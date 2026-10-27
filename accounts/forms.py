from django import forms
from django.contrib.auth import password_validation

from .models import Department, JobRole


class ChangePasswordForm(forms.Form):
    old_password = forms.CharField(label="Current password", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
    new_password1 = forms.CharField(label="New password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    new_password2 = forms.CharField(label="Repeat new password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def __init__(self, user, *a, **kw):
        super().__init__(*a, **kw)
        self.user = user

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("new_password1"), data.get("new_password2")
        if p1 and p2:
            if p1 != p2:
                self.add_error("new_password2", "The two passwords do not match.")
            else:
                if p1 == data.get("old_password"):
                    self.add_error("new_password1", "Choose a password you have not used just now.")
                try:
                    password_validation.validate_password(p1, self.user)
                except forms.ValidationError as exc:
                    self.add_error("new_password1", exc)
        return data


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name", "code", "description"]


class JobRoleForm(forms.ModelForm):
    class Meta:
        model = JobRole
        fields = ["title", "department", "description"]
