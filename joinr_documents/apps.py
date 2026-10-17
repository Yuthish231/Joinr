from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class JoinrDoumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "joinr_documents"
    verbose_name = _("Documents")
