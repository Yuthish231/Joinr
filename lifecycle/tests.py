from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.utils import timezone

from access import services as access
from access.models import AccessRequest, ApprovalStep, Grant
from accounts.models import User, UserSession
from audit.models import Action, AuditEvent
from core.testing import PASSWORD, IAMTestCase
from lifecycle import services
from lifecycle.models import LifecycleEvent

IST = ZoneInfo("Asia/Kolkata")


def held(user):
    return set(access.active_grants(user).values_list("entitlement__code", flat=True))


class JoinerTests(IAMTestCase):
    def test_department_and_role_decide_the_starting_access(self):
        u = services.provision_user(actor=self.admin, username="asha", email="asha@example.com",
                                    department=self.eng, job_role=self.dev)
        self.assertEqual(held(u), {"git", "deploy"})
        self.assertEqual(set(u.groups.values_list("name", flat=True)), {"Source Code", "Deploy"})
        self.assertEqual(u.status, User.ACTIVE)
        self.assertTrue(u.must_change_password)
        self.assertTrue(u.employee_id.startswith("JNR"))

    def test_temp_password_works_once_and_is_not_stored_in_clear(self):
        u = services.provision_user(actor=self.admin, username="asha", email="asha@example.com",
                                    department=self.eng)
        self.assertTrue(Client().login(username="asha", password=u.temp_password))
        self.assertNotIn(u.temp_password, u.password)

    def test_future_start_date_keeps_the_account_pending_without_access(self):
        start = timezone.localdate() + timedelta(days=10)
        u = services.provision_user(actor=self.admin, username="ravi", email="ravi@example.com",
                                    department=self.eng, job_role=self.dev, start_date=start)
        self.assertEqual(u.status, User.PENDING)
        self.assertFalse(u.is_active)
        self.assertEqual(held(u), set())
        self.assertFalse(Client().login(username="ravi", password=u.temp_password))

    def test_scheduler_activates_on_the_start_date_and_grants_access(self):
        start = date(2099, 3, 2)
        u = services.provision_user(actor=self.admin, username="ravi", email="ravi@example.com",
                                    department=self.eng, job_role=self.dev, start_date=start)
        res = services.run_due(datetime(2099, 3, 1, 12, tzinfo=IST))
        self.assertEqual(res["activated"], 0)
        res = services.run_due(datetime(2099, 3, 2, 9, tzinfo=IST))
        self.assertEqual(res["activated"], 1)
        u.refresh_from_db()
        self.assertEqual(u.status, User.ACTIVE)
        self.assertEqual(held(u), {"git", "deploy"})

    def test_duplicate_username_or_email_refused(self):
        self.make_user("asha")
        with self.assertRaises(services.LifecycleError):
            services.provision_user(username="ASHA", email="other@example.com")
        with self.assertRaises(services.LifecycleError):
            services.provision_user(username="new", email="asha@example.com")

    def test_role_from_another_department_refused(self):
        with self.assertRaises(services.LifecycleError):
            services.provision_user(username="x", email="x@example.com", department=self.fin, job_role=self.dev)


