from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.utils import timezone

from . import client, sync


class LDAPBackend(ModelBackend):
    """Authenticate by binding to the directory as the user, then mirror them locally."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not settings.LDAP_ENABLED or not username or not password:
            return None
        User = get_user_model()
        existing = User.objects.filter(username__iexact=username).first()
        if existing is not None and existing.locked_until and existing.locked_until > timezone.now():
            return None
        entry = client.authenticate(username, password)
        if entry is None:
            return None
        user = sync.upsert_user(entry, via="login")
        return user if user and self.user_can_authenticate(user) else None
