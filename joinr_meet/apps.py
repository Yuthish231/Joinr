from django.apps import AppConfig
from django.conf import settings


class JoinrMeetConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "joinr_meet"
    verbose_name = "Meet"

    def ready(self):
        from django.urls import include, path

        from joinr.urls import urlpatterns
        from joinr_meet import signals

        settings.APPS.append("joinr_meet")

        urlpatterns.append(
            path("meet/", include("joinr_meet.urls")),
        )
        super().ready()
