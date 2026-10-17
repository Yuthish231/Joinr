"""
joinr_automation/views/views.py
"""

from django import forms
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _

from joinr.decorators import hx_request_required, login_required, permission_required
from joinr.http.response import JoinrRedirect
from joinr_automations.methods.methods import generate_choices
from joinr_automations.methods.serialize import serialize_form
from joinr_automations.models import MailAutomation
from joinr_automations.signals import REFRESH_METHODS
from joinr_views.generic.cbv.views import JoinrFormView


@login_required
def get_to_field(request):
    """
    This method is to render `mail to` fields
    """
    model_path = request.GET.get("model")

    if not model_path:
        return JoinrRedirect(
            request,
            message=_("No matching query found."),
        )

    try:
        to_fields, mail_details_choice, model_class = generate_choices(model_path)
    except LookupError:
        return JsonResponse({"error": _("No matching query found.")}, status=400)

    class InstantModelForm(forms.ModelForm):
        """
        InstantModelForm
        """

        class Meta:
            model = model_class
            fields = "__all__"

    serialized_form = serialize_form(InstantModelForm(), "automation_multiple_")

    return JsonResponse(
        {
            "choices": to_fields,
            "mail_details_choice": mail_details_choice,
            "serialized_form": serialized_form,
        }
    )


@login_required
@permission_required("joinr_automations.delete_mailautomation")
def delete_automation(request, pk):
    """
    Automation delete view
    """
    try:
        MailAutomation.objects.get(id=pk).delete()
        messages.success(request, _("Automation deleted"))
    except Exception as e:
        print(e)
        messages.error(request, _("Something went wrong"))
    return redirect(reverse("mail-automations-view"))


@login_required
@permission_required("joinr_automations.view_mailautomation")
def mail_automations_settings_view(request):
    """
    Mail Automation settings page. Migrated from the Configuration menu into
    Settings > Mail; reuses the existing nav/list HTMX endpoints.
    """
    return render(
        request,
        "joinr_automations/mail_automations_settings.html",
    )


@login_required
@hx_request_required
@permission_required("joinr_automations.add_mailautomation")
def refresh_automations(request):
    """
    Method to  refresh automation signals
    """
    refreshed = False

    if REFRESH_METHODS.get("clear_connection"):
        REFRESH_METHODS["clear_connection"]()
        refreshed = True

    if REFRESH_METHODS.get("start_connection"):
        REFRESH_METHODS["start_connection"]()
        refreshed = True

    if refreshed:
        messages.success(request, _("Automations refreshed successfully."))
    else:
        messages.error(request, _("Automation method not available to refresh."))

    return JoinrFormView.HttpResponse()
