"""Demo organisation with Indian names. Everything goes through the real lifecycle services,
so the audit log, history and directory entries look exactly like production use."""
import secrets
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from access import services as access
from access.models import Entitlement, Grant
from accounts.models import Department, JobRole
from audit import service as audit
from audit.models import Action
from directory import client as ldap_client
from lifecycle import services as lc

User = get_user_model()

DEPARTMENTS = [("Engineering", "ENG"), ("Finance", "FIN"), ("Human Resources", "HR"), ("Sales", "SAL"),
               ("IT Security", "SEC"), ("Operations", "OPS")]
ROLES = {
    "ENG": ["Software Engineer", "Engineering Manager", "DevOps Engineer"],
    "FIN": ["Accountant", "Finance Manager"],
    "HR": ["HR Executive", "HR Manager"],
    "SAL": ["Sales Executive", "Sales Manager"],
    "SEC": ["Security Analyst", "Security Lead"],
    "OPS": ["Operations Executive", "Operations Manager"],
}
ALL = [c for _, c in DEPARTMENTS]

# name, code, description, risk, approval, auto-for departments, auto-for roles, max_days
CATALOG = [
    ("Email & Chat", "email", "Company mail and messaging", "low", "auto", ALL, [], None),
    ("VPN", "vpn", "Remote network access", "low", "auto", ALL, [], None),
    ("Source Code", "source-code", "Read and write the code repositories", "low", "auto", ["ENG"], [], None),
    ("CI/CD Pipeline", "ci-cd", "Run and configure build pipelines", "medium", "manager", [], ["DevOps Engineer"], None),
    ("Production Deploy", "prod-deploy", "Push releases to production", "high", "manager_owner", [], [], 30),
    ("Release Approval", "release-approval", "Sign off releases", "high", "manager", [], ["Engineering Manager"], None),
    ("Production Database (read)", "prod-db", "Read-only access to production data", "high", "manager_owner", [], [], 14),
    ("Finance Ledger", "ledger", "General ledger", "medium", "auto", ["FIN"], [], None),
    ("Payment Initiation", "pay-init", "Create payment batches", "medium", "manager", [], ["Accountant"], None),
    ("Payment Approval", "pay-approve", "Approve payment batches", "high", "manager", [], ["Finance Manager"], None),
    ("CRM", "crm", "Customer records and pipeline", "low", "auto", ["SAL"], [], None),
    ("HR Records", "hr-records", "Employee personal records", "high", "auto", ["HR"], [], None),
    ("Security Console", "sec-console", "SIEM and endpoint console", "high", "auto", ["SEC"], [], None),
    ("Auditor", "auditor", "Read the audit log and identity records", "medium", "manager", [], ["Security Lead"], None),
    ("IAM Admin", "iam-admin", "Administer identities, access and the directory", "high", "manager_owner", [], [], None),
]
CONFLICTS = [("prod-deploy", "release-approval"), ("pay-init", "pay-approve")]

