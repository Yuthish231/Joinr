from django.conf import settings

from accounts.permissions import is_auditor, is_iam_admin, is_manager


def app(request):
    user = getattr(request, "user", None)
    params = request.GET.copy() if hasattr(request, "GET") else {}
    if hasattr(params, "pop"):
        params.pop("page", None)
    qs = params.urlencode() + "&" if params and hasattr(params, "urlencode") and params.urlencode() else ""
    ctx = {"APP_NAME": "Joinr", "LDAP_ENABLED": settings.LDAP_ENABLED, "qs": qs}
    if user is not None and user.is_authenticated:
        ctx.update({"nav_admin": is_iam_admin(user), "nav_auditor": is_auditor(user),
                    "nav_manager": is_manager(user)})
        try:
            from access import services
            ctx["nav_approvals"] = len(services.pending_for(user))
        except Exception:  # noqa: BLE001 - never break a page over a badge
            ctx["nav_approvals"] = 0
    return ctx
