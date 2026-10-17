from django.apps import AppConfig


class BackupConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "joinr_backup"

    def ready(self):
        from django.urls import include, path

        from joinr.urls import urlpatterns

        urlpatterns.append(
            path("backup/", include("joinr_backup.urls")),
        )
        super().ready()