# first, last, department, role, manager-key
PEOPLE = [
    ("Rajesh", "Iyer", "ENG", "Engineering Manager", None), ("Ananya", "Reddy", "ENG", "Software Engineer", "ENG"),
    ("Vikram", "Singh", "ENG", "Software Engineer", "ENG"), ("Kavya", "Nair", "ENG", "DevOps Engineer", "ENG"),
    ("Rohan", "Gupta", "ENG", "Software Engineer", "ENG"), ("Divya", "Menon", "ENG", "Software Engineer", "ENG"),
    ("Suresh", "Pillai", "FIN", "Finance Manager", None), ("Priya", "Sharma", "FIN", "Accountant", "FIN"),
    ("Amit", "Desai", "FIN", "Accountant", "FIN"), ("Neha", "Kulkarni", "FIN", "Accountant", "FIN"),
    ("Sunita", "Verma", "HR", "HR Manager", None), ("Arvind", "Joshi", "HR", "HR Executive", "HR"),
    ("Pooja", "Bhatt", "HR", "HR Executive", "HR"),
    ("Manoj", "Kapoor", "SAL", "Sales Manager", None), ("Ishaan", "Malhotra", "SAL", "Sales Executive", "SAL"),
    ("Tanvi", "Chopra", "SAL", "Sales Executive", "SAL"), ("Karthik", "Subramanian", "SAL", "Sales Executive", "SAL"),
    ("Deepa", "Krishnan", "SEC", "Security Lead", None), ("Farhan", "Ansari", "SEC", "Security Analyst", "SEC"),
    ("Shreya", "Banerjee", "SEC", "Security Analyst", "SEC"),
    ("Harish", "Naidu", "OPS", "Operations Manager", None), ("Lakshmi", "Rao", "OPS", "Operations Executive", "OPS"),
    ("Gurpreet", "Sandhu", "OPS", "Operations Executive", "OPS"), ("Meera", "Chatterjee", "OPS", "Operations Executive", "OPS"),
    ("Nikhil", "Agarwal", "ENG", "Software Engineer", "ENG"), ("Aditi", "Mishra", "FIN", "Accountant", "FIN"),
    ("Sanjay", "Patil", "SAL", "Sales Executive", "SAL"), ("Rekha", "Tripathi", "OPS", "Operations Executive", "OPS"),
]


def uname(first, last):
    return f"{first}.{last}".lower()


