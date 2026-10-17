"""
AppConfig for the joinr_theme app
"""

from django.apps import AppConfig
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class JoinrThemeConfig(AppConfig):
    """App configuration class for joinr_theme."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "joinr_theme"
    verbose_name = _("Appearance")

    def ready(self):
        """Run app initialization logic (executed after Django setup).
        Used to auto-register URLs and connect signals if required.
        """
        try:
            # Auto-register this app's URLs and add to installed apps
            from django.urls import include, path

            from joinr.urls import urlpatterns

            settings.APPS.append(("joinr_theme"))
            # Add app URLs to main urlpatterns
            urlpatterns.append(
                path("theme/", include("joinr_theme.urls")),
            )

            __import__("joinr_theme.signals")
        except Exception as e:
            import logging

            logging.warning("JoinrThemeConfig.ready failed: %s", e)

        super().ready()
