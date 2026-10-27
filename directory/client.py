"""Thin LDAP client (ldap3). All directory I/O goes through here."""
import logging
import secrets

from django.conf import settings
from ldap3 import MODIFY_ADD, MODIFY_DELETE, MODIFY_REPLACE, SUBTREE, Connection, Server
from ldap3.core.exceptions import (LDAPAttributeOrValueExistsResult, LDAPException, LDAPNoSuchAttributeResult,
                                   LDAPNoSuchObjectResult, LDAPOperationsErrorResult)
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import escape_rdn

log = logging.getLogger(__name__)

# Tests replace this with a factory returning an in-memory (MOCK_SYNC) connection.
connection_factory = None

PERSON_ATTRS = ["uid", "cn", "sn", "givenName", "mail", "departmentNumber", "title", "employeeNumber",
                "telephoneNumber"]


class DirectoryError(Exception):
    pass


def user_base():
    return f"{settings.LDAP_USER_OU},{settings.LDAP_BASE_DN}"


def group_base():
    return f"{settings.LDAP_GROUP_OU},{settings.LDAP_BASE_DN}"


def disabled_base():
    return f"{settings.LDAP_DISABLED_OU},{settings.LDAP_BASE_DN}"


def placeholder_member():
    return f"cn=_placeholder,{settings.LDAP_BASE_DN}"


def user_dn(username):
    return f"uid={escape_rdn(username)},{user_base()}"


def group_dn(code):
    return f"cn={escape_rdn(code)},{group_base()}"


def connect(user=None, password=None):
    """Open a bound connection. With no arguments, binds as the service account."""
    if connection_factory is not None:
        return connection_factory(user, password)
    server = Server(settings.LDAP_SERVER_URI, connect_timeout=settings.LDAP_TIMEOUT)
    return Connection(server, user=user or settings.LDAP_BIND_DN,
                      password=password if user else settings.LDAP_BIND_PASSWORD,
                      auto_bind=True, receive_timeout=settings.LDAP_TIMEOUT, raise_exceptions=True)


def check():
    """(ok, message) for the status page."""
    try:
        conn = connect()
        conn.search(settings.LDAP_BASE_DN, "(objectClass=*)", search_scope="BASE")
        conn.unbind()
        return True, f"Connected to {settings.LDAP_SERVER_URI}"
    except Exception as exc:  # noqa: BLE001 - shown to the admin as text
        return False, f"{exc.__class__.__name__}: {exc}"


def _entry_to_dict(entry):
    attrs = entry["attributes"] if isinstance(entry, dict) else entry.entry_attributes_as_dict

    def one(name):
        v = attrs.get(name)
        if isinstance(v, (list, tuple)):
            v = v[0] if v else ""
        return (v or "") if not isinstance(v, bytes) else v.decode()

    dn = entry["dn"] if isinstance(entry, dict) else entry.entry_dn
    return {
        "dn": dn, "uid": one("uid"), "cn": one("cn"), "first_name": one("givenName"), "last_name": one("sn"),
        "mail": one("mail"), "department": one("departmentNumber"), "title": one("title"),
        "employee_id": one("employeeNumber"), "phone": one("telephoneNumber"),
        "disabled": disabled_base().lower() in dn.lower(),
    }


