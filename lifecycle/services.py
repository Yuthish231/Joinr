"""Joiner / mover / leaver. The only place identity state changes, so every change is audited."""
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from access import services as access
from access.models import AccessRequest, ApprovalStep, Entitlement
from accounts import sessions
from audit import service as audit
from audit.models import Action
from directory import provisioning as ldap

from .models import LifecycleEvent, LifecycleTask

User = get_user_model()

JOINER_TASKS = [
    ("Account and baseline access created", True),
    ("Welcome and first-day briefing", False),
    ("Equipment issued", False),
    ("Manager confirms required access", False),
]
LEAVER_TASKS = [
    ("Login disabled", True),
    ("Roles, groups and permissions removed", True),
    ("Active sessions terminated", True),
    ("Directory entry disabled", True),
    ("Equipment returned", False),
    ("Knowledge transfer completed", False),
]


class LifecycleError(Exception):
    """A business-rule refusal. The message is safe to show to the user."""


def temp_password():
    return secrets.token_urlsafe(settings.TEMP_PASSWORD_LENGTH)[: settings.TEMP_PASSWORD_LENGTH]


def _event(user, kind, actor, summary, **details):
    return LifecycleEvent.objects.create(user=user, kind=kind, actor=actor, summary=summary, details=details)


def _tasks(user, phase, items):
    now = timezone.now()
    for title, auto in items:
        LifecycleTask.objects.create(user=user, phase=phase, title=title, automatic=auto,
                                     done=auto, done_at=now if auto else None)


def _tick(user, phase, title):
    LifecycleTask.objects.filter(user=user, phase=phase, title=title, done=False).update(
        done=True, done_at=timezone.now())


# --------------------------------------------------------------------------
# Joiner
# --------------------------------------------------------------------------
@transaction.atomic
def provision_user(*, actor=None, username, email, first_name="", last_name="", department=None, job_role=None,
                   manager=None, start_date=None, employee_id=None, phone="", source=User.LOCAL, ldap_dn="",
                   via="manual"):
    """Create an identity, give it its birthright access and (if configured) its directory entry."""
    if User.objects.filter(username__iexact=username).exists():
        raise LifecycleError(f"The username '{username}' is already taken.")
    if User.objects.filter(email__iexact=email).exists():
        raise LifecycleError(f"The email '{email}' is already in use.")
    if job_role and department and job_role.department_id and job_role.department_id != department.pk:
        raise LifecycleError("That job role belongs to a different department.")

    today = timezone.localdate()
    pending = bool(start_date and start_date > today)
    # With a directory configured, new people live there and sign in through it.
    directory_backed = source == User.LDAP or (settings.LDAP_ENABLED and settings.LDAP_WRITE_BACK)
    password = None if source == User.LDAP else temp_password()

    user = User(username=username, email=email, first_name=first_name, last_name=last_name, phone=phone,
                department=department, job_role=job_role, manager=manager, start_date=start_date,
                employee_id=employee_id, source=User.LDAP if directory_backed else User.LOCAL, ldap_dn=ldap_dn,
                status=User.PENDING if pending else User.ACTIVE, must_change_password=password is not None)
    user.set_unusable_password() if (password is None or directory_backed) else user.set_password(password)
    user.save()
    if not user.employee_id:
        user.employee_id = f"JNR{user.pk:04d}"
        user.save(update_fields=["employee_id"])

    # Directory entry first, so group memberships below point at a person who exists.
    if password and directory_backed and not ldap_dn:
        ldap.create_entry(user, password)
    granted = []
    if not pending:
        granted, _ = access.sync_policy_grants(user, actor=actor, reason="joiner")

    audit.log(Action.USER_JOINED, actor=actor, target=user, via=via, department=getattr(department, "name", None),
              job_role=getattr(job_role, "title", None), status=user.status, baseline_access=granted)
    _event(user, LifecycleEvent.JOINER, actor, f"Joined as {job_role or 'new starter'}"
           f"{' in ' + department.name if department else ''}"
           f"{' (starts ' + start_date.isoformat() + ')' if pending else ''}", baseline_access=granted, via=via)
    _tasks(user, LifecycleTask.JOINER, JOINER_TASKS)
    user.temp_password = password
    return user


