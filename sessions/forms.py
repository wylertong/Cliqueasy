from django import forms

from .models import Session

# Django's default DATETIME_INPUT_FORMATS doesn't include the ISO "T"-separated
# format that <input type="datetime-local"> submits (e.g. "2026-01-01T14:30"), so
# both the field's input_formats (parsing on submit) and the widget's format
# (rendering an existing value back into the input on the edit form) must be set
# explicitly — without this, valid-looking submissions fail with "Enter a valid
# date/time" and edit forms silently show a blank date/time picker.
DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"


class SessionForm(forms.ModelForm):
    date_time = forms.DateTimeField(
        input_formats=[DATETIME_LOCAL_FORMAT],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DATETIME_LOCAL_FORMAT),
    )

    class Meta:
        model = Session
        fields = [
            "title", "description", "session_type", "date_time", "location_text",
            "target_size", "participant_visibility", "waitlist_mode",
            "waitlist_offer_window_minutes",
        ]
