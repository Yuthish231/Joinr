"""Put a few people straight into the directory, as if HR or IT had created them there.
Use the Directory page's "Sync now" (or `manage.py sync_ldap`) to import them."""
from django.core.management.base import BaseCommand
from django.conf import settings

from directory import client

PEOPLE = [
    ("Imran", "Sheikh", "SEC", "Security Analyst", "imran.sheikh"),
    ("Pallavi", "Hegde", "ENG", "Software Engineer", "pallavi.hegde"),
    ("Gautam", "Bose", "FIN", "Accountant", "gautam.bose"),
]


class Command(BaseCommand):
    help = "Create example people directly in LDAP (needs LDAP_ENABLED)."

    def handle(self, *args, **opts):
        if not settings.LDAP_ENABLED:
            self.stderr.write("LDAP_ENABLED is off.")
            return
        conn = client.connect()
        client.ensure_structure(conn)
        from ldap3.core.exceptions import LDAPEntryAlreadyExistsResult
        for first, last, dept, title, uid in PEOPLE:
            try:
                conn.add(client.user_dn(uid), ["inetOrgPerson", "organizationalPerson", "person", "top"], {
                    "uid": uid, "cn": f"{first} {last}", "sn": last, "givenName": first, "mail": f"{uid}@joinr.local",
                    "userPassword": "Directory-Demo-1", "departmentNumber": dept, "title": title})
                self.stdout.write(f"added {uid}")
            except LDAPEntryAlreadyExistsResult:
                self.stdout.write(f"{uid} already there")
        conn.unbind()
        self.stdout.write("Directory people use password 'Directory-Demo-1' until they change it.")
