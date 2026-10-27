from datetime import timedelta

from django.contrib.sessions.models import Session
from django.test import Client, override_settings
from django.utils import timezone

from accounts.models import User, UserSession
from audit.models import Action, AuditEvent
from core.testing import PASSWORD, IAMTestCase
from lifecycle import services


class LoginAndLockoutTests(IAMTestCase):
    def test_login_creates_tracked_session_and_audit(self):
        u = self.make_user("asha")
        self.client_for(u)
        self.assertEqual(UserSession.objects.filter(user=u, ended_at__isnull=True).count(), 1)
        self.assertTrue(AuditEvent.objects.filter(action=Action.LOGIN_OK, target_user=u).exists())

    def test_lockout_after_repeated_failures_blocks_even_the_right_password(self):
        u = self.make_user("ravi")
        c = Client()
        for _ in range(5):
            c.post("/login/", {"username": "ravi", "password": "wrong"})
        u.refresh_from_db()
        self.assertTrue(u.is_locked)
        r = c.post("/login/", {"username": "ravi", "password": PASSWORD})
        self.assertEqual(r.status_code, 200)  # form re-rendered, not logged in
        self.assertNotIn("_auth_user_id", c.session)
        self.assertTrue(AuditEvent.objects.filter(action=Action.LOGIN_LOCKED, target_user=u).exists())

    def test_lock_expires(self):
        u = self.make_user("meera")
        u.locked_until = timezone.now() - timedelta(minutes=1)
        u.save()
        self.assertTrue(Client().login(username="meera", password=PASSWORD))

    def test_pending_and_terminated_accounts_cannot_sign_in(self):
        self.make_user("pend", status="pending")
        self.make_user("gone", status="terminated")
        self.assertFalse(Client().login(username="pend", password=PASSWORD))
        self.assertFalse(Client().login(username="gone", password=PASSWORD))


class LogoutTests(IAMTestCase):
    def test_logout_must_be_post(self):
        c = self.client_for(self.make_user("kiran"))
        self.assertEqual(c.get("/logout/").status_code, 405)
        self.assertEqual(c.get("/").status_code, 200)  # still signed in after a GET

    def test_logout_destroys_the_server_side_session(self):
        u = self.make_user("kiran")
        c = self.client_for(u)
        key = c.session.session_key
        r = c.post("/logout/")
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        us = UserSession.objects.get(session_key=key)
        self.assertEqual(us.end_reason, "logout")
        self.assertTrue(AuditEvent.objects.filter(action=Action.LOGOUT, target_user=u).exists())
        self.assertEqual(c.get("/").status_code, 302)  # bounced to login

    def test_replaying_the_old_cookie_after_logout_fails(self):
        c = self.client_for(self.make_user("kiran"))
        old = c.cookies["sessionid"].value
        c.post("/logout/")
        replay = Client()
        replay.cookies["sessionid"] = old
        self.assertEqual(replay.get("/").status_code, 302)

    def test_signed_in_pages_are_not_cacheable(self):
        c = self.client_for(self.make_user("kiran"))
        self.assertIn("no-store", c.get("/")["Cache-Control"])


class SessionRuleTests(IAMTestCase):
    @override_settings(MAX_CONCURRENT_SESSIONS=3)
    def test_concurrent_session_cap_evicts_the_oldest(self):
        u = self.make_user("dev1")
        clients = [self.client_for(u) for _ in range(4)]
        self.assertEqual(UserSession.objects.filter(user=u, ended_at__isnull=True).count(), 3)
        self.assertEqual(clients[0].get("/").status_code, 302)  # oldest was signed out
        self.assertEqual(clients[3].get("/").status_code, 200)

    @override_settings(ABSOLUTE_SESSION_SECONDS=3600)
    def test_absolute_lifetime_ends_a_busy_session(self):
        u = self.make_user("dev1")
        c = self.client_for(u)
        UserSession.objects.filter(user=u).update(created_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(c.get("/").status_code, 302)
        self.assertEqual(UserSession.objects.get(user=u).end_reason, "expired")

    def test_user_can_end_one_of_their_own_sessions(self):
        u = self.make_user("dev1")
        a, b = self.client_for(u), self.client_for(u)
        other = UserSession.objects.exclude(session_key=b.session.session_key).get(user=u)
        self.assertEqual(b.post(f"/account/sessions/{other.pk}/end/").status_code, 302)
        self.assertEqual(a.get("/").status_code, 302)
        self.assertEqual(b.get("/").status_code, 200)

    def test_user_cannot_end_someone_elses_session(self):
        a, b = self.make_user("a1"), self.make_user("b1")
        ca, cb = self.client_for(a), self.client_for(b)
        victim = UserSession.objects.get(user=a)
        cb.post(f"/account/sessions/{victim.pk}/end/")
        self.assertEqual(ca.get("/").status_code, 200)

    def test_sign_out_everywhere_else_keeps_this_device(self):
        u = self.make_user("dev1")
        a, b = self.client_for(u), self.client_for(u)
        b.post("/account/sessions/end-others/")
        self.assertEqual(a.get("/").status_code, 302)
        self.assertEqual(b.get("/").status_code, 200)

    def test_suspending_an_account_signs_it_out_immediately(self):
        u = self.make_user("dev1")
        c = self.client_for(u)
        services.suspend_user(u, actor=self.admin)
        self.assertEqual(c.get("/").status_code, 302)

    def test_admin_can_force_sign_out(self):
        u = self.make_user("dev1")
        c = self.client_for(u)
        self.client_for(self.admin).post(f"/people/{u.pk}/force-logout/")
        self.assertEqual(c.get("/").status_code, 302)


class PasswordTests(IAMTestCase):
    def test_new_accounts_are_forced_to_change_password(self):
        u = self.make_user("new1", must_change_password=True)
        c = self.client_for(u)
        r = c.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/password/change/", r["Location"])

    def test_changing_password_ends_other_sessions_but_not_this_one(self):
        u = self.make_user("dev1")
        a, b = self.client_for(u), self.client_for(u)
        r = b.post("/password/change/", {"old_password": PASSWORD, "new_password1": "An0ther-Long-Pass!",
                                         "new_password2": "An0ther-Long-Pass!"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(b.get("/").status_code, 200)
        self.assertEqual(a.get("/").status_code, 302)
        u.refresh_from_db()
        self.assertTrue(u.check_password("An0ther-Long-Pass!"))
        self.assertFalse(u.must_change_password)

    def test_weak_or_wrong_current_password_is_refused(self):
        u = self.make_user("dev1")
        c = self.client_for(u)
        c.post("/password/change/", {"old_password": PASSWORD, "new_password1": "12345678", "new_password2": "12345678"})
        c.post("/password/change/", {"old_password": "nope", "new_password1": "An0ther-Long-Pass!",
                                     "new_password2": "An0ther-Long-Pass!"})
        u.refresh_from_db()
        self.assertTrue(u.check_password(PASSWORD))