class Command(BaseCommand):
    help = "Load a demo organisation (Indian names). Safe to run once; use --force to add again."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--no-credentials", action="store_true", help="Do not write .dev-credentials.txt")

    def handle(self, *args, **opts):
        if User.objects.filter(source__in=["local", "ldap"]).exclude(is_superuser=True).exists() and not opts["force"]:
            self.stdout.write("Demo data already present (use --force to add anyway).")
            return
        demo_pw = secrets.token_urlsafe(12)
        admin_pw = secrets.token_urlsafe(14)

        depts = {c: Department.objects.get_or_create(code=c, defaults={"name": n})[0] for n, c in DEPARTMENTS}
        roles = {}
        for code, titles in ROLES.items():
            for t in titles:
                roles[t] = JobRole.objects.get_or_create(title=t, department=depts[code])[0]

        ents = {}
        for name, code, desc, risk, policy, d_codes, r_titles, max_days in CATALOG:
            e, _ = Entitlement.objects.get_or_create(code=code, defaults={
                "name": name, "description": desc, "risk": risk, "approval_policy": policy, "max_days": max_days})
            e.departments.set([depts[c] for c in d_codes])
            e.job_roles.set([roles[t] for t in r_titles])
            ents[code] = e
        for a, b in CONFLICTS:
            ents[a].conflicts_with.add(ents[b])

        admin, created = User.objects.get_or_create(username="admin", defaults={
            "email": "admin@joinr.local", "first_name": "Arjun", "last_name": "Admin", "is_superuser": True,
            "is_staff": True, "status": User.ACTIVE})
        admin.set_password(admin_pw)
        admin.employee_id = admin.employee_id or "JNR0001"
        admin.save()
        managers, people = {}, {}
        today = timezone.localdate()
        for first, last, dc, title, mgr in PEOPLE:
            u = lc.provision_user(
                actor=admin, username=uname(first, last), email=f"{uname(first, last)}@joinr.local",
                first_name=first, last_name=last, department=depts[dc], job_role=roles[title],
                manager=managers.get(mgr) if mgr else admin, start_date=today - timedelta(days=30 + len(people) * 9),
                phone=f"+91 98{secrets.randbelow(10**8):08d}", via="seed")
            u.must_change_password = False
            self._set_password(u, demo_pw)
            u.save()
            people[uname(first, last)] = u
            if mgr is None:
                managers[dc] = u

        sec_lead, eng_mgr = people["deepa.krishnan"], people["rajesh.iyer"]
        for e in (ents["prod-deploy"], ents["prod-db"], ents["iam-admin"], ents["release-approval"]):
            e.owner = sec_lead
            e.save()
        # deepa runs identity day-to-day: give her the admin catalog item
        access.grant(sec_lead, ents["iam-admin"], Grant.MANUAL, actor=admin)

        # ---- lifecycle variety
        for first, last, dc, title, days in (("Aarav", "Khanna", "ENG", "Software Engineer", 5),
                                             ("Zoya", "Qureshi", "SAL", "Sales Executive", 12)):
            u = lc.provision_user(actor=admin, username=uname(first, last), email=f"{uname(first, last)}@joinr.local",
                                  first_name=first, last_name=last, department=depts[dc], job_role=roles[title],
                                  manager=managers[dc], start_date=today + timedelta(days=days), via="seed")
            self._set_password(u, demo_pw)
            u.must_change_password = False
            u.save()

        lc.schedule_departure(people["amit.desai"], today + timedelta(days=6), actor=admin, reason="resigned")
        lc.suspend_user(people["pooja.bhatt"], actor=admin, reason="investigation pending")
        lc.change_assignment(people["rohan.gupta"], department=depts["ENG"], job_role=roles["DevOps Engineer"],
                             manager=eng_mgr, actor=admin)
        access.grant(people["rohan.gupta"], ents["prod-db"], Grant.REQUEST, actor=admin,
                     expires_at=timezone.now() + timedelta(days=3))
        for k in ("nikhil.agarwal", "rekha.tripathi"):
            lc.deprovision_user(people[k], actor=admin, reason="left the company")

        # ---- access requests in every state
        reqs = [
            (people["ananya.reddy"], "ci-cd", "Need to fix the flaky build pipeline for the payments service", 14),
            (people["vikram.singh"], "prod-deploy", "On-call this month, need to roll out hotfixes", 30),
            (people["farhan.ansari"], "ci-cd", "Need pipeline access to wire security scanners into CI", 14),
            (people["tanvi.chopra"], "prod-db", "Investigating a customer's missing invoice data", 7),
            (people["lakshmi.rao"], "crm", "Covering for the sales desk during Diwali week", 7),
        ]
        made = [access.create_request(u, ents[code], why, days) for u, code, why, days in reqs]
        access.decide(made[0].steps.first(), eng_mgr, True, "go ahead")              # approved and granted
        access.decide(made[1].steps.first(), eng_mgr, True)                           # waits for owner
        access.decide(made[3].steps.first(), managers["SAL"], False, "use the report instead")  # rejected

        for who, reason in (("farhan.ansari", "unknown_user"), ("divya.menon", "bad_password")):
            audit.log(Action.LOGIN_FAIL, actor_label=who, success=False, reason=reason)

        if not opts["no_credentials"]:
            self._write_credentials(admin_pw, demo_pw)
        self.stdout.write(self.style.SUCCESS(
            f"Demo organisation ready: {User.objects.count()} identities, {Entitlement.objects.count()} catalog items. "
            "Sign-in details are in .dev-credentials.txt"))

    def _set_password(self, user, pw):
        if user.source == User.LDAP and settings.LDAP_ENABLED:
            try:
                ldap_client.set_password(user, pw)
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(f"could not set directory password for {user.username}: {exc}")
        else:
            user.set_password(pw)

    def _write_credentials(self, admin_pw, demo_pw):
        path = Path(settings.BASE_DIR) / ".dev-credentials.txt"
        path.write_text(
            "Joinr demo sign-in (local development only)\n\n"
            f"IAM administrator   username: admin                 password: {admin_pw}\n"
            f"Everyone else       username: first.last (e.g. priya.sharma)   password: {demo_pw}\n"
            "Try: deepa.krishnan (IAM admin + auditor), rajesh.iyer (manager), priya.sharma (employee)\n",
            encoding="utf-8")
