from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from django.utils import timezone


class Entitlement(models.Model):
    """A named piece of access. Backed by a Django Group so it carries real permissions."""

    LOW, MEDIUM, HIGH = "low", "medium", "high"
    RISKS = [(LOW, "Low"), (MEDIUM, "Medium"), (HIGH, "High")]
    AUTO, MANAGER, MANAGER_OWNER = "auto", "manager", "manager_owner"
    POLICIES = [
        (AUTO, "Automatic (no approval)"),
        (MANAGER, "Manager approval"),
        (MANAGER_OWNER, "Manager, then owner approval"),
    ]

    name = models.CharField(max_length=80, unique=True)
    code = models.SlugField(max_length=40, unique=True)
    description = models.CharField(max_length=250, blank=True)
    risk = models.CharField(max_length=8, choices=RISKS, default=LOW)
    approval_policy = models.CharField(max_length=14, choices=POLICIES, default=MANAGER)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="owned_entitlements")
    max_days = models.PositiveIntegerField(null=True, blank=True, help_text="Longest a request may be granted for.")
    departments = models.ManyToManyField("accounts.Department", blank=True, related_name="entitlements",
                                         help_text="Granted automatically to everyone in these departments.")
    job_roles = models.ManyToManyField("accounts.JobRole", blank=True, related_name="entitlements",
                                       help_text="Granted automatically to everyone in these job roles.")
    conflicts_with = models.ManyToManyField("self", blank=True, symmetrical=True,
                                            help_text="Separation of duties: cannot be held together.")
    group = models.OneToOneField(Group, null=True, blank=True, editable=False, on_delete=models.SET_NULL)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.group_id is None:
            g, _ = Group.objects.get_or_create(name=self.name)
            self.group = g
            super().save(update_fields=["group"])
        elif self.group.name != self.name:
            self.group.name = self.name
            self.group.save(update_fields=["name"])


class AccessRequest(models.Model):
    PENDING, APPROVED, REJECTED, CANCELLED = "pending", "approved", "rejected", "cancelled"
    STATUSES = [(PENDING, "Pending"), (APPROVED, "Approved"), (REJECTED, "Rejected"), (CANCELLED, "Cancelled")]

    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="access_requests")
    entitlement = models.ForeignKey(Entitlement, on_delete=models.CASCADE, related_name="requests")
    justification = models.TextField()
    duration_days = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.requester} -> {self.entitlement}"

    @property
    def current_step(self):
        return self.steps.filter(status=ApprovalStep.PENDING).order_by("order").first()


class ApprovalStep(models.Model):
    PENDING, APPROVED, REJECTED, SKIPPED = "pending", "approved", "rejected", "skipped"
    MANAGER, OWNER, ADMIN = "manager", "owner", "admin"
    KINDS = [(MANAGER, "Manager"), (OWNER, "Entitlement owner"), (ADMIN, "IAM administrator")]

    request = models.ForeignKey(AccessRequest, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=8, choices=KINDS)
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="+")
    status = models.CharField(max_length=10, default=PENDING)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    comment = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["order"]


class Grant(models.Model):
    POLICY, REQUEST, MANUAL = "policy", "request", "manual"
    SOURCES = [(POLICY, "Role/department policy"), (REQUEST, "Approved request"), (MANUAL, "Granted by admin")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="grants")
    entitlement = models.ForeignKey(Entitlement, on_delete=models.CASCADE, related_name="grants")
    source = models.CharField(max_length=8, choices=SOURCES)
    request = models.ForeignKey(AccessRequest, null=True, blank=True, on_delete=models.SET_NULL, related_name="grants")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    granted_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=60, blank=True)
    needs_review = models.BooleanField(default=False, help_text="Kept across a job move; confirm it is still needed.")

    class Meta:
        ordering = ["-granted_at"]

    @property
    def is_active(self):
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > timezone.now())
