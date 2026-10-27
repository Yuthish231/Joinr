from django.urls import include, path

urlpatterns = [
    path("", include("accounts.urls")),
    path("", include("access.urls")),
    path("", include("lifecycle.urls")),
    path("", include("directory.urls")),
    path("", include("audit.urls")),
    path("", include("core.urls")),
]
