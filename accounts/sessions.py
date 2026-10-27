"""Session management: track, cap, revoke. All server-side."""
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.utils import timezone

from audit import service as audit
from audit.models import Action

from .models import UserSession


def register_session(request, user):
    """Called at login. Creates the tracking row and enforces the concurrent-session cap."""
    key = request.session.session_key
    if not key:
        request.session.save()
        key = request.session.session_key
    us, _ = UserSession.objects.update_or_create(
        session_key=key,
        defaults={
            "user": user,
            "ip": request.META.get("REMOTE_ADDR") or None,
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:250],
            "created_at": timezone.now(),
            "last_seen": timezone.now(),
            "ended_at": None,
            "end_reason": "",
        },
    )
    cap = settings.MAX_CONCURRENT_SESSIONS
    if cap:
        active = list(UserSession.objects.filter(user=user, ended_at__isnull=True).order_by("created_at"))
        for old in active[: max(0, len(active) - cap)]:
            revoke(old, "concurrent_limit", actor=user)
    return us


def revoke(us, reason, actor=None):
    """End one session now: delete the server-side session and mark the row."""
    if us.ended_at is None:
        us.ended_at = timezone.now()
        us.end_reason = reason
        us.save(update_fields=["ended_at", "end_reason"])
        audit.log(Action.SESSION_REVOKED, actor=actor, target=us.user, reason=reason, ip_of_session=us.ip)
    Session.objects.filter(session_key=us.session_key).delete()


def revoke_all(user, reason, actor=None, except_key=None):
    """End every active session of a user. Returns how many were ended."""
    n = 0
    for us in UserSession.objects.filter(user=user, ended_at__isnull=True):
        if except_key and us.session_key == except_key:
            continue
        revoke(us, reason, actor=actor)
        n += 1
    # Belt and braces: any Django session tied to this user that has no tracking row.
    for s in Session.objects.all().iterator():
        try:
            data = SessionStore(session_key=s.session_key).load()
        except Exception:
            continue
        if str(data.get("_auth_user_id")) == str(user.pk) and s.session_key != except_key:
            s.delete()
    return n


def active_sessions(user):
    return UserSession.objects.filter(user=user, ended_at__isnull=True)
