"""Granting, revoking and the request/approval workflow."""
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.permissions import is_iam_admin
from audit import service as audit
from audit.models import Action
from directory import provisioning as ldap

from .models import AccessRequest, ApprovalStep, Entitlement, Grant


class AccessError(Exception):
    """A business-rule refusal. The message is safe to show to the user."""


# --------------------------------------------------------------------------
# Grants
# --------------------------------------------------------------------------
def active_grants(user):
    now = timezone.now()
    return Grant.objects.filter(user=user, revoked_at__isnull=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    ).select_related("entitlement")


def policy_entitlements(user):
    """What this person should hold because of their department and job role."""
    q = Q()
    if user.department_id:
        q |= Q(departments=user.department_id)
    if user.job_role_id:
        q |= Q(job_roles=user.job_role_id)
    if not q:
        return Entitlement.objects.none()
    return Entitlement.objects.filter(q, is_active=True).distinct()


@transaction.atomic
def grant(user, entitlement, source, actor=None, request_obj=None, expires_at=None):
    existing = active_grants(user).filter(entitlement=entitlement).first()
    if existing:
        return existing
    g = Grant.objects.create(user=user, entitlement=entitlement, source=source, request=request_obj,
                             granted_by=actor, expires_at=expires_at)
    user.groups.add(entitlement.group)
    audit.log(Action.ACCESS_GRANTED, actor=actor, target=user, entitlement=entitlement.name, source=source,
              expires_at=expires_at.isoformat() if expires_at else None)
    ldap.add_to_group(user, entitlement)
    return g


@transaction.atomic
def revoke(g, reason, actor=None, action=Action.ACCESS_REVOKED):
    if g.revoked_at is not None:
        return g
    g.revoked_at = timezone.now()
    g.revoke_reason = reason
    g.save(update_fields=["revoked_at", "revoke_reason"])
    if not active_grants(g.user).filter(entitlement=g.entitlement).exists():
        g.user.groups.remove(g.entitlement.group)
        ldap.remove_from_group(g.user, g.entitlement)
    audit.log(action, actor=actor, target=g.user, entitlement=g.entitlement.name, reason=reason)
    return g


@transaction.atomic
def revoke_all(user, reason, actor=None):
    """Leaver clean-up: every grant, plus any group/permission added outside the catalog."""
    n = 0
    for g in Grant.objects.filter(user=user, revoked_at__isnull=True):
        revoke(g, reason, actor=actor)
        n += 1
    stray_groups = list(user.groups.values_list("name", flat=True))
    stray_perms = user.user_permissions.count()
    user.groups.clear()
    user.user_permissions.clear()
    if stray_groups or stray_perms:
        audit.log(Action.ACCESS_REVOKED, actor=actor, target=user, reason=reason,
                  stripped_groups=stray_groups, stripped_permissions=stray_perms)
    return n


@transaction.atomic
def sync_policy_grants(user, actor=None, reason="policy_change"):
    """Make the policy-driven grants match the user's department and job role."""
    wanted = set(policy_entitlements(user).values_list("pk", flat=True))
    granted, revoked = [], []
    for g in active_grants(user).filter(source=Grant.POLICY):
        if g.entitlement_id not in wanted:
            revoke(g, reason, actor=actor)
            revoked.append(g.entitlement.name)
    held = set(active_grants(user).values_list("entitlement_id", flat=True))
    for ent in Entitlement.objects.filter(pk__in=wanted - held):
        grant(user, ent, Grant.POLICY, actor=actor)
        granted.append(ent.name)
    return granted, revoked


def flag_for_review(user):
    return active_grants(user).exclude(source=Grant.POLICY).update(needs_review=True)


def expire_due(now=None):
    now = now or timezone.now()
    n = 0
    for g in Grant.objects.filter(revoked_at__isnull=True, expires_at__isnull=False, expires_at__lte=now):
        revoke(g, "expired", action=Action.ACCESS_EXPIRED)
        n += 1
    return n


# --------------------------------------------------------------------------
# Requests and approvals
# --------------------------------------------------------------------------
def _conflicts(user, entitlement):
    held = active_grants(user).values_list("entitlement_id", flat=True)
    return entitlement.conflicts_with.filter(pk__in=held)


