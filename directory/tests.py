from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from ldap3 import MOCK_SYNC, MODIFY_REPLACE, Connection, Server

from access import services as access
from access.models import Grant
from audit.models import Action, AuditEvent
from core.testing import IAMTestCase
from directory import client, sync
from lifecycle import services as lifecycle

User = get_user_model()
BASE = "dc=joinr,dc=local"
ADMIN_DN = f"cn=admin,{BASE}"


@override_settings(LDAP_ENABLED=True, LDAP_WRITE_BACK=True)
class LDAPTestCase(IAMTestCase):
    """Runs against ldap3's in-memory directory: same protocol calls, no server needed."""

    def setUp(self):
        self.server = Server("mock")
        self.fail = False
        boot = Connection(self.server, user=ADMIN_DN, password="adminpw", client_strategy=MOCK_SYNC)
        boot.strategy.add_entry(ADMIN_DN, {"userPassword": "adminpw", "objectClass": "person"})

        def factory(user=None, password=None):
            if self.fail:
                raise ConnectionError("directory is down")
            c = Connection(self.server, user=user or ADMIN_DN, password=password if user else "adminpw",
                           client_strategy=MOCK_SYNC, raise_exceptions=True)
            c.bind()  # the mock strategy ignores auto_bind
            return c

        client.connection_factory = factory
        self.addCleanup(setattr, client, "connection_factory", None)
        self.boot = boot

    # -- helpers
    def add_person(self, uid, dept="ENG", title="Developer", pw="pw-123", ou="People", **extra):
        dn = f"uid={uid},ou={ou},{BASE}"
        attrs = {"uid": uid, "cn": uid.title(), "sn": "Kumar", "givenName": uid.title(), "mail": f"{uid}@example.com",
                 "userPassword": pw, "departmentNumber": dept, "title": title,
                 "objectClass": ["inetOrgPerson", "person", "top"], **extra}
        self.boot.strategy.add_entry(dn, attrs)
        return dn

    def conn(self):
        return client.connect()

    def members(self, code):
        c = self.conn()
        try:
            c.search(client.group_dn(code), "(objectClass=*)", search_scope="BASE", attributes=["member"])
            return set(c.response[0]["attributes"]["member"])
        finally:
            c.unbind()


class LDAPLoginTests(LDAPTestCase):
    def test_directory_password_signs_you_in_and_creates_the_identity(self):
        self.add_person("asha")
        self.assertTrue(Client().login(username="asha", password="pw-123"))
        u = User.objects.get(username="asha")
        self.assertEqual((u.source, u.department, u.job_role.title), (User.LDAP, self.eng, "Developer"))
        self.assertEqual(set(access.active_grants(u).values_list("entitlement__code", flat=True)), {"git", "deploy"})
        self.assertFalse(u.has_usable_password())  # the directory password is never copied here

    def test_wrong_password_and_unknown_user_are_refused(self):
        self.add_person("asha")
        self.assertFalse(Client().login(username="asha", password="nope"))
        self.assertFalse(Client().login(username="ghost", password="pw-123"))
        self.assertFalse(User.objects.filter(username="asha").exists())

    def test_disabled_directory_entries_cannot_sign_in(self):
        self.add_person("kiran", ou="Disabled")
        self.assertFalse(Client().login(username="kiran", password="pw-123"))

    def test_a_terminated_person_cannot_sign_in_even_with_a_valid_directory_password(self):
        self.add_person("asha")
        Client().login(username="asha", password="pw-123")
        lifecycle.deprovision_user(User.objects.get(username="asha"), actor=self.admin, write_back=False)
        self.assertFalse(Client().login(username="asha", password="pw-123"))

    def test_five_bad_attempts_lock_a_directory_account_too(self):
        self.add_person("asha")
        Client().login(username="asha", password="pw-123")
        c = Client()
        for _ in range(5):
            c.post("/login/", {"username": "asha", "password": "bad"})
        self.assertFalse(Client().login(username="asha", password="pw-123"))

    def test_directory_outage_fails_closed_but_local_admin_still_works(self):
        self.add_person("asha")
        self.fail = True
        self.assertFalse(Client().login(username="asha", password="pw-123"))
        self.assertTrue(Client().login(username="root", password="Str0ng-Test-Pass!"))


