from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from access import services as access
from access.models import AccessRequest, Grant
from accounts import sessions
from accounts.models import Department
from accounts.permissions import auditor_required, iam_admin_required, is_auditor, is_iam_admin, is_manager
from audit import service as audit
from audit.models import Action, AuditEvent
from directory import provisioning as ldap

from . import services
from .forms import DepartureForm, JoinerForm, MoverForm, ReasonForm
from .models import LifecycleEvent, LifecycleTask

User = get_user_model()


def _can_view(viewer, target):
    return is_auditor(viewer) or viewer.pk == target.pk or target.manager_id == viewer.pk


@login_required
@auditor_required
def user_list(request):
    qs = User.objects.select_related("department", "job_role", "manager")
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    dept = request.GET.get("department", "")
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
                       | Q(email__icontains=q) | Q(employee_id__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if dept:
        qs = qs.filter(department_id=dept)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "lifecycle/user_list.html", {
        "page": page, "q": q, "status": status, "dept": dept, "statuses": User.STATUSES,
        "departments": Department.objects.all()})


@login_required
def team(request):
    if not is_manager(request.user):
        messages.info(request, "You do not manage anyone.")
        return redirect("dashboard")
    reports = request.user.reports.select_related("department", "job_role")
    return render(request, "lifecycle/team.html", {"reports": reports})


@login_required
def user_detail(request, pk):
    target = get_object_or_404(User.objects.select_related("department", "job_role", "manager"), pk=pk)
    if not _can_view(request.user, target):
        raise Http404
    admin = is_iam_admin(request.user)
    return render(request, "lifecycle/user_detail.html", {
        "t": target, "admin": admin, "is_self": request.user.pk == target.pk,
        "grants": access.active_grants(target),
        "past_grants": Grant.objects.filter(user=target).exclude(
            pk__in=access.active_grants(target).values("pk")).select_related("entitlement")[:15],
        "sessions": sessions.active_sessions(target),
        "events": target.lifecycle_events.all()[:20],
        "tasks": target.lifecycle_tasks.all(),
        "requests": AccessRequest.objects.filter(requester=target).select_related("entitlement")[:10],
        "audit": AuditEvent.objects.filter(target_user=target)[:15] if is_auditor(request.user) else [],
        "credentials": request.session.pop("flash_credentials", None) if admin else None,
        "mover_form": MoverForm(initial={"department": target.department, "job_role": target.job_role,
                                         "manager": target.manager}, user=target) if admin else None,
        "departure_form": DepartureForm(initial={"last_working_day": target.last_working_day}) if admin else None,
    })


@login_required
@iam_admin_required
def user_create(request):
    form = JoinerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            user = services.provision_user(
                actor=request.user, username=d["username"], email=d["email"], first_name=d["first_name"],
                last_name=d["last_name"], phone=d["phone"], department=d["department"], job_role=d["job_role"],
                manager=d["manager"], start_date=d["start_date"])
        except services.LifecycleError as exc:
            form.add_error(None, str(exc))
        else:
            request.session["flash_credentials"] = {"username": user.username, "password": user.temp_password}
            messages.success(request, f"{user.display_name} has joined as {user.get_status_display().lower()}.")
            return redirect("user_detail", pk=user.pk)
    return render(request, "lifecycle/user_form.html", {"form": form})


def _admin_post(view):
    return login_required(iam_admin_required(require_POST(view)))


