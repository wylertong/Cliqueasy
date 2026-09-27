from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction


class Session(models.Model):
    class SessionType(models.TextChoices):
        SINGLES = "singles", "Singles"
        DOUBLES = "doubles", "Doubles"
        OPEN_PLAY = "open_play", "Open Play"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        FULL = "full", "Full"                  # unreachable until SessionParticipant exists
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"    # unreachable until the scheduled flip job exists

    class WaitlistMode(models.TextChoices):
        PRIORITY_CASCADE = "priority_cascade", "Priority Cascade"
        FCFS_BLAST = "fcfs_blast", "First-Come-First-Serve Blast"

    class ParticipantVisibility(models.TextChoices):
        VISIBLE = "visible", "Visible"
        HIDDEN = "hidden", "Hidden"

    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="created_sessions"
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    session_type = models.CharField(max_length=20, choices=SessionType.choices)
    date_time = models.DateTimeField()
    location_text = models.CharField(max_length=255)
    target_size = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    waitlist_mode = models.CharField(
        max_length=20, choices=WaitlistMode.choices, default=WaitlistMode.PRIORITY_CASCADE
    )
    participant_visibility = models.CharField(
        max_length=10, choices=ParticipantVisibility.choices, default=ParticipantVisibility.VISIBLE
    )
    waitlist_offer_window_minutes = models.PositiveIntegerField(default=30)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date_time"]

    @property
    def is_locked(self):
        return self.status in (self.Status.CANCELLED, self.Status.COMPLETED)

    def get_confirmed_participant_count(self):
        if self.pk is None:
            return 0
        return self.participants.filter(status=SessionParticipant.Status.CONFIRMED).count()

    def has_open_confirmed_slot(self):
        # False either at capacity, or when an existing waitlist means a brand
        # new joiner shouldn't skip ahead of people already waiting — that
        # spot is reserved for whoever's already queued, not a walk-up.
        return (
            self.get_confirmed_participant_count() < self.target_size
            and not self.participants.filter(status=SessionParticipant.Status.WAITLISTED).exists()
        )

    def next_waitlist_position(self):
        last = self.participants.filter(status=SessionParticipant.Status.WAITLISTED).aggregate(
            models.Max("position")
        )["position__max"]
        return (last or 0) + 1

    def recompact_waitlist(self, after_position):
        # Shifts every waitlisted participant past a freed position down by one.
        # Uses .update() to bypass SessionParticipant.clean() — this is internal
        # bookkeeping, not a user-driven status change subject to validation.
        if after_position is None:
            return
        self.participants.filter(
            status=SessionParticipant.Status.WAITLISTED, position__gt=after_position
        ).update(position=models.F("position") - 1)

    def sync_status(self):
        # Recomputes OPEN/FULL from confirmed count vs target_size, persisted via
        # .update() to bypass clean()'s cancelled/completed edit guard — per the
        # CLAUDE.md note on any code that transitions Session.status. The
        # status__in filter guards against clobbering a status (e.g. a
        # cancellation) that another request already committed since this
        # in-memory instance was loaded — if the row didn't match, someone else
        # already moved it to a terminal state, so this is a no-op.
        if self.status not in (self.Status.OPEN, self.Status.FULL):
            return
        new_status = self.Status.FULL if self.get_confirmed_participant_count() >= self.target_size else self.Status.OPEN
        if new_status != self.status:
            updated = Session.objects.filter(
                pk=self.pk, status__in=[self.Status.OPEN, self.Status.FULL]
            ).update(status=new_status)
            if updated:
                self.status = new_status

    def clean(self):
        super().clean()
        errors = {}
        original = None
        if self.pk:
            original = Session.objects.filter(pk=self.pk).only("waitlist_mode", "status", "target_size").first()

        target_size_changed = original is None or original.target_size != self.target_size
        if (
            target_size_changed
            and self.target_size is not None
            and self.target_size < self.get_confirmed_participant_count()
        ):
            errors["target_size"] = (
                "Target size cannot be less than the number of confirmed participants."
            )

        if original:
            if (
                original.waitlist_mode == self.WaitlistMode.FCFS_BLAST
                and self.waitlist_mode != self.WaitlistMode.FCFS_BLAST
            ):
                errors["waitlist_mode"] = (
                    "Once a session is switched to first-come-first-serve blast mode, "
                    "it cannot be switched back to priority cascade."
                )
            if original.is_locked:
                errors["__all__"] = (
                    "This session is cancelled or completed and can no longer be edited."
                )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title


