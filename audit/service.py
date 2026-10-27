from .models import AuditEvent


def client_ip(request):
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


def log(action, *, actor=None, target=None, request=None, success=True, actor_label="", target_label="", **details):
    """Write one audit event. Never raises into the caller's business logic."""
    if actor is None and request is not None and getattr(request, "user", None) is not None \
            and request.user.is_authenticated:
        actor = request.user
    return AuditEvent.objects.create(
        action=action,
        actor=actor,
        actor_label=(actor.username if actor else actor_label) or "system",
        target_user=target,
        target_label=(target.username if target else target_label),
        ip=client_ip(request),
        success=success,
        details={k: (v if isinstance(v, (str, int, float, bool, type(None), list, dict)) else str(v))
                 for k, v in details.items()},
    )