@login_required
@iam_admin_required
@require_POST
def user_move(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = MoverForm(request.POST, user=target)
    if form.is_valid():
        d = form.cleaned_data
        try:
            services.change_assignment(target, department=d["department"], job_role=d["job_role"],
                                       manager=d["manager"], actor=request.user)
            messages.success(request, "Assignment updated. Access was recalculated for the new role.")
        except services.LifecycleError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Could not read that form.")
    return redirect("user_detail", pk=pk)


@login_required
@iam_admin_required
@require_POST
def user_depart(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = DepartureForm(request.POST)
    if form.is_valid():
        try:
            services.schedule_departure(target, form.cleaned_data["last_working_day"], actor=request.user,
                                        reason=form.cleaned_data["reason"])
            messages.success(request, "Departure saved.")
        except services.LifecycleError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Enter a valid date.")
    return redirect("user_detail", pk=pk)


@login_required
@iam_admin_required
@require_POST
def user_terminate(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target.pk == request.user.pk:
        messages.error(request, "You cannot terminate your own account.")
    else:
        services.deprovision_user(target, actor=request.user, reason=request.POST.get("reason", "")[:120])
        messages.success(request, f"{target.display_name} has been deprovisioned: access, sessions and "
                                  "directory entry removed.")
    return redirect("user_detail", pk=pk)


@login_required
@iam_admin_required
@require_POST
def user_suspend(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target.pk == request.user.pk:
        messages.error(request, "You cannot suspend your own account.")
    else:
        try:
            services.suspend_user(target, actor=request.user, reason=request.POST.get("reason", "")[:120])
            messages.success(request, "Account suspended and signed out everywhere.")
        except services.LifecycleError as exc:
            messages.error(request, str(exc))
    return redirect("user_detail", pk=pk)


@login_required
@iam_admin_required
@require_POST
def user_reactivate(request, pk):
    target = get_object_or_404(User, pk=pk)
    try:
        services.reactivate_user(target, actor=request.user)
        messages.success(request, "Account reactivated.")
    except services.LifecycleError as exc:
        messages.error(request, str(exc))
    return redirect("user_detail", pk=pk)


@login_required
@iam_admin_required
@require_POST
def user_reset_password(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target.pk == request.user.pk:
        messages.error(request, "Use Change password for your own account.")
        return redirect("user_detail", pk=pk)
    if target.status == User.TERMINATED:
        messages.error(request, "Terminated accounts cannot be reset.")
        return redirect("user_detail", pk=pk)
    pw = services.temp_password()
    if target.source == User.LDAP:
        ldap.set_password(target, pw)
    else:
        target.set_password(pw)
    target.must_change_password = True
    target.failed_logins, target.locked_until = 0, None
    target.save()
    ended = sessions.revoke_all(target, "password_reset", actor=request.user)
    audit.log(Action.PASSWORD_RESET, actor=request.user, target=target, sessions_ended=ended)
    request.session["flash_credentials"] = {"username": target.username, "password": pw}
    messages.success(request, "Temporary password created. It is shown once, below.")
    return redirect("user_detail", pk=pk)


@login_required
@iam_admin_required
@require_POST
def user_force_logout(request, pk):
    target = get_object_or_404(User, pk=pk)
    n = sessions.revoke_all(target, "admin_forced_logout", actor=request.user)
    messages.success(request, f"{n} session(s) ended.")
    return redirect("user_detail", pk=pk)


@login_required
@iam_admin_required
@require_POST
def grant_revoke(request, pk):
    g = get_object_or_404(Grant, pk=pk)
    access.revoke(g, "revoked_by_admin", actor=request.user)
    messages.success(request, f"{g.entitlement.name} removed from {g.user.display_name}.")
    return redirect("user_detail", pk=g.user_id)


@login_required
@iam_admin_required
@require_POST
def grant_confirm(request, pk):
    g = get_object_or_404(Grant, pk=pk)
    g.needs_review = False
    g.save(update_fields=["needs_review"])
    messages.success(request, "Access confirmed as still needed.")
    return redirect("user_detail", pk=g.user_id)


@login_required
@require_POST
def task_toggle(request, pk):
    task = get_object_or_404(LifecycleTask, pk=pk)
    if not (is_iam_admin(request.user) or task.user.manager_id == request.user.pk):
        raise Http404
    task.done = not task.done
    task.done_at = timezone.now() if task.done else None
    task.done_by = request.user if task.done else None
    task.save()
    return redirect("user_detail", pk=task.user_id)


@login_required
@auditor_required
def events_list(request):
    kind = request.GET.get("kind", "")
    qs = LifecycleEvent.objects.select_related("user", "actor")
    if kind:
        qs = qs.filter(kind=kind)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "lifecycle/events.html", {"page": page, "kind": kind, "kinds": LifecycleEvent.KINDS})
