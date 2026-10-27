from django.conf import settings
from django.db import models
from django.utils import timezone


class LifecycleEvent(models.Model):
    JOINER, ACTIVATED, MOVER, SUSPENDED, REACTIVATED, SCHEDULED, LEAVER = (
        "joiner", "activated", "mover", "suspended", "reactivated", "departure_scheduled", "leaver")
    KINDS = [
        (JOINER, "Joined"), (ACTIVATED, "Activated"), (MOVER, "Moved"), (SUSPENDED, "Suspended"),
        (REACTIVATED, "Reactivated"), (SCHEDULED, "Departure scheduled"), (LEAVER, "Left"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lifecycle_events")
    kind = models.CharField(max_length=24, choices=KINDS, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="+")
    ts = models.DateTimeField(default=timezone.now, db_index=True)
    summary = models.CharField(max_length=250)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-ts", "-id"]


class LifecycleTask(models.Model):
    """Human follow-ups for a joiner or leaver. System steps are ticked automatically."""

    JOINER, LEAVER = "joiner", "leaver"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lifecycle_tasks")
    phase = models.CharField(max_length=8)
    title = models.CharField(max_length=120)
    automatic = models.BooleanField(default=False)
    done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="+")

    class Meta:
        ordering = ["id"]
