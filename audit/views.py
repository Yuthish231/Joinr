import csv

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from accounts.permissions import auditor_required
from .models import AuditEvent, verify_chain


def _filtered(request):
    qs = AuditEvent.objects.all()
    q = request.GET.get("q", "").strip()
    action = request.GET.get("action", "").strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(actor_label__icontains=q) | Q(target_label__icontains=q))
    if action:
        qs = qs.filter(action__startswith=action)
    return qs, q, action


@login_required
@auditor_required
def audit_list(request):
    qs, q, action = _filtered(request)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    groups = ["login", "logout", "session", "password", "lifecycle", "access", "request", "ldap", "catalog"]
    return render(request, "audit/list.html", {"page": page, "q": q, "action": action, "groups": groups})


@login_required
@auditor_required
def audit_export(request):
    qs, _q, _a = _filtered(request)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="audit.csv"'
    w = csv.writer(resp)
    w.writerow(["time", "action", "actor", "target", "ip", "success", "details", "hash"])
    for e in qs[:5000]:
        w.writerow([e.ts.isoformat(), e.action, e.actor_label, e.target_label, e.ip, e.success, e.details, e.hash])
    return resp


@login_required
@auditor_required
@require_POST
def audit_verify(request):
    ok, bad = verify_chain()
    ctx = {"ok": ok, "bad": bad, "total": AuditEvent.objects.count()}
    return render(request, "audit/verify.html", ctx)