def find_user(username, conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        conn.search(settings.LDAP_BASE_DN, f"(&(objectClass=inetOrgPerson)(uid={escape_filter_chars(username)}))",
                    search_scope=SUBTREE, attributes=PERSON_ATTRS)
        return _entry_to_dict(conn.response[0]) if conn.response and conn.response[0].get("dn") else None
    finally:
        if own:
            conn.unbind()


def authenticate(username, password):
    """Return the directory entry on a good bind, else None. Disabled entries never authenticate."""
    if not username or not password:
        return None
    try:
        entry = find_user(username)
        if entry is None or entry["disabled"]:
            return None
        bound = connect(user=entry["dn"], password=password)
        bound.unbind()
        return entry
    except LDAPException as exc:
        log.info("LDAP bind refused for %s: %s", username, exc)
        return None
    except Exception:  # directory down: fail closed, local accounts still work
        log.exception("LDAP unavailable during authenticate")
        return None


def fetch_users():
    conn = connect()
    try:
        conn.search(settings.LDAP_BASE_DN, "(objectClass=inetOrgPerson)", search_scope=SUBTREE,
                    attributes=PERSON_ATTRS)
        return [_entry_to_dict(e) for e in conn.response if e.get("dn")]
    finally:
        conn.unbind()


def _exists(conn, dn):
    try:
        return bool(conn.search(dn, "(objectClass=*)", search_scope="BASE"))
    except LDAPNoSuchObjectResult:
        return False


def _ensure_ou(conn, dn):
    if not _exists(conn, dn):
        conn.add(dn, "organizationalUnit")


def ensure_structure(conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        for dn in (user_base(), group_base(), disabled_base()):
            _ensure_ou(conn, dn)
    finally:
        if own:
            conn.unbind()


def ensure_group(code, description="", conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        dn = group_dn(code)
        _ensure_ou(conn, group_base())
        if not _exists(conn, dn):
            conn.add(dn, "groupOfNames", {"cn": code, "description": description or code,
                                          "member": [placeholder_member()]})
        return dn
    finally:
        if own:
            conn.unbind()


def create_user(user, password, conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        dn = user_dn(user.username)
        attrs = {
            "uid": user.username, "cn": user.display_name, "sn": user.last_name or user.username,
            "givenName": user.first_name or user.username, "mail": user.email, "userPassword": password,
        }
        if user.department_id:
            attrs["departmentNumber"] = user.department.code
        if user.job_role_id:
            attrs["title"] = user.job_role.title
        if user.employee_id:
            attrs["employeeNumber"] = user.employee_id
        conn.add(dn, ["inetOrgPerson", "organizationalPerson", "person", "top"], attrs)
        return dn
    finally:
        if own:
            conn.unbind()


def update_user(user, conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        dn = user.ldap_dn or user_dn(user.username)
        changes = {
            "mail": [(MODIFY_REPLACE, [user.email])],
            "departmentNumber": [(MODIFY_REPLACE, [user.department.code if user.department_id else ""])],
            "title": [(MODIFY_REPLACE, [user.job_role.title if user.job_role_id else ""])],
        }
        conn.modify(dn, {k: v for k, v in changes.items() if v[0][1] != [""]})
    finally:
        if own:
            conn.unbind()


def set_password(user, password):
    conn = connect()
    try:
        conn.modify(user.ldap_dn or user_dn(user.username), {"userPassword": [(MODIFY_REPLACE, [password])]})
    finally:
        conn.unbind()


def modify_member(code, dn, add=True):
    conn = connect()
    try:
        ensure_group(code, conn=conn)
        try:
            conn.modify(group_dn(code), {"member": [(MODIFY_ADD if add else MODIFY_DELETE, [dn])]})
        except (LDAPNoSuchAttributeResult, LDAPOperationsErrorResult, LDAPAttributeOrValueExistsResult):
            pass  # already a member / already not a member: the directory is where we want it
    finally:
        conn.unbind()


def disable_user(user):
    """Scramble the credential, drop group memberships, move the entry to the Disabled OU."""
    conn = connect()
    try:
        dn = user.ldap_dn or user_dn(user.username)
        _ensure_ou(conn, disabled_base())
        conn.modify(dn, {"userPassword": [(MODIFY_REPLACE, [secrets.token_urlsafe(24)])]})
        try:
            conn.search(group_base(), f"(member={escape_filter_chars(dn)})", search_scope=SUBTREE)
            memberships = [e for e in conn.response if e.get("dn")]
        except LDAPNoSuchObjectResult:
            memberships = []
        for ent in memberships:
            conn.modify(ent["dn"], {"member": [(MODIFY_DELETE, [dn])]})
        rdn = dn.split(",", 1)[0]
        conn.modify_dn(dn, rdn, new_superior=disabled_base())
        return f"{rdn},{disabled_base()}"
    finally:
        conn.unbind()