class SessionInvite(models.Model):
    class Method(models.TextChoices):
        IN_APP_LINK = "in_app_link", "In-App Link"
        SMS = "sms", "SMS"                                    # unreachable this phase — no delivery mechanism yet
        GROUPCHAT_LINK = "groupchat_link", "Group Chat Link"  # unreachable this phase

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="invites")
    invited_category = models.ForeignKey(
        "categories.Category", on_delete=models.CASCADE, null=True, blank=True,
        related_name="session_invites",
    )
    invited_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
        related_name="session_invites",
    )
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.IN_APP_LINK)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "invited_user"], name="unique_invite_per_user_per_session"),
            models.UniqueConstraint(
                fields=["session", "invited_category"], name="unique_invite_per_category_per_session"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(invited_category__isnull=False, invited_user__isnull=True)
                    | models.Q(invited_category__isnull=True, invited_user__isnull=False)
                ),
                name="exactly_one_invite_target",
            ),
        ]

    def clean(self):
        super().clean()
        errors = []
        has_category = self.invited_category_id is not None
        has_user = self.invited_user_id is not None
        if has_category == has_user:
            errors.append("Exactly one of invited category or invited user must be set.")
        if self.session_id:
            session = Session.objects.filter(pk=self.session_id).only("status").first()
            if session and session.is_locked:
                errors.append("This session is cancelled or completed and can no longer receive new invites.")
        if errors:
            raise ValidationError({"__all__": errors})

    def __str__(self):
        target = self.invited_user or self.invited_category
        return f"Invite to {self.session} for {target}"


class SessionParticipant(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        WAITLISTED = "waitlisted", "Waitlisted"
        LEFT = "left", "Left"
        REMOVED = "removed", "Removed"

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="session_participations"
    )
    status = models.CharField(max_length=20, choices=Status.choices)
    # Only meaningful when status == WAITLISTED (waitlist rank). Left null for
    # confirmed/left/removed rows — not enforced by a DB constraint, just
    # convention followed by the views/service methods on Session.
    position = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "user"], name="unique_participant_per_session"),
            # Mirrors SessionInvite's exactly_one_invite_target pattern. Uses the
            # literal status value rather than SessionParticipant.Status.WAITLISTED
            # since this Meta class body executes in its own scope, before the
            # enclosing class (and its nested Status choices) exists as a name.
            models.CheckConstraint(
                condition=(
                    models.Q(status="waitlisted", position__isnull=False)
                    | (~models.Q(status="waitlisted") & models.Q(position__isnull=True))
                ),
                name="waitlist_position_set_iff_waitlisted",
            ),
        ]
        ordering = ["position", "created_at"]

    def clean(self):
        super().clean()
        errors = []
        if self.session_id:
            session = Session.objects.filter(pk=self.session_id).only("status", "target_size", "creator_id").first()
            if session:
                if session.is_locked:
                    errors.append("This session is cancelled or completed and can no longer accept new participants.")
                if self.user_id and session.creator_id == self.user_id:
                    errors.append("The session creator cannot join their own session as a participant.")
                if self.status == self.Status.CONFIRMED:
                    confirmed_count = (
                        SessionParticipant.objects.filter(session_id=self.session_id, status=self.Status.CONFIRMED)
                        .exclude(pk=self.pk)
                        .count()
                    )
                    if confirmed_count >= session.target_size:
                        errors.append("This session is already full.")
        if (self.status == self.Status.WAITLISTED) != (self.position is not None):
            errors.append("Waitlisted participants must have a position; others must not.")
        if errors:
            raise ValidationError({"__all__": errors})

    def deactivate(self, new_status):
        # Marks this participant LEFT/REMOVED, recompacting the waitlist and
        # resyncing the session's OPEN/FULL status as one atomic unit. Bypasses
        # full_clean() via save(update_fields=...) — like Session's own status
        # transitions (see CLAUDE.md), deactivating isn't subject to the
        # join-time validation in clean().
        with transaction.atomic():
            was_position = self.position
            was_waitlisted = self.status == self.Status.WAITLISTED
            self.status = new_status
            self.position = None
            self.save(update_fields=["status", "position", "updated_at"])
            if was_waitlisted:
                self.session.recompact_waitlist(after_position=was_position)
            self.session.sync_status()

    def __str__(self):
        return f"{self.user} in {self.session} ({self.status})"
