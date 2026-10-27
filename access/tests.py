from datetime import timedelta

from django.utils import timezone

from access import services
from access.models import AccessRequest, ApprovalStep, Grant
from audit.models import Action, AuditEvent
from core.testing import IAMTestCase
from lifecycle import services as lifecycle


class RequestWorkflowTests(IAMTestCase):
    def setUp(self):
        self.boss = self.make_user("boss")
        self.owner = self.make_user("owner")
        self.prod_db.owner = self.owner
        self.prod_db.save()
        self.emp = self.make_user("emp", manager=self.boss)

    def held(self, u):
        return set(services.active_grants(u).values_list("entitlement__code", flat=True))

    def test_low_risk_automatic_access_is_granted_at_once(self):
        req = services.create_request(self.emp, self.git, "Need to read the repositories")
        self.assertEqual(req.status, AccessRequest.APPROVED)
        self.assertIn("git", self.held(self.emp))
        self.assertTrue(self.emp.groups.filter(name="Source Code").exists())

    def test_manager_approval_grants_with_an_expiry(self):
        req = services.create_request(self.emp, self.reports, "Month-end reporting work", days=10)
        self.assertEqual(req.status, AccessRequest.PENDING)
        self.assertEqual(self.held(self.emp), set())
        services.decide(req.steps.get(), self.boss, True, "ok")
        req.refresh_from_db()
        self.assertEqual(req.status, AccessRequest.APPROVED)
        g = Grant.objects.get(user=self.emp, entitlement=self.reports)
        self.assertEqual(g.source, Grant.REQUEST)
        self.assertAlmostEqual((g.expires_at - timezone.now()).total_seconds(), 10 * 86400, delta=60)

    def test_two_step_approval_runs_in_order(self):
        req = services.create_request(self.emp, self.prod_db, "Investigating the billing incident", days=90)
        self.assertEqual(req.duration_days, 30)  # capped by the entitlement
        first, second = req.steps.order_by("order")
        self.assertEqual((first.kind, second.kind), (ApprovalStep.MANAGER, ApprovalStep.OWNER))
        self.assertFalse(services.can_decide(second, self.owner))  # not yet
        services.decide(first, self.boss, True)
        req.refresh_from_db()
        self.assertEqual(req.status, AccessRequest.PENDING)
        self.assertTrue(services.can_decide(second, self.owner))
        services.decide(second, self.owner, True)
        req.refresh_from_db()
        self.assertEqual(req.status, AccessRequest.APPROVED)

    def test_rejection_ends_the_request_and_grants_nothing(self):
        req = services.create_request(self.emp, self.prod_db, "Investigating the billing incident")
        services.decide(req.steps.order_by("order").first(), self.boss, False, "not now")
        req.refresh_from_db()
        self.assertEqual(req.status, AccessRequest.REJECTED)
        self.assertEqual(self.held(self.emp), set())
        self.assertFalse(req.steps.filter(status=ApprovalStep.PENDING).exists())

    def test_nobody_approves_their_own_access_not_even_an_admin(self):
        req = services.create_request(self.admin, self.reports, "I would like this please")
        step = req.steps.get()
        self.assertEqual(step.kind, ApprovalStep.ADMIN)  # no manager, so an admin decides
        with self.assertRaises(services.AccessError):
            services.decide(step, self.admin, True)

    def test_the_wrong_person_cannot_decide(self):
        req = services.create_request(self.emp, self.reports, "Month-end reporting work")
        with self.assertRaises(services.AccessError):
            services.decide(req.steps.get(), self.make_user("stranger"), True)

    def test_without_a_manager_an_admin_decides(self):
        loner = self.make_user("loner")
        req = services.create_request(loner, self.reports, "Month-end reporting work")
        step = req.steps.get()
        self.assertEqual(step.kind, ApprovalStep.ADMIN)
        services.decide(step, self.admin, True)
        self.assertIn("reports", self.held(loner))

    def test_separation_of_duties_blocks_conflicting_access(self):
        services.grant(self.emp, self.pay_approve, Grant.MANUAL, actor=self.admin)
        with self.assertRaisesMessage(services.AccessError, "Separation of duties"):
            services.create_request(self.emp, self.pay_start, "Need to start payments for a client")

    def test_separation_of_duties_is_rechecked_at_approval_time(self):
        req = services.create_request(self.emp, self.pay_start, "Need to start payments for a client")
        services.grant(self.emp, self.pay_approve, Grant.MANUAL, actor=self.admin)  # arrives meanwhile
        services.decide(req.steps.get(), self.boss, True)
        req.refresh_from_db()
        self.assertEqual(req.status, AccessRequest.REJECTED)
        self.assertNotIn("payinit", self.held(self.emp))

    def test_no_duplicate_or_repeat_requests(self):
        services.create_request(self.emp, self.reports, "Month-end reporting work")
        with self.assertRaises(services.AccessError):
            services.create_request(self.emp, self.reports, "Asking a second time for it")
        services.grant(self.emp, self.git, Grant.MANUAL)
        with self.assertRaises(services.AccessError):
            services.create_request(self.emp, self.git, "I already have this one")

    def test_inactive_accounts_cannot_request(self):
        pend = self.make_user("pend", status="pending")
        with self.assertRaises(services.AccessError):
            services.create_request(pend, self.git, "Planning ahead of my start date")

    def test_every_step_is_audited(self):
        req = services.create_request(self.emp, self.reports, "Month-end reporting work")
        services.decide(req.steps.get(), self.boss, True)
        actions = set(AuditEvent.objects.values_list("action", flat=True))
        self.assertTrue({Action.REQUEST_CREATED, Action.REQUEST_APPROVED, Action.ACCESS_GRANTED} <= actions)


