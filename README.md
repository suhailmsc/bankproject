# Northstar Bank - Django banking demo (v2)

A realistic, production-style Django + PostgreSQL retail banking app for the Enterprise Banking
Disaster Recovery project. **Fictional bank, fictional money. Not for real customers.**

## What changed from the starter

| Area | Starter | Now |
|---|---|---|
| Identity | Django `auth_user`, one account per user | Custom `User` (email login) with two strictly separated kinds: **customer** and **staff** |
| Admin access | Any user flagged staff | Customers can **never** reach or sign in to the staff console (see below) |
| Accounts | One account, created by an admin | Customers open up to 5 savings/current accounts themselves |
| Money | Balance + transfer | Locked, atomic postings; immutable ledger; DB constraints; idempotent confirm step |
| Payees | Type any account number | Saved beneficiaries with account-number checksum and name verification |
| Security | Defaults | Argon2, lockout, idle timeout, CSP, HSTS, step-up password on transfers, audit trail |
| Ops | `runserver` | gunicorn, WhiteNoise, `/healthz` + `/readyz`, non-root image, env-driven config |

> **The old `db.sqlite3` is not compatible** (different user table and schema). Delete it; a fresh database is created on first run.

## Customers cannot use the Django admin (defence in depth)

1. **Different identity kinds.** `User.kind` is `customer` or `staff`. Registration only creates customers.
2. **Forced flags.** `User.save()` forces `is_staff` and `is_superuser` to `False` for customers, and a database
   `CHECK` constraint (`customers_are_never_staff`) rejects any row that tries otherwise, even from raw SQL.
3. **Console login rejects customers** even with a correct password (`StaffAdminSite.login_form` + `has_permission`).
4. **Hidden URL.** The console lives at `ADMIN_URL` (default `/staff-console/`, not `/admin/`). A signed-in customer
   who requests it gets a plain **404** and the attempt is written to the audit log.
5. **Reverse isolation.** Staff credentials do not work on the customer portal, and staff who browse to it are redirected to the console.
6. **Staff cannot touch customer credentials.** The console shows customers read-only (except "active") and the
   set-password page returns 404 for them. Balances are read-only too; they change only through ledger postings.
7. **Password reset** on the portal only ever applies to customers.

## Run it

### Docker (PostgreSQL)
```bash
cp .env.example .env            # optional; compose has safe local defaults
docker compose up --build
docker compose exec web python manage.py createsuperuser      # creates a STAFF user (email + names + password)
```
- Customer portal: http://localhost:8000
- Staff console: http://localhost:8000/staff-console/
- Verification and alert emails print to `docker compose logs web` (console email backend while `DEBUG=1`).

### Plain Python (SQLite)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DEBUG=1
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### Try the flow
1. Register two customers in two browsers (or one normal + one private window).
2. Each opens an account (demo mode offers a fictional opening balance, or use **Add demo funds**).
3. Customer A: **Beneficiaries -> Add**, enter customer B's 12-digit account number (the name is shown masked in lists and in full on the review screen).
4. **Send money -> Review -> confirm with password -> receipt.** Both statements show the entry; CSV export and print are on the account page.
5. In the staff console: verify KYC (raises limits), freeze/unfreeze accounts, read the ledger and audit log.

## Bank rules (all in env, see `.env.example`)
- Accounts: savings or current, max 5 open per customer, 12-digit numbers with a Luhn check digit, branch code `NSTB0000001`.
- Transfers: min 1, max 100,000 per transfer; daily limit to *other people* of 25,000 (KYC pending) or 200,000 (KYC verified). Transfers between your own accounts are not limited.
- Every transfer: review screen, password re-entry (3 attempts), 5-minute expiry, idempotency key, debit and credit alert emails.
- Sessions end after 15 idle minutes; 5 failed sign-ins lock that email+IP for 15 minutes (django-axes).
- Passwords: 10+ characters, complexity, common-password and similarity checks, Argon2 hashing.
- Money is `Decimal(14,2)`; balances cannot go negative (DB constraint); ledger rows and audit rows cannot be edited or deleted.

## Deploying (AWS / DR notes)
- **Health checks:** `GET /healthz` (liveness) and `GET /readyz` (database reachable). They bypass host validation and the HTTPS redirect, so ALB/ECS probes on the container IP work. Use `/readyz` as the target-group check.
- **Behind an ALB:** set `BEHIND_PROXY=1`, `HTTPS_ONLY=1`, `ALLOWED_HOSTS=<your domain>`, `CSRF_TRUSTED_ORIGINS=https://<your domain>`.
- **Secrets:** `SECRET_KEY` and `DATABASE_URL` from Secrets Manager/SSM. The app refuses to start with `DEBUG=0` and a missing or placeholder key.
- **Migrations:** run `python manage.py migrate` as a one-off task and set `RUN_MIGRATIONS=0` on web containers once you scale past one.
- **Multiple workers/instances:** set `REDIS_URL` so rate limits are shared. Lockout counters already live in the database. Sessions are in the database, so failover to a replica region keeps customers signed in only if the DB is replicated.
- **Static files:** collected at image build and served by WhiteNoise (put CloudFront in front if you like).
- **Logs:** everything goes to stdout; audit events are logged as `banking.audit` lines as well as stored in the `AuditLog` table.

## Tests
```bash
DEBUG=1 python manage.py test tests
```
43 tests cover the admin/customer separation, registration rules, transfers (limits, idempotency, frozen accounts, authorisation), ledger immutability, CSV formula injection and page smoke tests.

## Layout
```
banking_project/   settings (env driven), urls, wsgi
accounts/          custom User + Customer (KYC), auth forms/views, email verification, staff user admin
banking/           Account, Transaction, LedgerEntry, Beneficiary, services.py (all money movement), views, admin
core/              AuditLog, middleware (health, console isolation, security headers), staff AdminSite, rate limiting
templates/ static/ responsive UI, no inline scripts (strict CSP)
tests/
```

## Honest limits (this is still a learning prototype)
No MFA/OTP, no real KYC or document upload, no interbank rails (NEFT/IMPS/UPI), no interest, fees or statements by PDF,
no double-entry general ledger or reconciliation, no maker-checker approvals for staff, no fraud engine. Rate limiting
is per IP (shared only with Redis). The test suite runs on SQLite; the PostgreSQL row-locking path (`SELECT ... FOR UPDATE`)
is written for but should be exercised on your Postgres before you rely on it under load.