@transaction.atomic
def activate_user(user, actor=None):
    if user.status != User.PENDING:
        return user
    user.status = User.ACTIVE
    user.save(update_fields=["status"])
    granted, _ = access.sync_policy_grants(user, actor=actor, reason="start_date")
    audit.log(Action.USER_ACTIVATED, actor=actor, target=user, baseline_access=granted)
    _event(user, LifecycleEvent.ACTIVATED, actor, "Start date reached: account activated", baseline_access=granted)
    return user


# --------------------------------------------------------------------------
# Mover
# --------------------------------------------------------------------------
@transaction.atomic
def change_assignment(user, *, department, job_role, manager, actor=None, via="manual", write_back=True):
    if user.status == User.TERMINATED:
        raise LifecycleError("Terminated accounts cannot be moved.")
    if job_role and department and job_role.department_id and job_role.department_id != department.pk:
        raise LifecycleError("That job role belongs to a different department.")
    if manager and manager.pk == user.pk:
        raise LifecycleError("A person cannot manage themselves.")
    if department == user.department and job_role == user.job_role and manager == user.manager:
        return user

    before = {"department": getattr(user.department, "name", None), "job_role": getattr(user.job_role, "title", None),
              "manager": getattr(user.manager, "username", None)}
    org_changed = department != user.department or job_role != user.job_role
    user.department, user.job_role, user.manager = department, job_role, manager
    user.save(update_fields=["department", "job_role", "manager"])
    after = {"department": getattr(department, "name", None), "job_role": getattr(job_role, "title", None),
             "manager": getattr(manager, "username", None)}

    granted, revoked, flagged = [], [], 0
    if org_changed and user.status == User.ACTIVE:
        granted, revoked = access.sync_policy_grants(user, actor=actor, reason="mover")
        flagged = access.flag_for_review(user)  # requested/manual access is kept but must be re-confirmed
    if write_back and org_changed:
        ldap.update_entry(user)

    audit.log(Action.USER_MOVED, actor=actor, target=user, via=via, before=before, after=after,
              granted=granted, revoked=revoked, flagged_for_review=flagged)
    _event(user, LifecycleEvent.MOVER, actor,
           f"Moved: {before['department'] or '-'} / {before['job_role'] or '-'} -> "
           f"{after['department'] or '-'} / {after['job_role'] or '-'}",
           before=before, after=after, granted=granted, revoked=revoked, flagged_for_review=flagged, via=via)
    return user


# --------------------------------------------------------------------------
# Suspend / reactivate
# --------------------------------------------------------------------------
@transaction.atomic
def suspend_user(user, actor=None, reason=""):
    if user.status != User.ACTIVE:
        raise LifecycleError("Only active accounts can be suspended.")
    user.status = User.SUSPENDED
    user.save(update_fields=["status"])
    ended = sessions.revoke_all(user, "account_suspended", actor=actor)
    audit.log(Action.USER_SUSPENDED, actor=actor, target=user, reason=reason, sessions_ended=ended)
    _event(user, LifecycleEvent.SUSPENDED, actor, f"Suspended{': ' + reason if reason else ''}")
    return user


@transaction.atomic
def reactivate_user(user, actor=None):
    if user.status != User.SUSPENDED:
        raise LifecycleError("Only suspended accounts can be reactivated.")
    user.status = User.ACTIVE
    user.save(update_fields=["status"])
    audit.log(Action.USER_REACTIVATED, actor=actor, target=user)
    _event(user, LifecycleEvent.REACTIVATED, actor, "Reactivated")
    return user