class LDAPSyncTests(LDAPTestCase):
    def test_sync_creates_moves_and_disables(self):
        self.add_person("asha")
        self.add_person("ravi", dept="FIN", title="Accountant")
        self.add_person("kiran", ou="Disabled")
        s = sync.sync_all(actor=self.admin)
        self.assertEqual((s["total"], s["created"]), (3, 2))  # the already-disabled entry is not imported
        self.assertFalse(User.objects.filter(username="kiran").exists())

        c = self.conn()
        c.modify(f"uid=asha,ou=People,{BASE}", {"departmentNumber": [(MODIFY_REPLACE, ["FIN"])],
                                                 "title": [(MODIFY_REPLACE, ["Accountant"])]})
        c.modify_dn(f"uid=ravi,ou=People,{BASE}", "uid=ravi", new_superior=f"ou=Disabled,{BASE}")
        c.unbind()

        s = sync.sync_all(actor=self.admin)
        self.assertEqual((s["moved"], s["disabled"]), (1, 1))
        asha, ravi = User.objects.get(username="asha"), User.objects.get(username="ravi")
        self.assertEqual(asha.department, self.fin)
        self.assertEqual(set(access.active_grants(asha).values_list("entitlement__code", flat=True)), {"ledger"})
        self.assertEqual(ravi.status, User.TERMINATED)
        self.assertEqual(access.active_grants(ravi).count(), 0)
        self.assertTrue(AuditEvent.objects.filter(action=Action.LDAP_SYNC).exists())

    def test_sync_is_repeatable(self):
        self.add_person("asha")
        sync.sync_all()
        s = sync.sync_all()
        self.assertEqual((s["created"], s["moved"], s["disabled"]), (0, 0, 0))
        self.assertEqual(User.objects.filter(username="asha").count(), 1)

    def test_status_page_and_manual_sync_for_admins_only(self):
        self.add_person("asha")
        self.assertEqual(self.client_for(self.make_user("plain")).get("/directory/").status_code, 302)
        c = self.client_for(self.admin)
        self.assertEqual(c.get("/directory/").status_code, 200)
        c.post("/directory/sync/")
        self.assertTrue(User.objects.filter(username="asha").exists())


class LDAPProvisioningTests(LDAPTestCase):
    def joiner(self, **kw):
        return lifecycle.provision_user(actor=self.admin, username="newbie", email="newbie@example.com",
                                        first_name="New", last_name="Bie", department=self.eng, job_role=self.dev, **kw)

    def test_a_joiner_gets_a_directory_entry_and_group_memberships(self):
        u = self.joiner()
        self.assertEqual(u.source, User.LDAP)
        entry = client.find_user("newbie")
        self.assertEqual((entry["department"], entry["title"]), ("ENG", "Developer"))
        self.assertEqual(u.ldap_dn, entry["dn"])
        self.assertIn(u.ldap_dn, self.members("git"))
        self.assertIn(u.ldap_dn, self.members("deploy"))
        self.assertTrue(Client().login(username="newbie", password=u.temp_password))

    def test_changing_password_updates_the_directory(self):
        u = self.joiner()
        c = self.client_for(u, password=u.temp_password)
        new = "An0ther-Long-Pass!"
        c.post("/password/change/", {"old_password": u.temp_password, "new_password1": new, "new_password2": new})
        self.assertIsNotNone(client.authenticate("newbie", new))
        self.assertIsNone(client.authenticate("newbie", u.temp_password))

    def test_a_mover_is_updated_in_the_directory(self):
        u = self.joiner()
        lifecycle.change_assignment(u, department=self.fin, job_role=self.accountant, manager=None, actor=self.admin)
        entry = client.find_user("newbie")
        self.assertEqual((entry["department"], entry["title"]), ("FIN", "Accountant"))
        self.assertNotIn(u.ldap_dn, self.members("git"))
        self.assertIn(u.ldap_dn, self.members("ledger"))

    def test_a_leaver_is_scrambled_unlisted_and_moved_to_the_disabled_ou(self):
        u = self.joiner()
        old_pw, dn = u.temp_password, u.ldap_dn
        lifecycle.deprovision_user(u, actor=self.admin, reason="resigned")
        entry = client.find_user("newbie")
        self.assertTrue(entry["disabled"])
        self.assertIn("ou=Disabled", entry["dn"])
        self.assertIsNone(client.authenticate("newbie", old_pw))
        self.assertNotIn(dn, self.members("git"))
        self.assertTrue(AuditEvent.objects.filter(action=Action.LDAP_DISABLE).exists())

    def test_catalog_grants_and_revocations_follow_into_ldap_groups(self):
        u = self.joiner()
        g = access.grant(u, self.reports, Grant.REQUEST, actor=self.admin)
        self.assertIn(u.ldap_dn, self.members("reports"))
        access.revoke(g, "test", actor=self.admin)
        self.assertNotIn(u.ldap_dn, self.members("reports"))

    def test_a_directory_outage_never_blocks_a_leaver(self):
        u = self.joiner()
        self.fail = True
        lifecycle.deprovision_user(u, actor=self.admin, reason="resigned")
        u.refresh_from_db()
        self.assertEqual(u.status, User.TERMINATED)
        self.assertEqual(access.active_grants(u).count(), 0)
        self.assertTrue(AuditEvent.objects.filter(action=Action.LDAP_PROVISION, success=False).exists())

    @override_settings(LDAP_WRITE_BACK=False)
    def test_read_only_mode_never_writes_to_the_directory(self):
        u = lifecycle.provision_user(actor=self.admin, username="ro1", email="ro1@example.com", department=self.eng)
        self.assertIsNone(client.find_user("ro1"))
        self.assertEqual(u.source, User.LOCAL)
