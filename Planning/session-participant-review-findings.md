# Code review findings: SessionParticipant join/leave/waitlist

Reviewed 2026-09-26. Scope: the uncommitted diff adding the `SessionParticipant` model,
`SessionJoinView`/`SessionLeaveView`/`SessionRemoveParticipantView`, waitlist position
tracking, and `Session.sync_status()`/`recompact_waitlist()` (touches `sessions/models.py`,
`sessions/views.py`, `sessions/admin.py`, `sessions/urls.py`, related templates, and the new
`sessions/migrations/0003_sessionparticipant.py` / `sessions/tests/test_participants.py`).

Method: 8 parallel finder passes (line-by-line, removed-behavior, cross-file, reuse,
simplification, efficiency, altitude, CLAUDE.md conventions) → deduped to 11 distinct
candidates → each independently verified against the code. 10 survived verification (1
refuted: the `participant_visibility`/roster-privacy gap is explicitly documented in-code as
an intentional deferral, not an oversight, so it isn't listed below).

**Instruction to whoever picks this up:** work through these before starting the next
feature — several are load-bearing correctness bugs in the capacity/waitlist invariants that
later phases (waitlist cascade engine, notifications) will build on top of. Fix in the order
listed; #1–#3 are related (same root cause) and worth fixing together.

---

### 1. No capacity ceiling anywhere — concurrent joins can overbook a session
**File:** `sessions/views.py:141`, `sessions/models.py:189` (`SessionParticipant.clean()`)
**Verdict:** PLAUSIBLE (race)

`SessionJoinView` computes `has_room = session.get_confirmed_participant_count() <
session.target_size` with no locking, and `SessionParticipant.clean()` never checks confirmed
count against `target_size` (only `Session.clean()` has a floor check, not a ceiling on the
participant side). Two different users can both read `has_room=True` and both save as
CONFIRMED — the `unique_participant_per_session` constraint only blocks a duplicate
`(session, user)` pair, not two distinct users.

**Fix direction:** wrap the check-then-save in `transaction.atomic()` with
`select_for_update()` on the session, or add a ceiling check inside
`SessionParticipant.clean()` mirroring `Session.clean()`'s floor check, or both.

### 2. Waitlist queue-jumping — a new joiner can skip ahead of everyone waiting
**File:** `sessions/views.py:141` (`SessionJoinView`), `172` (`SessionLeaveView`)
**Verdict:** CONFIRMED

`has_room` only compares confirmed-count to target_size and never checks for an existing
non-empty waitlist. Nothing anywhere promotes a waitlisted participant to CONFIRMED when a
spot frees up. So: target_size=1, A confirmed, B waitlisted(1). A leaves → session flips back
to OPEN. The next brand-new user C to click Join is instantly CONFIRMED, jumping B entirely.

**Fix direction:** on leave/remove, if the session isn't full and a waitlist exists, promote
the front of the waitlist to CONFIRMED before flipping status — or at minimum, block new
CONFIRMED joins while a non-empty waitlist exists and route them into the waitlist instead.

### 3. Overbooked sessions become permanently uneditable
**File:** `sessions/models.py:86` (`Session.clean()`)
**Verdict:** CONFIRMED

The target_size floor check (`target_size < get_confirmed_participant_count()`) fires on
*every* edit, not only when target_size itself changes — unlike the adjacent `waitlist_mode`
check a few lines below, which correctly compares against the original value to detect an
actual transition. So if #1 ever overbooks a session, the creator can no longer save *any*
edit (even to an unrelated field like description) until participants are manually reduced.

**Fix direction:** only raise this error when `target_size` is actually being decreased below
the confirmed count, e.g. compare against the original `target_size` the same way the
`waitlist_mode` check does.

### 4. Unhandled 500 on double-submit join
**File:** `sessions/views.py:162`
**Verdict:** PLAUSIBLE (race)

`participant.save()` after `full_clean()` has no `IntegrityError` handling. A double-click or
two open tabs can have both requests see `existing=None` and both pass `full_clean()`'s
uniqueness check before either commits; the second `save()` then raises an uncaught
`IntegrityError` (violating `unique_participant_per_session`) instead of showing "you're
already in this session."

**Fix direction:** catch `IntegrityError` around `participant.save()` and treat it the same as
the existing "already in this session" branch, or serialize via `transaction.atomic()` +
`select_for_update()` as part of fixing #1.

### 5. `sync_status()` can silently revert a concurrent cancellation
**File:** `sessions/models.py:71`
**Verdict:** CONFIRMED

The guard `if self.status not in (OPEN, FULL): return` checks only the in-memory `self.status`,
and the `.update()` call filters solely on `pk` — no `status__in=[OPEN, FULL]` in the WHERE
clause. If a session is cancelled by another request between when this instance was loaded and
when `sync_status()` runs, the stale in-memory check passes and the `.update()` silently
overwrites the just-written CANCELLED back to OPEN/FULL.

**Fix direction:** add `status__in=[Status.OPEN, Status.FULL]` to the `.update()`'s filter so
it's a no-op if another request already moved the session to a terminal state.

### 6. Waitlist `position`/`status` invariant unenforced — admin can corrupt it
**File:** `sessions/models.py:179` (field), `189` (`clean()`), `sessions/admin.py`
**Verdict:** CONFIRMED

"`position` only meaningful when WAITLISTED" is documented only as a comment, not enforced by
`clean()` or a `CheckConstraint`. `SessionParticipant` is registered in the plain Django admin
with no custom form, so a staff user can save a WAITLISTED row with `position=None` (or vice
versa). `next_waitlist_position()`'s `Max(position)` and `recompact_waitlist()`'s
`position__gt=...` filter both silently exclude NULL rows in SQL, so the corrupted row is
invisible to all position bookkeeping and renders as `#None` in the template.

**Fix direction:** add validation in `SessionParticipant.clean()` (position is not None iff
status == WAITLISTED), and/or a `CheckConstraint` mirroring the existing
`exactly_one_invite_target` pattern already used on `SessionInvite` in the same file.

### 7. Duplicate waitlist positions possible under concurrent joins
**File:** `sessions/models.py:54` (`next_waitlist_position()`)
**Verdict:** PLAUSIBLE (race)

Reads `Max(position)` with no locking. Two concurrent `confirm_waitlist` POSTs can both read
the same max and both save with the same computed position — there's no unique constraint on
`(session, position)` to catch it.

**Fix direction:** same `select_for_update()`/`transaction.atomic()` treatment as #1, scoped
to the session's waitlisted rows.

### 8. "My Sessions" leaks cancelled/completed sessions
**File:** `sessions/views.py:19` (`HomeView.get_context_data`, `my_sessions` query)
**Verdict:** CONFIRMED

The new `my_sessions` query has no CANCELLED/COMPLETED exclusion, unlike the sibling
`open_to_join_sessions` query a few lines below, which explicitly excludes them (added
deliberately in a recent prior commit: "fix: exclude completed sessions from Open to Join").
No test exercises a cancelled/completed session in `HomeViewMySessionsTests`, so it's unclear
whether this is intentional (keep as history) or an overlooked parity gap.

**Fix direction:** decide the intended behavior (likely: still show cancelled sessions the
user was part of, since that's meaningful history — but confirm with product intent), then add
a test locking in whichever behavior is chosen.

### 9. Inconsistent error handling on double-remove
**File:** `sessions/views.py:200` (`SessionRemoveParticipantView`) vs `172` (`SessionLeaveView`)
**Verdict:** CONFIRMED

`SessionRemoveParticipantView`'s `get_object_or_404` is scoped to
`status__in=[CONFIRMED, WAITLISTED]`, so removing an already-inactive participant (e.g. a
double-submit from two tabs) raises a hard `Http404`. `SessionLeaveView` handles the identical
situation gracefully via `.filter(...).first()` + a redirect with a message.

**Fix direction:** mirror `SessionLeaveView`'s pattern — look up without the status filter,
then branch on whether it's still active, redirecting with a friendly message if not.

### 10. Non-atomic leave/remove write sequence
**File:** `sessions/views.py:187` (`SessionLeaveView`), `209` (`SessionRemoveParticipantView`)
**Verdict:** PLAUSIBLE

`participant.save()`, `session.recompact_waitlist()`, and `session.sync_status()` run as three
separate un-transacted writes. A fault between steps (e.g. between save and recompact) leaves
a permanent gap in waitlist positions, since `recompact_waitlist` only shifts positions greater
than the passed `after_position` rather than renumbering the whole queue on a later call.

**Fix direction:** wrap the three calls in `transaction.atomic()`.

---

## Also noted (lower priority, not blocking)

- **Reuse:** the CANCELLED/COMPLETED status-lookup guard is now duplicated across
  `Session.clean()`, `SessionInvite.clean()`, `SessionParticipant.clean()`, and
  `SessionJoinView` — worth a shared helper (e.g. `Session.is_locked` property) if a fourth
  copy ever appears.
- **Reuse:** `SessionLeaveView` and `SessionRemoveParticipantView` bodies are near-identical
  (capture position/waitlisted flag, mutate, save, recompact, sync) — worth extracting into a
  `SessionParticipant.deactivate(new_status)` model method.
- **Efficiency:** `confirmed_participants`/`waitlisted_participants` querysets in
  `SessionDetailView` lack `.select_related("user")`, causing an N+1 on roster rendering.
- **Efficiency:** `recompact_waitlist()` loops with one `.update()` per row instead of a single
  bulk `.update(position=F('position') - 1)`.
- **Conventions:** `sessions/tests/test_participants.py` mixes model and view tests in one
  file, rather than following the app's documented `tests/test_models.py` /
  `tests/test_views.py` split (CLAUDE.md).
