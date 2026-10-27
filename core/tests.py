from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from access.models import AccessRequest, Entitlement
from accounts.models import Department, JobRole
from core.testing import FAST_HASH

User = get_user_model()


@FAST_HASH
class SeededSiteSmokeTests(TestCase):
    """Seed the full demo organisation and open every screen as different kinds of user."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", "--no-credentials", verbosity=0)

    def visit(self, username, paths):
        c = Client()
        c.force_login(User.objects.get(username=username))
        return {p: c.get(p).status_code for p in paths}

    def test_every_screen_renders_for_the_iam_admin(self):
        paths = ["/", "/people/", "/people/?status=terminated", "/people/new/", "/lifecycle/", "/catalog/",
                 "/catalog/new/", "/access/", "/approvals/", "/requests/", "/review/", "/organisation/",
                 "/sessions/", "/audit/", "/audit/export/", "/directory/", "/account/", "/password/change/"]
        paths += [f"/people/{u.pk}/" for u in User.objects.all()]
        paths += [f"/catalog/{e.pk}/" for e in Entitlement.objects.all()]
        paths += [f"/requests/{r.pk}/" for r in AccessRequest.objects.all()]
        paths += [f"/organisation/department/{Department.objects.first().pk}/",
                  f"/organisation/role/{JobRole.objects.first().pk}/"]
        bad = {p: s for p, s in self.visit("admin", paths).items() if s != 200}
        self.assertEqual(bad, {})

    def test_roles_see_only_what_they_should(self):
        admin_only = ["/people/", "/audit/", "/directory/", "/organisation/", "/sessions/", "/requests/"]
        employee = self.visit("priya.sharma", ["/", "/access/", "/catalog/", "/approvals/", "/account/"] + admin_only)
        self.assertEqual([employee[p] for p in ["/", "/access/", "/catalog/", "/approvals/", "/account/"]], [200] * 5)
        self.assertTrue(all(employee[p] == 302 for p in admin_only))  # bounced to the dashboard

        manager = self.visit("rajesh.iyer", ["/team/", "/approvals/", "/audit/"])
        self.assertEqual((manager["/team/"], manager["/approvals/"], manager["/audit/"]), (200, 200, 302))

        lead = self.visit("deepa.krishnan", ["/people/", "/audit/", "/directory/", "/sessions/"])
        self.assertEqual(set(lead.values()), {200})  # IAM Admin + Auditor through the catalog, not superuser

    def test_demo_organisation_shape(self):
        by = {s: User.objects.filter(status=s).count() for s, _ in User.STATUSES}
        self.assertEqual((by["pending"], by["suspended"], by["terminated"]), (2, 1, 2))
        self.assertTrue(AccessRequest.objects.filter(status="pending").exists())
        self.assertTrue(AccessRequest.objects.filter(status="rejected").exists())
        names = set(User.objects.values_list("first_name", flat=True))
        self.assertTrue({"Priya", "Rohan", "Ananya"} <= names)
