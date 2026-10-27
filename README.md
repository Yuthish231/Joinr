# Joinr

An identity and access management (IAM) system built around the identity lifecycle: **joiners, movers and leavers**.
It covers session management, provisioning and deprovisioning, safe logout, role/department-based access,
approval workflows, LDAP, and a tamper-evident audit log. About 5,000 lines of Django, with 80 automated tests.

## What it does

| Area | How Joinr does it |
|---|---|
| **Session management** | Server-side sessions, each tracked so it can be listed and ended. 30-minute idle timeout, 8-hour absolute limit, at most 3 devices (oldest is signed out). Users see and end their own sessions; admins see and end everyone's. Changing your password, being suspended or being deprovisioned ends sessions immediately. HttpOnly, SameSite cookies; signed-in pages are never cached. |
| **Login protection** | 5 wrong passwords lock the account for 15 minutes, even for the right password. New and reset accounts must set their own password first. Pending, suspended and terminated accounts cannot sign in. |
| **Safe logout** | POST only, with CSRF protection (a link or image elsewhere cannot sign you out). Destroys the server-side session, so a copied cookie is useless afterwards. "Sign out everywhere else" and admin "sign out everywhere". |
| **Provisioning (joiner)** | Creating a person creates the identity, a one-time temporary password, a directory entry, and the access their **department and job role** grant automatically. A future start date keeps the account pending, with no access, until that day. |
| **Mover** | Changing department or role recalculates access: what came from the old role is removed, the new role's access is granted, and anything requested or hand-granted is kept but flagged for re-confirmation. |
| **Deprovisioning (leaver)** | Removes every grant, group and direct permission; makes the password unusable; ends all sessions; cancels their pending requests; hands approvals they owed to the IAM admins; moves their reports to their manager; and disables the directory entry. Safe to run twice. |
| **Last working day** | Set it in advance: access ends automatically at 18:00 that day (configurable), or immediately if the date has passed. The scheduler catches up after downtime. |
| **Access requests and approvals** | Catalog of entitlements with risk levels. Policies: automatic, manager approval, or manager then owner. Optional time limit (capped per entitlement), automatic expiry, no self-approval, admin fallback when there is no manager. **Separation of duties**: conflicting entitlements cannot be held together, checked at request time and again at approval time. |
| **LDAP** | Sign in with the directory password (Joinr never stores it). Sync imports directory people, maps `departmentNumber` and `title` to department and role, treats a changed department as a move and a disabled entry as a leaver. Write-back: joiners get an entry, approved access adds them to the matching LDAP group, leavers are scrambled, removed from groups and moved to `ou=Disabled`. A directory outage never blocks a leaver. |
| **Audit** | Every identity event (logins, failures, lockouts, sessions, lifecycle, grants, approvals, directory) in an append-only, SHA-256 hash-chained log. "Verify integrity" detects any edited or deleted record. CSV export. |

## Roles

- **Employee**: sees and requests their own access, manages their own sessions.
- **Manager**: also approves their team's requests and sees their team's records.
- **Auditor**: reads every identity record and the audit log (granted through the catalog).
- **IAM Admin**: runs the lifecycle, catalog, sessions and directory (granted through the catalog, not hard-coded).

## Run it

```bash
docker compose up --build -d
```

Open http://localhost:8000. The first start loads a demo organisation with Indian names into PostgreSQL and OpenLDAP.
Sign-in details:

```bash
docker compose exec web cat .dev-credentials.txt
```

Good accounts to try: `admin` (IAM admin), `deepa.krishnan` (security lead: IAM admin + auditor),
`rajesh.iyer` (engineering manager, has approvals waiting), `priya.sharma` (employee).
Three more people (`imran.sheikh`, `pallavi.hegde`, `gautam.bose`) exist only in LDAP: press **Directory → Sync now** to import them.

Without Docker (SQLite, LDAP off):

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
python manage.py migrate && python manage.py seed_demo
DEBUG=true python manage.py runserver
```

## Test it

```bash
python manage.py test
```

80 tests cover sessions, lockout, logout, joiner/mover/leaver, the last-working-day scheduler, approvals, separation of
duties, audit tamper detection, role-based screens, and LDAP (against an in-memory directory, so no server is needed).

## Layout

```
accounts/   users, departments, job roles, sign-in, lockout, session tracking and rules, logout
lifecycle/  joiner / mover / leaver services, scheduler, people screens
access/     entitlement catalog, grants, requests, approval steps, separation of duties
directory/  LDAP client, login backend, sync, write-back provisioning
audit/      hash-chained audit log
core/       dashboard, navigation, demo data
```

All identity changes go through `lifecycle/services.py` and `access/services.py`, so every change is audited and
there is no back door (the Django admin site is deliberately not installed).

## Settings

Environment variables (see `.env.example`): `SESSION_IDLE_SECONDS`, `SESSION_ABSOLUTE_SECONDS`, `MAX_CONCURRENT_SESSIONS`,
`LOCKOUT_THRESHOLD`, `LOCKOUT_MINUTES`, `LEAVER_CUTOFF_HOUR`, `LDAP_ENABLED`, `LDAP_SERVER_URI`, `LDAP_BIND_DN`,
`LDAP_BIND_PASSWORD`, `LDAP_BASE_DN`, `LDAP_WRITE_BACK`, `COOKIE_SECURE`, `DATABASE_URL`.

The passwords in `docker-compose.yml` are throw-away development values.
