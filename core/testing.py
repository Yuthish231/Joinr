"""Shared helpers for the test suites."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from access.models import Entitlement
from accounts.models import Department, JobRole

User = get_user_model()
PASSWORD = "Str0ng-Test-Pass!"

FAST_HASH = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST_HASH
class IAMTestCase(TestCase):
    """Small company: two departments, two roles, a handful of entitlements."""

    @classmethod
    def setUpTestData(cls):
        cls.eng = Department.objects.create(name="Engineering", code="ENG")
        cls.fin = Department.objects.create(name="Finance", code="FIN")
        cls.dev = JobRole.objects.create(title="Developer", department=cls.eng)
        cls.accountant = JobRole.objects.create(title="Accountant", department=cls.fin)

        cls.git = Entitlement.objects.create(name="Source Code", code="git", approval_policy="auto")
        cls.git.departments.add(cls.eng)
        cls.deploy = Entitlement.objects.create(name="Deploy", code="deploy", risk="high", approval_policy="manager")
        cls.deploy.job_roles.add(cls.dev)
        cls.ledger = Entitlement.objects.create(name="Ledger", code="ledger", approval_policy="auto")
        cls.ledger.departments.add(cls.fin)
        cls.reports = Entitlement.objects.create(name="Reports", code="reports", approval_policy="manager")
        cls.prod_db = Entitlement.objects.create(name="Prod DB", code="proddb", risk="high",
                                                 approval_policy="manager_owner", max_days=30)
        cls.pay_start = Entitlement.objects.create(name="Payment Initiation", code="payinit", approval_policy="manager")
        cls.pay_approve = Entitlement.objects.create(name="Payment Approval", code="payappr", risk="high",
                                                     approval_policy="manager")
        cls.pay_start.conflicts_with.add(cls.pay_approve)

        cls.admin = User.objects.create_superuser("root", "root@example.com", PASSWORD, status="active")

    def make_user(self, username, *, department=None, job_role=None, manager=None, status=User.ACTIVE, **kw):
        return User.objects.create_user(
            username=username, email=f"{username}@example.com", password=PASSWORD, first_name=username.title(),
            department=department, job_role=job_role, manager=manager, status=status, **kw)

    def client_for(self, user, password=PASSWORD):
        c = Client()
        assert c.login(username=user.username, password=password), "login failed in test setup"
        return c
