from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from django.utils import timezone

from audit import service as audit
from audit.models import Action

from . import sessions


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    if request is None:
        return
    user.failed_logins = 0
    user.locked_until = None
    user.save(update_fields=["failed_logins", "locked_until"])
    sessions.register_session(request, user)
    audit.log(Action.LOGIN_OK, actor=user, target=user, request=request)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is None or request is None:
        return
    key = request.session.session_key
    from .models import UserSession
    us = UserSession.objects.filter(session_key=key, ended_at__isnull=True).first()
    if us:
        us.ended_at = timezone.now()
        us.end_reason = getattr(request, "_logout_reason", "logout")
        us.save(update_fields=["ended_at", "end_reason"])
    if getattr(request, "_logout_reason", "logout") == "logout":
        audit.log(Action.LOGOUT, actor=user, target=user, request=request)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    User = get_user_model()
    name = (credentials or {}).get("username", "")
    user = User.objects.filter(username__iexact=name).first() if name else None
    if user is None:
        audit.log(Action.LOGIN_FAIL, actor_label=name or "unknown", request=request, success=False, reason="unknown_user")
        return
    if user.locked_until and user.locked_until > timezone.now():
        audit.log(Action.LOGIN_LOCKED, actor=user, target=user, request=request, success=False,
                  until=user.locked_until.isoformat())
        return
    user.failed_logins += 1
    if user.failed_logins >= settings.LOCKOUT_THRESHOLD:
        user.locked_until = timezone.now() + timedelta(minutes=settings.LOCKOUT_MINUTES)
        user.failed_logins = 0
        user.save(update_fields=["failed_logins", "locked_until"])
        audit.log(Action.LOGIN_LOCKED, actor=user, target=user, request=request, success=False,
                  until=user.locked_until.isoformat(), reason="threshold_reached")
    else:
        user.save(update_fields=["failed_logins"])
        audit.log(Action.LOGIN_FAIL, actor=user, target=user, request=request, success=False,
                  attempts=user.failed_logins)
