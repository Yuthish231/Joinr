"""Write-back to the directory. Best effort: a down directory never blocks a lifecycle action."""
import logging

from django.conf import settings

from audit import service as audit
from audit.models import Action

from . import client

log = logging.getLogger(__name__)


def enabled():
    return bool(settings.LDAP_ENABLED and settings.LDAP_WRITE_BACK)


def _safe(label, user, fn):
    if not enabled():
        return None
    try:
        result = fn()
        audit.log(Action.LDAP_PROVISION, target=user, operation=label)
        return result
    except Exception as exc:  # noqa: BLE001
        log.warning("LDAP %s failed for %s: %s", label, user.username, exc)
        audit.log(Action.LDAP_PROVISION, target=user, success=False, operation=label, error=str(exc)[:200])
        return None


def create_entry(user, password):
    def go():
        client.ensure_structure()
        user.ldap_dn = client.create_user(user, password)
        user.save(update_fields=["ldap_dn"])
        return user.ldap_dn
    return _safe("create", user, go)


def update_entry(user):
    return _safe("update", user, lambda: client.update_user(user))


def set_password(user, password):
    return _safe("set_password", user, lambda: client.set_password(user, password))


def add_to_group(user, entitlement):
    if user.source != user.LDAP:
        return None
    return _safe(f"group_add:{entitlement.code}", user,
                 lambda: client.modify_member(entitlement.code, user.ldap_dn or client.user_dn(user.username), True))


def remove_from_group(user, entitlement):
    if user.source != user.LDAP:
        return None
    return _safe(f"group_remove:{entitlement.code}", user,
                 lambda: client.modify_member(entitlement.code, user.ldap_dn or client.user_dn(user.username), False))


def disable_entry(user):
    def go():
        new_dn = client.disable_user(user)
        user.ldap_dn = new_dn
        user.save(update_fields=["ldap_dn"])
        audit.log(Action.LDAP_DISABLE, target=user, dn=new_dn)
    return _safe("disable", user, go) if user.source == user.LDAP else None
