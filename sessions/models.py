from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


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

    def get_confirmed_participant_count(self):
        # Replace with self.participants.filter(status=SessionParticipant.Status.CONFIRMED).count()
        # once SessionParticipant exists (later phase).
        return 0

    def clean(self):
        super().clean()
        errors = {}
        if self.target_size is not None and self.target_size < self.get_confirmed_participant_count():
            errors["target_size"] = (
                "Target size cannot be less than the number of confirmed participants."
            )
        if self.pk:
            original = Session.objects.filter(pk=self.pk).values("waitlist_mode", "status").first()
            if original:
                if (
                    original["waitlist_mode"] == self.WaitlistMode.FCFS_BLAST
                    and self.waitlist_mode != self.WaitlistMode.FCFS_BLAST
                ):
                    errors["waitlist_mode"] = (
                        "Once a session is switched to first-come-first-serve blast mode, "
                        "it cannot be switched back to priority cascade."
                    )
                if original["status"] in (self.Status.CANCELLED, self.Status.COMPLETED):
                    errors["__all__"] = (
                        "This session is cancelled or completed and can no longer be edited."
                    )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title