class ScreenTests(IAMTestCase):
    def test_approver_sees_and_decides_from_the_inbox(self):
        boss = self.make_user("boss")
        emp = self.make_user("emp", manager=boss)
        req = services.create_request(emp, self.reports, "Month-end reporting work")
        c = self.client_for(boss)
        self.assertIn("Month-end", c.get(f"/requests/{req.pk}/").content.decode())
        self.assertEqual(len(services.pending_for(boss)), 1)
        step = req.steps.get()
        c.post(f"/steps/{step.pk}/decide/", {"decision": "approve", "comment": "fine"})
        req.refresh_from_db()
        self.assertEqual(req.status, AccessRequest.APPROVED)

    def test_strangers_cannot_open_a_request(self):
        emp = self.make_user("emp")
        req = services.create_request(emp, self.reports, "Month-end reporting work")
        self.assertEqual(self.client_for(self.make_user("nosy")).get(f"/requests/{req.pk}/").status_code, 404)

    def test_requester_can_cancel(self):
        emp = self.make_user("emp", manager=self.make_user("boss"))
        req = services.create_request(emp, self.reports, "Month-end reporting work")
        self.client_for(emp).post(f"/requests/{req.pk}/cancel/")
        req.refresh_from_db()
        self.assertEqual(req.status, AccessRequest.CANCELLED)

    def test_requesting_through_the_form(self):
        emp = self.make_user("emp")
        r = self.client_for(emp).post("/access/request/", {"entitlement": self.git.pk,
                                                          "justification": "Need to read the repos for onboarding"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(services.active_grants(emp).filter(entitlement=self.git).exists())


class AuditTests(IAMTestCase):
    def test_chain_verifies_and_detects_tampering(self):
        from audit.models import AuditEvent, verify_chain
        self.make_user("x")
        lifecycle.provision_user(actor=self.admin, username="y1", email="y1@example.com", department=self.eng)
        self.assertTrue(verify_chain()[0])
        ev = AuditEvent.objects.order_by("id")[1]
        AuditEvent.objects.filter(pk=ev.pk).update(actor_label="someone-else")  # bypasses save()
        ok, bad = verify_chain()
        self.assertFalse(ok)
        self.assertEqual(bad, ev.pk)

    def test_events_cannot_be_deleted_or_edited(self):
        from audit import service
        ev = service.log("test.event")
        with self.assertRaises(RuntimeError):
            ev.delete()
        with self.assertRaises(RuntimeError):
            ev.save()

    def test_only_auditors_and_admins_can_read_the_log(self):
        self.assertEqual(self.client_for(self.make_user("plain")).get("/audit/").status_code, 302)
        self.assertEqual(self.client_for(self.admin).get("/audit/").status_code, 200)
