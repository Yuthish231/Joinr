from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.utils import timezone


class LockoutModelBackend(ModelBackend):
    """Local password login that refuses a locked account before checking the password."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            return None
        User = get_user_model()
        user = User.objects.filter(username__iexact=username).first()
        if user is not None and user.locked_until and user.locked_until > timezone.now():
            return None  # locked: do not even test the password
        if user is not None and user.source == User.LDAP and not user.has_usable_password():
            return None  # directory accounts authenticate against LDAP only
        return super().authenticate(request, username=username, password=password, **kwargs)
