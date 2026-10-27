from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.JoinrLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("password/change/", views.password_change, name="password_change"),
    path("account/", views.my_account, name="my_account"),
    path("account/sessions/<int:pk>/end/", views.session_revoke, name="session_revoke"),
    path("account/sessions/end-others/", views.sessions_revoke_others, name="sessions_revoke_others"),
    path("sessions/", views.sessions_all, name="sessions_all"),
    path("organisation/", views.org, name="org"),
    path("organisation/<str:kind>/add/", views.org_add, name="org_add"),
    path("organisation/<str:kind>/<int:pk>/", views.org_edit, name="org_edit"),
]
