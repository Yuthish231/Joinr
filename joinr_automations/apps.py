"""
App configuration for the Joinr Automations app.
Initializes model choices and starts automation when the server runs.
"""

import logging
import os
import sys

from django.apps import AppConfig
from django.core.exceptions import AppRegistryNotReady, ImproperlyConfigured
from django.db.utils import DatabaseError
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


class JoinrAutomationConfig(AppConfig):
    """Configuration class for the Joinr Automations Django app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "joinr_automations"
    verbose_name = _("Automations")

    def ready(self) -> None:
        ready = super().ready()
        if any(
            cmd in sys.argv
            for cmd in [
                "makemigrations",
                "migrate",
                "compilemessages",
                "flush",
                "shell",
            ]
        ):
            return ready
        try:

            from base.templatetags.joinrfilters import app_installed
            from employee.models import Employee
            from joinr_automations.methods.methods import get_related_models
            from joinr_automations.models import MODEL_CHOICES

            recruitment_installed = False
            if app_installed("recruitment"):
                recruitment_installed = True

            models = [Employee]
            if recruitment_installed:
                from recruitment.models import Candidate

                models.append(Candidate)

            main_models = models
            for main_model in main_models:
                related_models = get_related_models(main_model)

                for model in related_models:
                    path = f"{model.__module__}.{model.__name__}"
                    MODEL_CHOICES.append((path, model.__name__))
            MODEL_CHOICES.append(("employee.models.Employee", "Employee"))
            MODEL_CHOICES.append(
                ("pms.models.EmployeeKeyResult", "Employee Key Results")
            )

            MODEL_CHOICES = list(set(MODEL_CHOICES))
            try:
                from joinr_automations.signals import start_automation

                start_automation()
            except DatabaseError as error:
                # Tables are not present yet on a fresh database; the
                # post_migrate hook re-runs this once they are.
                logger.debug("automations not started yet: %s", error)
        except (AppRegistryNotReady, ImproperlyConfigured, ImportError) as error:
            # MODEL_CHOICES is assembled from other apps' models, so this can
            # fire while the registry is still loading. Narrowed from a bare
            # except, which also hid a genuine failure here and left
            # MODEL_CHOICES half-built with the automations unregistered and
            # nothing logged at all.
            logger.warning("automation model choices incomplete: %s", error)
        return ready