@transaction.atomic
def create_request(requester, entitlement, justification, days=None):
    if requester.status != requester.ACTIVE:
        raise AccessError("Only active accounts can request access.")
    if not entitlement.is_active:
        raise AccessError("That access is no longer offered.")
    if active_grants(requester).filter(entitlement=entitlement).exists():
        raise AccessError("You already have this access.")
    if AccessRequest.objects.filter(requester=requester, entitlement=entitlement,
                                    status=AccessRequest.PENDING).exists():
        raise AccessError("You already have a pending request for this access.")
    clash = _conflicts(requester, entitlement).first()
    if clash:
        raise AccessError(f"Separation of duties: {entitlement.name} cannot be held together with {clash.name}.")
    if entitlement.max_days:
        days = min(days or entitlement.max_days, entitlement.max_days)

    req = AccessRequest.objects.create(requester=requester, entitlement=entitlement,
                                       justification=justification.strip(), duration_days=days)
    audit.log(Action.REQUEST_CREATED, actor=requester, target=requester, entitlement=entitlement.name,
              policy=entitlement.approval_policy)

    plan = []
    if entitlement.approval_policy in (Entitlement.MANAGER, Entitlement.MANAGER_OWNER):
        if requester.manager_id and requester.manager.status == requester.manager.ACTIVE:
            plan.append((ApprovalStep.MANAGER, requester.manager))
        else:
            plan.append((ApprovalStep.ADMIN, None))  # no manager to ask: an IAM admin decides
    if entitlement.approval_policy == Entitlement.MANAGER_OWNER:
        if entitlement.owner_id and entitlement.owner_id != requester.pk:
            plan.append((ApprovalStep.OWNER, entitlement.owner))
        else:
            plan.append((ApprovalStep.ADMIN, None))
    for i, (kind, approver) in enumerate(plan, start=1):
        ApprovalStep.objects.create(request=req, order=i, kind=kind, approver=approver)
    if not plan:  # automatic
        _finalise_approved(req, actor=None)
    return req


def can_decide(step, user):
    if step.status != ApprovalStep.PENDING or step.request.status != AccessRequest.PENDING:
        return False
    if step.request.requester_id == user.pk:
        return False  # nobody approves their own access
    if step.request.current_step is None or step.request.current_step.pk != step.pk:
        return False  # earlier steps first
    if step.kind == ApprovalStep.ADMIN:
        return is_iam_admin(user)
    return step.approver_id == user.pk or is_iam_admin(user)


def pending_for(user):
    steps = ApprovalStep.objects.filter(status=ApprovalStep.PENDING, request__status=AccessRequest.PENDING) \
        .select_related("request", "request__requester", "request__entitlement")
    return [s for s in steps if can_decide(s, user)]


@transaction.atomic
def decide(step, approver, approve, comment=""):
    if not can_decide(step, approver):
        raise AccessError("You cannot decide this step.")
    req = step.request
    step.status = ApprovalStep.APPROVED if approve else ApprovalStep.REJECTED
    step.decided_by, step.decided_at, step.comment = approver, timezone.now(), comment[:300]
    step.save()
    if not approve:
        req.steps.filter(status=ApprovalStep.PENDING).update(status=ApprovalStep.SKIPPED)
        req.status, req.decided_at = AccessRequest.REJECTED, timezone.now()
        req.save(update_fields=["status", "decided_at"])
        audit.log(Action.REQUEST_REJECTED, actor=approver, target=req.requester,
                  entitlement=req.entitlement.name, comment=comment)
        return req
    audit.log(Action.REQUEST_APPROVED, actor=approver, target=req.requester,
              entitlement=req.entitlement.name, step=step.kind)
    if req.current_step is None:
        _finalise_approved(req, actor=approver)
    return req


def _finalise_approved(req, actor):
    clash = _conflicts(req.requester, req.entitlement).first()
    if clash:  # something changed while it was waiting
        req.status, req.decided_at = AccessRequest.REJECTED, timezone.now()
        req.save(update_fields=["status", "decided_at"])
        audit.log(Action.REQUEST_REJECTED, actor=actor, target=req.requester, entitlement=req.entitlement.name,
                  comment=f"separation of duties vs {clash.name}", success=False)
        return
    req.status, req.decided_at = AccessRequest.APPROVED, timezone.now()
    req.save(update_fields=["status", "decided_at"])
    expires = timezone.now() + timedelta(days=req.duration_days) if req.duration_days else None
    grant(req.requester, req.entitlement, Grant.REQUEST, actor=actor, request_obj=req, expires_at=expires)


@transaction.atomic
def cancel_request(req, actor):
    if req.status != AccessRequest.PENDING:
        raise AccessError("Only pending requests can be cancelled.")
    req.status, req.decided_at = AccessRequest.CANCELLED, timezone.now()
    req.save(update_fields=["status", "decided_at"])
    req.steps.filter(status=ApprovalStep.PENDING).update(status=ApprovalStep.SKIPPED)
    audit.log(Action.REQUEST_CANCELLED, actor=actor, target=req.requester, entitlement=req.entitlement.name)


def cancel_pending_for(user, actor=None):
    n = 0
    for req in AccessRequest.objects.filter(requester=user, status=AccessRequest.PENDING):
        cancel_request(req, actor)
        n += 1
    return n
