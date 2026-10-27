from django.urls import path

from . import views

urlpatterns = [
    path("directory/", views.directory_status, name="directory_status"),
    path("directory/sync/", views.directory_sync, name="directory_sync"),
]
