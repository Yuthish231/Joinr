from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class Department(models.Model):
    name = models.CharField(max_length=80, unique=True)
    code = models.CharField(max_length=20, unique=True, help_text="Also used as the LDAP departmentNumber.")
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class JobRole(models.Model):
    title = models.CharField(max_length=80)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="roles")
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["title"]
        unique_together = [("title", "department")]

    def __str__(self):
        return self.title


class User(AbstractUser):
    PENDING, ACTIVE, SUSPENDED, TERMINATED = "pending", "active", "suspended", "terminated"
    STATUSES = [
        (PENDING, "Pending start"),
        (ACTIVE, "Active"),
        (SUSPENDED, "Suspended"),
        (TERMINATED, "Terminated"),
    ]
    LOCAL, LDAP = "local", "ldap"

    email = models.EmailField(unique=True)
    employee_id = models.CharField(max_length=20, unique=True, null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="members")
    job_role = models.ForeignKey(JobRole, null=True, blank=True, on_delete=models.SET_NULL, related_name="members")
    manager = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reports")
    status = models.CharField(max_length=12, choices=STATUSES, default=ACTIVE, db_index=True)
    start_date = models.DateField(null=True, blank=True)
    last_working_day = models.DateField(null=True, blank=True)
    terminated_at = models.DateTimeField(null=True, blank=True)
    must_change_password = models.BooleanField(default=False)
    failed_logins = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=10, default=LOCAL)
    ldap_dn = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["first_name", "last_name", "username"]

    def save(self, *args, **kwargs):
        # The login gate (Django's is_active) always mirrors the lifecycle status.
        self.is_active = self.status == self.ACTIVE
        fields = kwargs.get("update_fields")
        if fields is not None and "status" in fields and "is_active" not in fields:
            kwargs["update_fields"] = list(fields) + ["is_active"]
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def is_locked(self):
        return bool(self.locked_until and self.locked_until > timezone.now())

    def __str__(self):
        return self.display_name


class UserSession(models.Model):
    """One row per login. Mirrors a Django session so it can be listed and revoked."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sessions_log")
    session_key = models.CharField(max_length=40, unique=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_active(self):
        return self.ended_at is None
