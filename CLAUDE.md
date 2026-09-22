# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Cliquey is a social coordination layer for organizing casual tennis sessions — it is explicitly **not** a court-booking system; sessions carry time/place as plain info, not an enforced resource. Full product spec and data model: `Planning/tennis-app-mvp-spec.md`. Tech stack rationale (hosting, email provider, deployment): `Planning/cliquey-tech-stack.md`.

The repo is currently at the end of **Phase 1 (foundation)**: accounts/auth, and the `Session`/`Category` models with CRUD. Deliberately not yet built — see the spec's "Explicitly Deferred" section — `SessionInvite`, the join/waitlist flow (`SessionParticipant`), the waitlist cascade engine (`WaitlistCascade`/`WaitlistOffer`), `Notification`/email sending, `SessionMessage` chat, the underfilled-session scheduled job, and deployment. The `waitlist` and `notifications` apps exist only as empty scaffolds reserved for that later work.

## Commands

All commands run through Docker Compose; there is no local (non-Docker) Python environment.

```bash
docker compose up -d --build          # start Postgres + Django dev server (localhost:8000)
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py test                    # full suite
docker compose exec web python manage.py test sessions           # one app
docker compose exec web python manage.py test sessions.tests.test_models.TargetSizeFloorTests.test_decrease_below_confirmed_count_raises  # one test
docker compose exec web python manage.py shell
docker compose down                    # stop (add -v to also wipe the Postgres volume/data)
```

Copy `.env.example` to `.env` before first run (not committed).

**Migration gotcha:** the `sessions` app's Django `app_label` is `tennis_sessions`, not `sessions` — it was renamed in `sessions/apps.py` to avoid colliding with the built-in `django.contrib.sessions` app, which also claims the label `sessions`. Running `manage.py makemigrations sessions` silently targets the wrong (built-in) app and reports "No changes detected." Use `manage.py makemigrations tennis_sessions` for this app. `categories`/`accounts` have no such collision.

**Docker bind-mount permissions (macOS):** if files created inside the container aren't writable from the host or vice versa: `docker compose exec web chown -R $(id -u):$(id -g) .`

## Architecture

- Django 5, one app per domain concept: `accounts` (custom User + auth), `sessions` (`Session` model/CRUD), `categories` (`Category`/`CategoryMember`), plus empty `waitlist`/`notifications` scaffolds for a later phase.
- Settings (`config/settings.py`) are driven by `django-environ` reading `.env`; `DATABASES` always points at the Docker `db` Postgres service in local dev (no SQLite fallback).
- `accounts.models.User` is a custom `AUTH_USER_MODEL` (`AbstractUser` + unique `email` + `phone`), set before the first migration ever ran. Because of this, `accounts`'s initial migration must always apply before any other app's — this is already encoded via Django's swappable-dependency migration graph, but keep it in mind if migrations are ever hand-edited.
- Business validation for `Session` lives in `Session.clean()` (`sessions/models.py`), not only in a form — this means `full_clean()`, the Django admin, and `SessionForm` all enforce the same rules: the target-size floor (can't drop below `get_confirmed_participant_count()`, currently stubbed to `0` until `SessionParticipant` exists), the one-way `waitlist_mode` switch (`priority_cascade` → `fcfs_blast` only, never back), and a guard against editing `cancelled`/`completed` sessions. **Any future code that transitions `Session.status`** (a cancel action, a scheduled completed-flip job) **must bypass `full_clean()`** — e.g. via `.update()` or `save(update_fields=[...])` — or it will be blocked by the very guard it's trying to satisfy.
- `SessionForm.date_time` (`sessions/forms.py`) explicitly overrides both `input_formats` and the widget's `format` to `"%Y-%m-%dT%H:%M"`. This is load-bearing: Django's default `DATETIME_INPUT_FORMATS` doesn't include the ISO "T"-separated format that `<input type="datetime-local">` submits, so removing this override breaks both form submission and the edit form's pre-filled value.
- Categories are private and one-way: only the creator ever sees or manages a category, members are never notified. `CategoryForm.clean_name()` (`categories/forms.py`) enforces per-creator name uniqueness at the form layer — required in addition to the DB's `unique_category_name_per_creator` constraint because `creator` isn't itself a form field (it's set in the view after validation), so Django's normal ModelForm uniqueness check can't see it.
- Templates are server-rendered Django templates with Tailwind loaded via CDN `<script>` tag (no build step, no HTMX yet). `templates/base.html` is the shared layout; nav links to routes that may not exist yet use the `{% url 'name' as var %}{% if var %}...{% endif %}` pattern so they degrade gracefully instead of raising `NoReverseMatch` — follow this pattern for any future nav link to an app that might not have its URLs defined yet.
- Local dev email backend is Django's console backend (prints to stdout) — no real provider is wired up yet; that's deferred to the notifications phase.
- Test layout: `sessions` uses a `tests/` package (`test_models.py`, `test_views.py`) since it has the most business logic; `accounts` and `categories` use a single `tests.py`. Follow whichever pattern matches the app you're touching.
