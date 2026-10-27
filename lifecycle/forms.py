from django import forms
from django.contrib.auth import get_user_model

from accounts.models import Department, JobRole

User = get_user_model()


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kw):
        super().__init__(format="%Y-%m-%d", **kw)


def _managers():
    return User.objects.filter(status=User.ACTIVE).order_by("first_name", "last_name")


class JoinerForm(forms.Form):
    first_name = forms.CharField(max_length=60)
    last_name = forms.CharField(max_length=60)
    username = forms.CharField(max_length=60, help_text="Sign-in name, e.g. priya.sharma")
    email = forms.EmailField()
    phone = forms.CharField(max_length=30, required=False)
    department = forms.ModelChoiceField(Department.objects.all(), required=False)
    job_role = forms.ModelChoiceField(JobRole.objects.all(), required=False)
    manager = forms.ModelChoiceField(User.objects.none(), required=False)
    start_date = forms.DateField(required=False, widget=DateInput(),
                                 help_text="In the future = account stays pending until that day.")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["manager"].queryset = _managers()

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class MoverForm(forms.Form):
    department = forms.ModelChoiceField(Department.objects.all(), required=False)
    job_role = forms.ModelChoiceField(JobRole.objects.all(), required=False)
    manager = forms.ModelChoiceField(User.objects.none(), required=False)

    def __init__(self, *a, user=None, **kw):
        super().__init__(*a, **kw)
        self.fields["manager"].queryset = _managers().exclude(pk=user.pk if user else None)


class DepartureForm(forms.Form):
    last_working_day = forms.DateField(widget=DateInput(), required=False,
                                       help_text="Leave empty to cancel a scheduled departure.")
    reason = forms.CharField(max_length=120, required=False)


class ReasonForm(forms.Form):
    reason = forms.CharField(max_length=120, required=False)
