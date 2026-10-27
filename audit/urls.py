from django.urls import path

from . import views

urlpatterns = [
    path("audit/", views.audit_list, name="audit_list"),
    path("audit/export/", views.audit_export, name="audit_export"),
    path("audit/verify/", views.audit_verify, name="audit_verify"),
]
