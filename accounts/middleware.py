from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from audit import service as audit
from audit.models import Action

from .models import UserSession

_EXEMPT_PREFIXES = ("/static/",)


class SessionGuardMiddleware:
    """Server-side session rules: revocation, absolute lifetime, status check, last-seen."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not request.path.startswith(_EXEMPT_PREFIXES):
            key = request.session.session_key
            us = UserSession.objects.filter(session_key=key).first()
            now = timezone.now()
            reason = None
            if us is None or us.ended_at is not None:
                reason = "revoked"
            elif now - us.created_at > timedelta(seconds=settings.ABSOLUTE_SESSION_SECONDS):
                reason = "expired"
            elif user.status != user.ACTIVE:
                reason = "account_disabled"
            if reason:
                request._logout_reason = reason
                if us is not None and us.ended_at is None:
                    us.ended_at, us.end_reason = now, reason
                    us.save(update_fields=["ended_at", "end_reason"])
                    audit.log(Action.SESSION_EXPIRED, actor=user, target=user, request=request, reason=reason)
                text = {
                    "revoked": "Your session was ended. Please sign in again.",
                    "expired": "Your session reached its maximum length. Please sign in again.",
                    "account_disabled": "Your account is no longer active.",
                }[reason]
                logout(request)
                messages.warning(request, text)
                return redirect(f"{reverse('login')}?next={request.path}")
            if now - us.last_seen > timedelta(seconds=60):
                UserSession.objects.filter(pk=us.pk).update(last_seen=now)
        return self.get_response(request)


class PasswordChangeRequiredMiddleware:
    """New and reset accounts must set their own password before doing anything else."""

    ALLOWED = ("/password/change/", "/logout/", "/static/", "/login/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (user is not None and user.is_authenticated and user.must_change_password
                and not request.path.startswith(self.ALLOWED)):
            messages.info(request, "Please choose a new password to continue.")
            return redirect("password_change")
        return self.get_response(request)


class NoStoreMiddleware:
    """Signed-in pages must never be cached, so Back after logout shows nothing."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith("/static/"):
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response["Pragma"] = "no-cache"
        return response
