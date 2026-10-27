from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from audit import service as audit
from audit.models import Action
from directory import client as ldap_client

from . import sessions
from .forms import ChangePasswordForm, DepartmentForm, JobRoleForm
from .models import Department, JobRole, User, UserSession
from .permissions import iam_admin_required, is_iam_admin


class JoinrLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def form_invalid(self, form):
        name = form.data.get("username", "")
        user = User.objects.filter(username__iexact=name).first() if name else None
        if user is not None and user.is_locked:
            until = timezone.localtime(user.locked_until)
            messages.error(self.request, f"Too many failed attempts. Try again after {until:%H:%M}.")
        return super().form_invalid(form)


@require_POST
def logout_view(request):
    """POST only: a link or image on another site must not be able to sign you out."""
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("login")


@login_required
def password_change(request):
    user = request.user
    form = ChangePasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        old, new = form.cleaned_data["old_password"], form.cleaned_data["new_password1"]
        ldap_user = user.source == User.LDAP
        ok = bool(ldap_client.authenticate(user.username, old)) if ldap_user and settings.LDAP_ENABLED \
            else user.check_password(old)
        if not ok:
            form.add_error("old_password", "That is not your current password.")
        else:
            try:
                if ldap_user and settings.LDAP_ENABLED:
                    ldap_client.set_password(user, new)
                else:
                    user.set_password(new)
            except Exception as exc:  # noqa: BLE001
                form.add_error(None, f"The directory refused the change: {exc}")
            else:
                user.must_change_password = False
                user.save()
                old_key = request.session.session_key
                update_session_auth_hash(request, user)  # keep THIS session signed in (Django rotates its key)
                UserSession.objects.filter(session_key=old_key).update(session_key=request.session.session_key)
                ended = sessions.revoke_all(user, "password_changed", actor=user,
                                            except_key=request.session.session_key)
                audit.log(Action.PASSWORD_CHANGED, actor=user, target=user, request=request, other_sessions_ended=ended)
                messages.success(request, "Password changed. Other devices were signed out.")
                return redirect("my_account")
    return render(request, "accounts/password_change.html", {"form": form, "forced": user.must_change_password})


@login_required
def my_account(request):
    mine = sessions.active_sessions(request.user)
    return render(request, "accounts/my_account.html", {
        "sessions": mine, "current_key": request.session.session_key,
        "idle_minutes": settings.SESSION_COOKIE_AGE // 60, "absolute_hours": settings.ABSOLUTE_SESSION_SECONDS // 3600,
        "max_sessions": settings.MAX_CONCURRENT_SESSIONS})


@login_required
@require_POST
def session_revoke(request, pk):
    us = get_object_or_404(UserSession, pk=pk)
    if us.user_id != request.user.pk and not is_iam_admin(request.user):
        messages.error(request, "That session is not yours.")
        return redirect("my_account")
    current = us.session_key == request.session.session_key
    sessions.revoke(us, "revoked_by_user" if us.user_id == request.user.pk else "revoked_by_admin",
                    actor=request.user)
    if current:
        messages.success(request, "Signed out.")
        return redirect("login")
    messages.success(request, "Session ended.")
    return redirect(request.POST.get("next") or "my_account")


@login_required
@require_POST
def sessions_revoke_others(request):
    n = sessions.revoke_all(request.user, "logout_everywhere", actor=request.user,
                            except_key=request.session.session_key)
    messages.success(request, f"{n} other session(s) ended.")
    return redirect("my_account")


@login_required
@iam_admin_required
def sessions_all(request):
    active = UserSession.objects.filter(ended_at__isnull=True).select_related("user")
    return render(request, "accounts/sessions_all.html", {"sessions": active, "current_key": request.session.session_key})


# ------------------------------ organisation structure ------------------------------
@login_required
@iam_admin_required
def org(request):
    return render(request, "accounts/org.html", {
        "departments": Department.objects.all(), "roles": JobRole.objects.select_related("department"),
        "dept_form": DepartmentForm(prefix="d"), "role_form": JobRoleForm(prefix="r")})


@login_required
@iam_admin_required
@require_POST
def org_add(request, kind):
    form_class, prefix = (DepartmentForm, "d") if kind == "department" else (JobRoleForm, "r")
    form = form_class(request.POST, prefix=prefix)
    if form.is_valid():
        obj = form.save()
        audit.log(Action.CATALOG_CHANGED, request=request, target_label=str(obj), kind=kind, change="created")
        messages.success(request, f"{kind.title()} added.")
    else:
        messages.error(request, "; ".join(f"{k}: {', '.join(v)}" for k, v in form.errors.items()))
    return redirect("org")


@login_required
@iam_admin_required
def org_edit(request, kind, pk):
    model, form_class = (Department, DepartmentForm) if kind == "department" else (JobRole, JobRoleForm)
    obj = get_object_or_404(model, pk=pk)
    form = form_class(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.log(Action.CATALOG_CHANGED, request=request, target_label=str(obj), kind=kind, change="edited")
        messages.success(request, "Saved.")
        return redirect("org")
    return render(request, "accounts/org_edit.html", {"form": form, "kind": kind, "obj": obj})
