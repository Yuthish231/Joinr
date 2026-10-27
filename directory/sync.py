"""Mirror directory users into Joinr and apply lifecycle rules to the differences."""
from django.contrib.auth import get_user_model
from django.db import transaction

from accounts.models import Department, JobRole
from audit import service as audit
from audit.models import Action

from . import client


def _lookup_org(entry):
    dept = Department.objects.filter(code=entry["department"]).first() if entry["department"] else None
    role = None
    if entry["title"]:
        role = JobRole.objects.filter(title__iexact=entry["title"], department=dept).first() \
            or JobRole.objects.filter(title__iexact=entry["title"]).first()
        if role is None:
            role = JobRole.objects.create(title=entry["title"], department=dept)
    return dept, role


@transaction.atomic
def upsert_user(entry, via="sync", actor=None):
    """Create or update the local user for a directory entry. Returns the user (or None)."""
    from lifecycle import services as lifecycle  # local import: lifecycle uses directory.provisioning

    User = get_user_model()
    username = entry["uid"]
    if not username:
        return None
    dept, role = _lookup_org(entry)
    user = User.objects.filter(username__iexact=username).first()

    if user is None:
        if entry["disabled"]:
            return None  # never import someone who is already disabled
        return lifecycle.provision_user(
            actor=actor, username=username, email=entry["mail"] or f"{username}@invalid.local",
            first_name=entry["first_name"], last_name=entry["last_name"], department=dept, job_role=role,
            employee_id=entry["employee_id"] or None, source=User.LDAP, ldap_dn=entry["dn"], via=f"ldap:{via}",
        )

    changed = []
    for field, value in (("first_name", entry["first_name"]), ("last_name", entry["last_name"]),
                         ("email", entry["mail"]), ("ldap_dn", entry["dn"])):
        if value and getattr(user, field) != value:
            setattr(user, field, value)
            changed.append(field)
    if user.source != User.LDAP:
        user.source = User.LDAP
        user.set_unusable_password()
        changed += ["source", "password"]
    if changed:
        user.save()

    if entry["disabled"] and user.status != User.TERMINATED:
        lifecycle.deprovision_user(user, actor=actor, reason="disabled in directory", write_back=False)
    elif not entry["disabled"] and user.status == User.ACTIVE and (
            (dept and dept != user.department) or (role and role != user.job_role)):
        lifecycle.change_assignment(user, department=dept or user.department, job_role=role or user.job_role,
                                    manager=user.manager, actor=actor, via=f"ldap:{via}", write_back=False)
    return user


def sync_all(actor=None):
    """Full pass over the directory. Returns a summary dict."""
    User = get_user_model()
    summary = {"created": 0, "updated": 0, "moved": 0, "disabled": 0, "total": 0, "errors": []}
    for entry in client.fetch_users():
        summary["total"] += 1
        before = User.objects.filter(username__iexact=entry["uid"]).values_list("status", "department_id",
                                                                               "job_role_id").first()
        try:
            user = upsert_user(entry, via="sync", actor=actor)
        except Exception as exc:  # noqa: BLE001 - one bad entry must not stop the pass
            summary["errors"].append(f"{entry['uid']}: {exc}")
            continue
        if user is None:
            continue
        if before is None:
            summary["created"] += 1
        else:
            if before[0] != User.TERMINATED and user.status == User.TERMINATED:
                summary["disabled"] += 1
            elif (before[1], before[2]) != (user.department_id, user.job_role_id):
                summary["moved"] += 1
            else:
                summary["updated"] += 1
    audit.log(Action.LDAP_SYNC, actor=actor, **{k: v for k, v in summary.items() if k != "errors"},
              errors=len(summary["errors"]))
    return summary
