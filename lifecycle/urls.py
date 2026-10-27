from django.urls import path

from . import views

urlpatterns = [
    path("people/", views.user_list, name="user_list"),
    path("people/new/", views.user_create, name="user_create"),
    path("people/<int:pk>/", views.user_detail, name="user_detail"),
    path("people/<int:pk>/move/", views.user_move, name="user_move"),
    path("people/<int:pk>/departure/", views.user_depart, name="user_depart"),
    path("people/<int:pk>/terminate/", views.user_terminate, name="user_terminate"),
    path("people/<int:pk>/suspend/", views.user_suspend, name="user_suspend"),
    path("people/<int:pk>/reactivate/", views.user_reactivate, name="user_reactivate"),
    path("people/<int:pk>/reset-password/", views.user_reset_password, name="user_reset_password"),
    path("people/<int:pk>/force-logout/", views.user_force_logout, name="user_force_logout"),
    path("grants/<int:pk>/revoke/", views.grant_revoke, name="grant_revoke"),
    path("grants/<int:pk>/confirm/", views.grant_confirm, name="grant_confirm"),
    path("tasks/<int:pk>/toggle/", views.task_toggle, name="task_toggle"),
    path("team/", views.team, name="team"),
    path("lifecycle/", views.events_list, name="lifecycle_events"),
]
