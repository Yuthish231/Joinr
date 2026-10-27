from django.urls import path

from . import views

urlpatterns = [
    path("catalog/", views.catalog, name="catalog"),
    path("catalog/new/", views.entitlement_edit, name="entitlement_new"),
    path("catalog/<int:pk>/", views.entitlement_edit, name="entitlement_edit"),
    path("access/", views.my_access, name="my_access"),
    path("access/request/", views.request_create, name="request_create"),
    path("requests/", views.requests_all, name="requests_all"),
    path("requests/<int:pk>/", views.request_detail, name="request_detail"),
    path("requests/<int:pk>/cancel/", views.request_cancel, name="request_cancel"),
    path("steps/<int:pk>/decide/", views.request_decide, name="request_decide"),
    path("approvals/", views.approvals, name="approvals"),
    path("review/", views.grants_review, name="grants_review"),
]
