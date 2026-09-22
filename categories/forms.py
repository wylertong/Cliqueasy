from django import forms
from django.contrib.auth import get_user_model

from .models import Category

User = get_user_model()


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name"]

    def __init__(self, *args, creator=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.creator = creator

    def clean_name(self):
        name = self.cleaned_data["name"]
        if self.creator and Category.objects.filter(creator=self.creator, name=name).exists():
            raise forms.ValidationError("You already have a category with this name. Choose a new name.")
        return name


class AddMemberForm(forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.none())

    def __init__(self, *args, category=None, **kwargs):
        super().__init__(*args, **kwargs)
        existing_member_ids = category.members.values_list("user_id", flat=True)
        self.fields["user"].queryset = User.objects.exclude(
            pk__in=list(existing_member_ids) + [category.creator_id]
        )
