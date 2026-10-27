from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import iam_admin_required, is_auditor, is_iam_admin
from audit import service as audit
from audit.models import Action

from . import services
from .forms import DecisionForm, EntitlementForm, RequestForm
from .models import AccessRequest, Entitlement, Grant


@login_required
def catalog(request):
    held = set(services.active_grants(request.user).values_list("entitlement_id", flat=True))
    pending = set(AccessRequest.objects.filter(requester=request.user, status=AccessRequest.PENDING)
                  .values_list("entitlement_id", flat=True))
    return render(request, "access/catalog.html", {
        "entitlements": Entitlement.objects.prefetch_related("departments", "job_roles").select_related("owner"),
        "held": held, "pending": pending, "admin": is_iam_admin(request.user)})


@login_required
def my_access(request):
    form = RequestForm(initial={"entitlement": request.GET.get("entitlement")})
    return render(request, "access/my_access.html", {
        "grants": services.active_grants(request.user),
        "requests": AccessRequest.objects.filter(requester=request.user).select_related("entitlement")[:20],
        "form": form})


@login_required
@require_POST
def request_create(request):
    form = RequestForm(request.POST)
    if form.is_valid():
        try:
            req = services.create_request(request.user, form.cleaned_data["entitlement"],
                                          form.cleaned_data["justification"], form.cleaned_data["days"])
        except services.AccessError as exc:
            messages.error(request, str(exc))
        else:
            if req.status == AccessRequest.APPROVED:
                messages.success(request, f"{req.entitlement.name} was granted straight away.")
            else:
                messages.success(request, "Request sent for approval.")
            return redirect("request_detail", pk=req.pk)
    else:
        messages.error(request, "Please choose the access and explain why you need it (10+ characters).")
    return redirect("my_access")


@login_required
def request_detail(request, pk):
    req = get_object_or_404(AccessRequest.objects.select_related("requester", "entitlement"), pk=pk)
    steps = list(req.steps.select_related("approver", "decided_by"))
    deciders = [s for s in steps if services.can_decide(s, request.user)]
    involved = req.requester_id == request.user.pk or any(s.approver_id == request.user.pk for s in steps)
    if not (involved or is_auditor(request.user)):
        raise Http404
    return render(request, "access/request_detail.html", {
        "req": req, "steps": steps, "step_to_decide": deciders[0] if deciders else None,
        "can_cancel": req.requester_id == request.user.pk and req.status == AccessRequest.PENDING,
        "form": DecisionForm()})


@login_required
@require_POST
def request_decide(request, pk):
    from .models import ApprovalStep
    step = get_object_or_404(ApprovalStep, pk=pk)
    approve = request.POST.get("decision") == "approve"
    try:
        req = services.decide(step, request.user, approve, request.POST.get("comment", ""))
        messages.success(request, "Approved." if approve else "Rejected.")
    except services.AccessError as exc:
        messages.error(request, str(exc))
        req = step.request
    return redirect("request_detail", pk=req.pk)


@login_required
@require_POST
def request_cancel(request, pk):
    req = get_object_or_404(AccessRequest, pk=pk, requester=request.user)
    try:
        services.cancel_request(req, request.user)
        messages.success(request, "Request cancelled.")
    except services.AccessError as exc:
        messages.error(request, str(exc))
    return redirect("my_access")


@login_required
def approvals(request):
    return render(request, "access/approvals.html", {"steps": services.pending_for(request.user)})


@login_required
@iam_admin_required
def requests_all(request):
    status = request.GET.get("status", "")
    qs = AccessRequest.objects.select_related("requester", "entitlement")
    if status:
        qs = qs.filter(status=status)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "access/requests_all.html", {"page": page, "status": status,
                                                        "statuses": AccessRequest.STATUSES})


@login_required
@iam_admin_required
def entitlement_edit(request, pk=None):
    obj = get_object_or_404(Entitlement, pk=pk) if pk else None
    form = EntitlementForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        ent = form.save()
        audit.log(Action.CATALOG_CHANGED, request=request, target_label=ent.name, kind="entitlement",
                  change="edited" if obj else "created", approval=ent.approval_policy, risk=ent.risk)
        messages.success(request, "Saved.")
        return redirect("catalog")
    return render(request, "access/entitlement_form.html", {"form": form, "obj": obj})


@login_required
@iam_admin_required
def grants_review(request):
    """Everything kept across a job move that still needs somebody to confirm it."""
    pending = Grant.objects.filter(revoked_at__isnull=True, needs_review=True).select_related("user", "entitlement")
    return render(request, "access/review.html", {"grants": pending})