# --------------------------------------------------------------------------
# Leaver
# --------------------------------------------------------------------------
@transaction.atomic
def schedule_departure(user, last_working_day, actor=None, reason=""):
    if user.status == User.TERMINATED:
        raise LifecycleError("This account is already terminated.")
    user.last_working_day = last_working_day
    user.save(update_fields=["last_working_day"])
    if last_working_day is None:
        audit.log(Action.DEPARTURE_SCHEDULED, actor=actor, target=user, last_working_day=None, cleared=True)
        _event(user, LifecycleEvent.SCHEDULED, actor, "Departure cancelled")
        return user
    audit.log(Action.DEPARTURE_SCHEDULED, actor=actor, target=user, last_working_day=last_working_day.isoformat(),
              reason=reason)
    _event(user, LifecycleEvent.SCHEDULED, actor, f"Last working day set to {last_working_day:%d %b %Y}",
           reason=reason)
    if _departure_due(user, timezone.localtime()):
        deprovision_user(user, actor=actor, reason=reason or "last working day reached")
    return user


@transaction.atomic
def deprovision_user(user, actor=None, reason="", write_back=True):
    """Remove every trace of access. Safe to call twice."""
    if user.status == User.TERMINATED:
        return user
    now = timezone.now()
    user.status = User.TERMINATED
    user.terminated_at = now
    user.must_change_password = False
    user.set_unusable_password()
    user.save()

    revoked = access.revoke_all(user, reason or "leaver", actor=actor)
    cancelled = access.cancel_pending_for(user, actor=actor)
    # Work that was waiting on this person moves to the IAM admins.
    ApprovalStep.objects.filter(approver=user, status=ApprovalStep.PENDING).update(
        kind=ApprovalStep.ADMIN, approver=None)
    Entitlement.objects.filter(owner=user).update(owner=None)
    handed_over = list(user.reports.values_list("username", flat=True))
    user.reports.update(manager=user.manager)
    ended = sessions.revoke_all(user, "account_terminated", actor=actor)
    if write_back:
        ldap.disable_entry(user)

    for title in ("Login disabled", "Roles, groups and permissions removed", "Active sessions terminated",
                  "Directory entry disabled"):
        _tick(user, LifecycleTask.LEAVER, title)
    if not user.lifecycle_tasks.filter(phase=LifecycleTask.LEAVER).exists():
        _tasks(user, LifecycleTask.LEAVER, LEAVER_TASKS)

    audit.log(Action.USER_LEFT, actor=actor, target=user, reason=reason, grants_revoked=revoked,
              requests_cancelled=cancelled, sessions_ended=ended, reports_reassigned=handed_over)
    _event(user, LifecycleEvent.LEAVER, actor, f"Left: access removed{' (' + reason + ')' if reason else ''}",
           grants_revoked=revoked, sessions_ended=ended, requests_cancelled=cancelled)
    return user


# --------------------------------------------------------------------------
# Scheduler
# --------------------------------------------------------------------------
def _departure_due(user, now_local):
    """Access ends at the cut-off hour of the last working day, or any time after that day."""
    lwd = user.last_working_day
    if lwd is None:
        return False
    today = now_local.date()
    return today > lwd or (today == lwd and now_local.hour >= settings.LEAVER_CUTOFF_HOUR)


def run_due(now=None):
    """One scheduler pass: start dates, last working days, expiring grants."""
    now_local = timezone.localtime(now or timezone.now())
    today = now_local.date()
    result = {"activated": 0, "departed": 0, "expired_grants": 0}
    for user in User.objects.filter(status=User.PENDING, start_date__lte=today):
        activate_user(user)
        result["activated"] += 1
    leavers = User.objects.filter(last_working_day__isnull=False).exclude(status=User.TERMINATED)
    for user in leavers:
        if _departure_due(user, now_local):
            deprovision_user(user, reason="last working day reached")
            result["departed"] += 1
    result["expired_grants"] = access.expire_due(now)
    return result