class MoverTests(IAMTestCase):
    def setUp(self):
        self.u = services.provision_user(actor=self.admin, username="asha", email="asha@example.com",
                                         department=self.eng, job_role=self.dev)
        # access she asked for herself, outside her role
        access.grant(self.u, self.reports, Grant.REQUEST, actor=self.admin)

    def test_move_swaps_role_based_access_and_keeps_requested_access_for_review(self):
        self.assertEqual(held(self.u), {"git", "deploy", "reports"})
        services.change_assignment(self.u, department=self.fin, job_role=self.accountant, manager=None,
                                   actor=self.admin)
        self.assertEqual(held(self.u), {"ledger", "reports"})
        self.assertEqual(set(self.u.groups.values_list("name", flat=True)), {"Ledger", "Reports"})
        self.assertTrue(Grant.objects.get(user=self.u, entitlement=self.reports, revoked_at__isnull=True).needs_review)
        old = Grant.objects.get(user=self.u, entitlement=self.git)
        self.assertEqual(old.revoke_reason, "mover")

    def test_move_is_recorded(self):
        services.change_assignment(self.u, department=self.fin, job_role=self.accountant, manager=None,
                                   actor=self.admin)
        ev = LifecycleEvent.objects.filter(user=self.u, kind="mover").get()
        self.assertEqual(ev.details["after"]["department"], "Finance")
        self.assertIn("Source Code", ev.details["revoked"])
        self.assertTrue(AuditEvent.objects.filter(action=Action.USER_MOVED, target_user=self.u).exists())

    def test_changing_only_the_manager_does_not_touch_access(self):
        mgr = self.make_user("boss")
        before = held(self.u)
        services.change_assignment(self.u, department=self.eng, job_role=self.dev, manager=mgr, actor=self.admin)
        self.assertEqual(held(self.u), before)
        self.assertFalse(Grant.objects.filter(user=self.u, needs_review=True).exists())

    def test_cannot_manage_yourself_or_use_foreign_role(self):
        with self.assertRaises(services.LifecycleError):
            services.change_assignment(self.u, department=self.eng, job_role=self.dev, manager=self.u)
        with self.assertRaises(services.LifecycleError):
            services.change_assignment(self.u, department=self.fin, job_role=self.dev, manager=None)

    def test_admin_can_move_through_the_screen(self):
        c = self.client_for(self.admin)
        c.post(f"/people/{self.u.pk}/move/", {"department": self.fin.pk, "job_role": self.accountant.pk})
        self.assertEqual(held(self.u), {"ledger", "reports"})


