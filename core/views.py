from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from access import services as access
from access.models import AccessRequest, Grant
from accounts.models import UserSession
from accounts.permissions import is_auditor, is_iam_admin, is_manager
from audit.models import Action, AuditEvent
from lifecycle.models import LifecycleEvent

User = get_user_model()


@login_required
def dashboard(request):
    me = request.user
    now = timezone.now()
    ctx = {
        "my_grants": access.active_grants(me).count(),
        "my_pending": AccessRequest.objects.filter(requester=me, status=AccessRequest.PENDING).count(),
        "my_sessions": UserSession.objects.filter(user=me, ended_at__isnull=True).count(),
        "to_approve": len(access.pending_for(me)),
        "is_manager": is_manager(me),
    }
    if is_auditor(me):
        today = timezone.localdate()
        counts = {s: User.objects.filter(status=s).count() for s, _ in User.STATUSES}
        ctx.update({
            "counts": counts,
            "open_requests": AccessRequest.objects.filter(status=AccessRequest.PENDING).count(),
            "active_sessions": UserSession.objects.filter(ended_at__isnull=True).count(),
            "failed_24h": AuditEvent.objects.filter(action__in=[Action.LOGIN_FAIL, Action.LOGIN_LOCKED],
                                                   ts__gte=now - timedelta(hours=24)).count(),
            "needs_review": Grant.objects.filter(revoked_at__isnull=True, needs_review=True).count(),
            "expiring": Grant.objects.filter(revoked_at__isnull=True, expires_at__isnull=False,
                                             expires_at__lte=now + timedelta(days=7), expires_at__gt=now).count(),
            "departing": User.objects.filter(last_working_day__gte=today, last_working_day__lte=today + timedelta(days=14))
                         .exclude(status=User.TERMINATED).order_by("last_working_day")[:6],
            "starting": User.objects.filter(status=User.PENDING).order_by("start_date")[:6],
            "recent_events": LifecycleEvent.objects.select_related("user")[:8],
            "recent_audit": AuditEvent.objects.all()[:8],
            "admin": is_iam_admin(me),
        })
    return render(request, "core/dashboard.html", ctx)
