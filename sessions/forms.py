from django import forms
from django.contrib.auth import get_user_model

from categories.models import Category
from .models import Session

User = get_user_model()

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


class InviteCategoryForm(forms.Form):
    category = forms.ModelChoiceField(queryset=Category.objects.none())

    def __init__(self, *args, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        already_invited_ids = session.invites.filter(invited_category__isnull=False).values_list(
            "invited_category_id", flat=True
        )
        self.fields["category"].queryset = Category.objects.filter(creator=session.creator).exclude(
            pk__in=list(already_invited_ids)
        )


class InviteUsersForm(forms.Form):
    users = forms.ModelMultipleChoiceField(queryset=User.objects.none())

    def __init__(self, *args, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        already_invited_ids = session.invites.filter(invited_user__isnull=False).values_list(
            "invited_user_id", flat=True
        )
        self.fields["users"].queryset = User.objects.exclude(
            pk__in=list(already_invited_ids) + [session.creator_id]
        )