class LeaverTests(IAMTestCase):
    def setUp(self):
        self.boss = self.make_user("boss")
        self.u = services.provision_user(actor=self.admin, username="asha", email="asha@example.com",
                                         department=self.eng, job_role=self.dev, manager=self.boss)
        self.u.set_password(PASSWORD)
        self.u.must_change_password = False
        self.u.save()
        self.report = self.make_user("junior", manager=self.u)

    def test_deprovision_removes_every_form_of_access(self):
        # access that did not come through the catalog: added by hand
        stray = Group.objects.create(name="Handmade")
        self.u.groups.add(stray)
        self.u.user_permissions.add(Permission.objects.first())
        c1, c2 = self.client_for(self.u), self.client_for(self.u)
        access.grant(self.u, self.reports, Grant.REQUEST, actor=self.admin)

        services.deprovision_user(self.u, actor=self.admin, reason="resigned")
        self.u.refresh_from_db()

        self.assertEqual(self.u.status, User.TERMINATED)
        self.assertFalse(self.u.is_active)
        self.assertEqual(self.u.groups.count(), 0)
        self.assertEqual(self.u.user_permissions.count(), 0)
        self.assertEqual(held(self.u), set())
        self.assertFalse(Grant.objects.filter(user=self.u, revoked_at__isnull=True).exists())
        self.assertFalse(self.u.has_usable_password())
        self.assertEqual(UserSession.objects.filter(user=self.u, ended_at__isnull=True).count(), 0)
        self.assertEqual(c1.get("/").status_code, 302)
        self.assertEqual(c2.get("/").status_code, 302)
        self.assertFalse(Client().login(username="asha", password=PASSWORD))
        self.assertTrue(self.u.lifecycle_tasks.filter(title="Login disabled", done=True).exists())
        self.assertTrue(AuditEvent.objects.filter(action=Action.USER_LEFT, target_user=self.u).exists())

    def test_work_waiting_on_the_leaver_is_not_lost(self):
        self.u.refresh_from_db()
        req = access.create_request(self.report, self.reports, "Need the monthly reports for planning")
        step = req.steps.get()
        self.assertEqual(step.approver, self.u)
        pending_own = access.create_request(self.u, self.deploy_or_reports(), "Need it for the release work")
        services.deprovision_user(self.u, actor=self.admin)
        step.refresh_from_db()
        self.assertEqual((step.kind, step.approver), (ApprovalStep.ADMIN, None))
        pending_own.refresh_from_db()
        self.assertEqual(pending_own.status, AccessRequest.CANCELLED)
        self.report.refresh_from_db()
        self.assertEqual(self.report.manager, self.boss)  # reports go up one level

    def deploy_or_reports(self):
        return self.pay_start

    def test_deprovision_twice_is_harmless(self):
        services.deprovision_user(self.u, actor=self.admin)
        n = AuditEvent.objects.filter(action=Action.USER_LEFT).count()
        services.deprovision_user(self.u, actor=self.admin)
        self.assertEqual(AuditEvent.objects.filter(action=Action.USER_LEFT).count(), n)

    def test_access_ends_at_the_cutoff_on_the_last_working_day(self):
        lwd = date(2099, 6, 30)
        services.schedule_departure(self.u, lwd, actor=self.admin, reason="resigned")
        self.assertEqual(services.run_due(datetime(2099, 6, 30, 10, 0, tzinfo=IST))["departed"], 0)
        self.assertEqual(self.client_for(self.u).get("/").status_code, 200)
        self.assertEqual(services.run_due(datetime(2099, 6, 30, 19, 0, tzinfo=IST))["departed"], 1)
        self.u.refresh_from_db()
        self.assertEqual(self.u.status, User.TERMINATED)
        self.assertEqual(held(self.u), set())

    def test_scheduler_catches_up_after_downtime(self):
        services.schedule_departure(self.u, date(2099, 6, 30), actor=self.admin)
        self.assertEqual(services.run_due(datetime(2099, 7, 3, 3, 0, tzinfo=IST))["departed"], 1)

    def test_scheduling_a_past_date_deprovisions_immediately(self):
        services.schedule_departure(self.u, timezone.localdate() - timedelta(days=1), actor=self.admin)
        self.u.refresh_from_db()
        self.assertEqual(self.u.status, User.TERMINATED)

    def test_a_scheduled_departure_can_be_cancelled(self):
        services.schedule_departure(self.u, date(2099, 1, 1), actor=self.admin)
        services.schedule_departure(self.u, None, actor=self.admin)
        self.u.refresh_from_db()
        self.assertIsNone(self.u.last_working_day)
        self.assertEqual(services.run_due()["departed"], 0)

    def test_time_limited_access_expires_by_itself(self):
        g = access.grant(self.boss, self.reports, Grant.REQUEST, expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(services.run_due()["expired_grants"], 1)
        g.refresh_from_db()
        self.assertEqual(g.revoke_reason, "expired")
        self.assertFalse(self.boss.groups.filter(name="Reports").exists())


class AdminScreenTests(IAMTestCase):
    def test_non_admins_cannot_deprovision_anyone(self):
        victim = self.make_user("victim")
        c = self.client_for(self.make_user("nosy"))
        c.post(f"/people/{victim.pk}/terminate/")
        victim.refresh_from_db()
        self.assertEqual(victim.status, User.ACTIVE)

    def test_admin_deprovisions_through_the_screen(self):
        victim = self.make_user("victim")
        self.client_for(self.admin).post(f"/people/{victim.pk}/terminate/", {"reason": "test"})
        victim.refresh_from_db()
        self.assertEqual(victim.status, User.TERMINATED)

    def test_admin_cannot_terminate_themselves(self):
        self.client_for(self.admin).post(f"/people/{self.admin.pk}/terminate/")
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.status, User.ACTIVE)

    def test_people_can_only_open_records_they_are_entitled_to(self):
        a, b = self.make_user("a1"), self.make_user("b1")
        c = self.client_for(a)
        self.assertEqual(c.get(f"/people/{a.pk}/").status_code, 200)
        self.assertEqual(c.get(f"/people/{b.pk}/").status_code, 404)

    def test_managers_see_their_team_but_cannot_change_it(self):
        boss = self.make_user("boss")
        rep = self.make_user("rep", manager=boss)
        c = self.client_for(boss)
        self.assertEqual(c.get(f"/people/{rep.pk}/").status_code, 200)
        c.post(f"/people/{rep.pk}/terminate/")
        rep.refresh_from_db()
        self.assertEqual(rep.status, User.ACTIVE)
