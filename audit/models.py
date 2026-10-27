import hashlib
import json

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone


class Action:
    LOGIN_OK = "login.success"
    LOGIN_FAIL = "login.failed"
    LOGIN_LOCKED = "login.locked"
    LOGOUT = "logout"
    SESSION_REVOKED = "session.revoked"
    SESSION_EXPIRED = "session.expired"
    PASSWORD_CHANGED = "password.changed"
    PASSWORD_RESET = "password.reset"
    USER_JOINED = "lifecycle.joiner"
    USER_ACTIVATED = "lifecycle.activated"
    USER_MOVED = "lifecycle.mover"
    USER_SUSPENDED = "lifecycle.suspended"
    USER_REACTIVATED = "lifecycle.reactivated"
    DEPARTURE_SCHEDULED = "lifecycle.departure_scheduled"
    USER_LEFT = "lifecycle.leaver"
    ACCESS_GRANTED = "access.granted"
    ACCESS_REVOKED = "access.revoked"
    ACCESS_EXPIRED = "access.expired"
    REQUEST_CREATED = "request.created"
    REQUEST_APPROVED = "request.approved"
    REQUEST_REJECTED = "request.rejected"
    REQUEST_CANCELLED = "request.cancelled"
    LDAP_SYNC = "ldap.sync"
    LDAP_PROVISION = "ldap.provision"
    LDAP_DISABLE = "ldap.disable"
    CATALOG_CHANGED = "catalog.changed"


class AuditEvent(models.Model):
    """Append-only, hash-chained record of an identity event."""

    ts = models.DateTimeField(default=timezone.now, db_index=True)
    action = models.CharField(max_length=40, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    actor_label = models.CharField(max_length=150, blank=True)
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    target_label = models.CharField(max_length=150, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    success = models.BooleanField(default=True)
    details = models.JSONField(default=dict, blank=True)
    prev_hash = models.CharField(max_length=64, blank=True)
    hash = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.ts:%Y-%m-%d %H:%M} {self.action} {self.target_label}"

    def compute_hash(self):
        body = json.dumps(
            [self.prev_hash, self.ts.isoformat(), self.action, self.actor_label, self.target_label,
             self.ip, self.success, self.details],
            sort_keys=True, default=str,
        )
        return hashlib.sha256(body.encode()).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk:
            raise RuntimeError("Audit events are append-only")
        with transaction.atomic():
            last = AuditEvent.objects.select_for_update().order_by("-id").first()
            self.prev_hash = last.hash if last else ""
            self.hash = self.compute_hash()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Audit events cannot be deleted")


def verify_chain():
    """Return (ok, first_bad_id). Walks the whole chain oldest to newest."""
    prev = ""
    for ev in AuditEvent.objects.order_by("id").iterator():
        if ev.prev_hash != prev or ev.hash != ev.compute_hash():
            return False, ev.id
        prev = ev.hash
    return True, None
