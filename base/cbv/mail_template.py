"""
This page handles the cbv methods for mail template page
"""

from typing import Any

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _

from base.forms import MailTemplateForm
from base.models import JoinrMailTemplate
from joinr.http.response import JoinrRedirect
from joinr_views.cbv_methods import login_required, permission_required
from joinr_views.generic.cbv.views import JoinrFormView, JoinrNavView


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("base.add_joinrmailtemplate"), name="dispatch")
class MailTemplateFormView(JoinrFormView):
    """
    form view for create and edit mail template
    """

    form_class = MailTemplateForm
    model = JoinrMailTemplate
    template_name = "cbv/mail_template/form_inherit.html"
    new_display_title = _("Add Template")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.form.instance.pk:
            self.form_class.verbose_name = _("Update Template")
        context["searchWords"] = self.form.get_template_language()

        return context

    def form_valid(self, form: MailTemplateForm) -> HttpResponse:
        if form.is_valid():
            if form.instance.pk:
                message = _("Template Updated")
            else:
                message = _("Template created")
            form.save()

            messages.success(self.request, message)
            return JoinrRedirect(self.request)
        return super().form_valid(form)


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("base.add_joinrmailtemplate"), name="dispatch")
class MailTemplateDuplicateForm(JoinrFormView):
    """
    from view for duplicate mail templates
    """

    model = JoinrMailTemplate
    form_class = MailTemplateForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        original_object = JoinrMailTemplate.objects.get(id=self.kwargs["pk"])
        form = self.form_class(instance=original_object)

        for field_name, field in form.fields.items():
            if isinstance(field, forms.CharField):
                initial_value = form.initial.get(field_name, "")
                if initial_value:
                    initial_value += " (copy)"
                form.initial[field_name] = initial_value
                form.fields[field_name].initial = initial_value

        if hasattr(form.instance, "id"):
            form.instance.id = None

        context["form"] = form
        self.form_class.verbose_name = _("Duplicate Template")
        return context

    def form_invalid(self, form: Any) -> HttpResponse:
        self.form_class.verbose_name = _("Duplicate Template")
        if not form.is_valid():
            errors = form.errors.as_data()
            return render(
                self.request, self.template_name, {"form": form, "errors": errors}
            )
        return super().form_invalid(form)

    def form_valid(self, form: MailTemplateForm) -> HttpResponse:
        form = self.form_class(self.request.POST)
        self.form_class.verbose_name = _("Duplicate Template")
        if form.is_valid():
            message = _("Template Added")
            messages.success(self.request, message)
            form.save()
            return JoinrRedirect(self.request)
        return self.form_invalid(form)


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("base.view_joinrmailtemplate"), name="dispatch")
class MailTemplateNavView(JoinrNavView):
    """
    Mail Template Nav View
    """

    nav_title = _("Mail Templates")
    search_url = None
    template_name = "generic/inline_nav.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.create_attrs = f"""
            hx-get="{reverse_lazy('mail-template-create-form')}"
            data-toggle="oh-modal-toggle"
            data-target="#objectCreateModal"
            hx-target="#objectCreateModalTarget"
        """
