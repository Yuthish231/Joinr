from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class JoinrAuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "joinr_auth"
    verbose_name = _("Joinr Auth")
