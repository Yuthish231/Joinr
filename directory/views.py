from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import iam_admin_required
from . import client, sync


@login_required
@iam_admin_required
def directory_status(request):
    ctx = {"enabled": settings.LDAP_ENABLED, "uri": settings.LDAP_SERVER_URI, "base_dn": settings.LDAP_BASE_DN,
           "user_ou": settings.LDAP_USER_OU, "write_back": settings.LDAP_WRITE_BACK,
           "result": request.session.pop("ldap_result", None)}
    if settings.LDAP_ENABLED:
        ctx["ok"], ctx["message"] = client.check()
    return render(request, "directory/status.html", ctx)


@login_required
@iam_admin_required
@require_POST
def directory_sync(request):
    if not settings.LDAP_ENABLED:
        messages.error(request, "LDAP is not enabled for this deployment.")
        return redirect("directory_status")
    try:
        request.session["ldap_result"] = sync.sync_all(actor=request.user)
        messages.success(request, "Directory sync finished.")
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f"Directory sync failed: {exc}")
    return redirect("directory_status")
