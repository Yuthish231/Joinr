from django import forms

from .models import Entitlement


class EntitlementForm(forms.ModelForm):
    class Meta:
        model = Entitlement
        fields = ["name", "code", "description", "risk", "approval_policy", "owner", "max_days",
                  "departments", "job_roles", "conflicts_with", "is_active"]
        widgets = {
            "departments": forms.CheckboxSelectMultiple,
            "job_roles": forms.CheckboxSelectMultiple,
            "conflicts_with": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        if self.instance.pk:
            self.fields["conflicts_with"].queryset = Entitlement.objects.exclude(pk=self.instance.pk)


class RequestForm(forms.Form):
    entitlement = forms.ModelChoiceField(Entitlement.objects.none())
    justification = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), min_length=10,
                                    help_text="Why do you need this? Approvers will read it.")
    days = forms.IntegerField(required=False, min_value=1, max_value=365, label="For how many days?",
                              help_text="Leave empty for no expiry (where allowed).")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["entitlement"].queryset = Entitlement.objects.filter(is_active=True)


class DecisionForm(forms.Form):
    comment = forms.CharField(max_length=300, required=False)
