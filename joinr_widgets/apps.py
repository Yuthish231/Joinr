from django.apps import AppConfig


class JoinrWidgetsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "joinr_widgets"

    def ready(self):
        from joinr_widgets.widgets.file_widgets import patch_clearable_file_input

        patch_clearable_file_input()
