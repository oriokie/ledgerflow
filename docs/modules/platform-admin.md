# Platform Administration Workspace

The owner-only console for operating LedgerFlow as a SaaS business. It is not
a tenant, has no workspace context, and is reached at `/admin` (UI) and
`/api/v1/platform/` (API).

---

## 1. The security model

Everything about this module follows from one decision: **the platform console
operates on the control plane, and reaching customer financial data requires an
audited, time-boxed impersonation grant.**

LedgerFlow already enforces tenant isolation with fail-closed PostgreSQL
row-level security. Household financial tables (`finance_transaction`,
`ledger_*`, `budgeting_*`, …) carry an RLS policy keyed on the
`app.current_tenant` GUC. Control-plane tables (`tenancy_*`, `billing_*`,
`users_*`) deliberately do not — they are written around the edges of a tenant
context and read cross-tenant by trusted workers.

`PlatformAdminAPIView` **never binds a tenant**. So:

* Platform endpoints read the control plane natively — tenants, subscriptions,
  payments, invoices, staff, audit.
* If a platform view ever touched a tenant-scoped table by mistake, Postgres
  returns **zero rows**, not another customer's ledger. The isolation guarantee
  protects the console from its own bugs.
* There is exactly one way through: `services.impersonation.impersonate()`,
  which binds a real tenant context against a stored grant.

The console therefore shows *who the customer is and what they pay*, never
*what they spend*.

### Impersonation

| Property | Enforcement |
|---|---|
| Requires `tenant.impersonate` | `services.impersonation.start` |
| Requires a ≥10-character reason | service + serializer |
| Read-only unless explicitly disabled | `ImpersonationGrant.read_only` |
| Expires automatically | `PLATFORM_IMPERSONATION_TTL_MINUTES` (default 30) |
| Revocable mid-session | every request re-reads the grant |
| Token stored only as SHA-256 | `token_hash`; raw returned once |
| Ends when staff access is revoked | `staff.revoke` → `revoke_all_for_staff` |
| Every request counted | `request_count` |

A JWT claim could not offer mid-session revocation, which is why the grant is a
row rather than a token claim.

---

## 2. RBAC

Platform authority is a **separate system** from tenancy RBAC. A workspace
OWNER has total authority over their household and none over the platform; a
BILLING_ADMIN can refund any tenant's payment and read none of their
transactions. One hierarchy could not express that.

Capabilities are the unit of authorization — nothing asks "is this person an
admin", only "may they do `tenant.suspend`". Roles are named bundles.

### Roles

| Role | Shape |
|---|---|
| `platform_owner` | Everything |
| `platform_administrator` | Everything except `staff.manage`, `refund.approve`, `tenant.delete` |
| `billing_administrator` | Read-all + subscription/invoice/coupon/dunning writes, `refund.request` |
| `finance` | Read-all + `refund.approve`, `payment.reconcile`, `credit.issue` |
| `customer_success` | Read-all + `tenant.write`, `tenant.impersonate`, `subscription.write`, `refund.request` |
| `technical_support` | Read-all + `tenant.impersonate`, `tenant.export`, `webhook.replay` |
| `read_only_auditor` | Read-only |

### Separation of duties

`refund.request` and `refund.approve` are distinct capabilities held by
different roles. `approve_refund()` additionally refuses when the approver is
the requester — an RBAC split is meaningless if one person holding both
capabilities can satisfy it alone.

`subscription.grant` (comps, gifts) is split from `subscription.write` (moving
a customer between plans they pay for). Giving away revenue-bearing product is
a commercial decision, not routine support.

### Per-person overrides

`PlatformStaff.extra_capabilities` / `denied_capabilities` widen or narrow a
role without inventing a new one. **Denials always win.** An unknown capability
string raises `UnknownCapabilityError` rather than silently conferring nothing —
a typo in a grant must not look like it succeeded.

### Privilege-escalation guard

A staff member cannot grant a capability they do not hold, cannot change their
own role, and cannot revoke their own access. The last active owner cannot be
revoked. Without these, anyone with `staff.manage` is effectively an owner.

The single exception is the bootstrap path (`actor=None`), reachable only from
the server console:

```bash
python manage.py bootstrap_platform_owner --email ops@example.com
```

### Additional gates

* **MFA** is required by default (`PlatformStaff.require_mfa`). Enrolment is
  checked per request, so removing an authenticator revokes platform access
  immediately rather than at next login.
* **IP allowlist** (`allowed_ips`) accepts addresses or CIDR blocks. Empty =
  unrestricted; non-empty = fail-closed. A malformed entry never widens access.

---

## 3. Audit

`PlatformAuditLog` is **append-only, enforced by a database trigger** (migration
`platform_admin/0002`), reusing the same `ledgerflow_forbid_mutation()` function
that protects the ledger. Application convention is not a control; the people
with most motive to edit this table are the people with database access.

Every row carries: actor id **and denormalized email** (an audit trail that goes
anonymous when an employee is deleted has failed at its only job), role, action,
module, target, tenant, a `{field: [before, after]}` diff, the operator's
**reason**, IP, user agent, and request id.

Destructive and money-moving actions require a reason at the serializer boundary
(so the UI can attach it to the textarea) *and* in the service (so a Celery task
or management command is held to the same standard).

---

## 4. Billing domain

Invoices, refunds, credits, coupons and dunning live in **`apps.billing`**, not
in `platform_admin`. They are billing domain objects the tenant-facing app also
needs; the platform module is an operator console *over* them.

### Invoices — why totals are stored

The product's rule is "no persisted projections — read from the ledger". An
invoice is the deliberate exception, and not really an exception: it is not a
*view* of current state but a point-in-time legal artifact. Recomputing last
March's invoice from today's prices and tax rates would produce a different
document than the customer paid.

Arithmetic order is **subtotal → discount → credit → tax**. Taxing before
discounting overcharges; crediting before discounting consumes more of the
customer's credit than the invoice needs.

Invoice numbers come from a locked counter row, not a Postgres sequence:
sequences are non-transactional, so a rolled-back invoice would burn a number
and leave a gap an auditor will ask about.

`invoice_for_subscription_period` is idempotent per (subscription, period) — a
replayed billing sweep must not bill twice.

### Credits

Consumed oldest-first (credits expire; spending a lapsing one first is strictly
better for the customer), locked with `SELECT … FOR UPDATE` so concurrent
invoice runs cannot double-spend. Voiding an invoice **returns** the credit it
consumed. Voiding a credit withdraws only the unspent remainder.

### Refunds

Two-step by design: `request_refund` records intent, `approve_refund` moves
money. The refundable balance counts **in-flight** refunds, not just settled
ones — otherwise two agents each refunding "the remaining half" within a minute
both pass validation and the platform pays out 150%.

M-PESA reversals return `PROCESSING`, never `SUCCEEDED`: Safaricom queues a
reversal for approval and confirms out-of-band. Reporting success before they
agree would lie to the customer. A webhook settles it via
`settle_pending_refund`.

### Coupons

One model covers percentage, fixed, free-months and trial-extension promotions.
`Coupon.value` is polymorphic and interpreted in exactly one place —
`promotions.discount_for()`. Eligibility returns a *reason*, not a bool: "This
promotion expired on 3 March" is actionable where "invalid" is not.

A fixed-amount discount is currency-bound and never converted — an FX move must
not silently change a promise already made.

### Dunning

Three models: `DunningPolicy` (tunable config), `DunningCase` (one recovery
episode), `DunningAttempt` (one scheduled step, written **before** execution).

Writing the whole schedule up front means:

* "What happens to this customer next, and when" is answerable.
* A policy change is not retroactive — a customer keeps the terms they entered
  dunning under.
* The worker *claims* a due attempt, so a sweep running twice does not send two
  reminders.

`SUSPENDED` is an intermediate state, not terminal: a suspended case still
progresses to abandonment. Suspension means loss of **access**, never deletion —
a customer who pays on day 30 gets their data back intact.

### Invoice documents

The PDF is **rendered on demand and never stored**. The invoice row already
holds the frozen arithmetic, so the document is fully reproducible from it —
and not storing it means there is exactly one source of truth. A cached PDF
that disagreed with the invoice it claims to represent would be worse than no
PDF.

`render_invoice_pdf()` makes **zero database queries** when line items are
prefetched. That property is locked down by a test: a document generator that
lazily loads a related field is one refactor away from an N+1 inside a PDF
loop, and from putting data on the document the caller never intended.

The issuing entity is configurable (`INVOICE_ISSUER`) because it is a
deployment fact, not a product one — a reseller bills under their own name.

Delivery is a Celery task. A slow mail provider must never block the request
that issued the invoice, and delivery is retryable where the operator's intent
is not. A missing invoice or missing address returns a reason rather than
retrying — neither is fixable by trying again. `send_invoice_email()` raises
rather than no-opping when there is no address: "send this invoice" quietly
succeeding without sending surfaces weeks later as an unpaid bill nobody
chased.

```
GET  /api/v1/platform/invoices/{id}/pdf/    billing.read    → application/pdf
POST /api/v1/platform/invoices/{id}/send/   invoice.write   → queues delivery
```

Downloading is **not audited** — reading a document is not an administrative
action, and logging every glance at a bill would bury the actions that matter.
Sending *is* audited, because it puts a message in front of a customer.

---

## 4b. Operator/customer separation

A platform account operates the product; it does not use it. `create_workspace`
and `accept_invitation` both refuse platform staff, so the two ways an account
becomes a tenant member are closed.

Three reasons, any one sufficient:

* **Audit clarity.** The impersonation trail answers "when did staff touch
  customer data". If the operator also owns a workspace, personal and
  administrative activity interleave under one identity and reconstructing an
  incident becomes guesswork.
* **Blast radius.** A compromised operator credential already exposes the
  control plane. It should not additionally expose someone's personal finances.
* **Metric hygiene.** Billing, dunning and churn all assume a workspace has a
  paying owner. An operator's workspace is neither paying nor churnable and
  quietly pollutes every figure the console reports.

Enforced at the **service layer**, so it holds for the API, a management
command and a Celery task alike. `ProtectedRoute` also routes staff to
`/admin`, but that is convenience — the service is the control.

Governed by `PLATFORM_STAFF_SEPARATE_FROM_TENANTS` (default on), because a solo
founder dogfooding their own product is a real situation that deserves a
knowing opt-out rather than a workaround.

Pre-existing memberships are **recorded in the audit row, not severed**.
Removing someone from their own household because they were given a support
role would be a startling side effect of a permissions change, and their data
is not ours to delete.

`GET /api/v1/auth/me/` carries `is_platform_staff` so the *customer* app can
redirect rather than showing a workspace picker the account may not use. A bare
boolean leaks nothing; capabilities stay behind the platform API.

---

## 4c. Runtime settings — what may be edited, and what may not

The hard question is which configuration belongs in a database an admin can
edit. The split:

**Operational settings** live in the database: which payment providers are
offered, the invoice issuer's name and tax ID, default tax rate, payment terms,
whether AI is available, which model. These are commercial decisions someone
makes on a Tuesday, and requiring a deploy for each guarantees they are made
badly or not at all.

**Secrets stay in the environment by default.** Putting a live Stripe key behind
a web form changes the security posture in ways that are easy to understate: a
database dump becomes a payment credential — inherited by backups, replicas and
analytics exports — and any XSS in the console becomes credential theft rather
than an ugly but bounded incident.

But refusing outright is its own failure: a deployment that cannot rotate a key
without a release is one that does not rotate keys. So a secret **may** be
stored, encrypted with `FIELD_ENCRYPTION_KEY` (the key that protects TOTP
secrets — deliberately not `SECRET_KEY`), as an explicit opt-in.

    database override  →  environment  →  built-in default

Two properties worth stating plainly:

* **The API never returns a secret's value.** It reports whether one is set and
  which layer supplied it. An operator can rotate a credential; nobody reads one
  back out through the console.
* **The audit row records that a secret changed and by whom, never its value.**
  An audit log holding live credentials is a liability, not a control.

Only *explicit* overrides take precedence. The store's own default must never
displace a value a deployment configured — that would be precedence exactly
backwards. `get_overrides()` exists for this, and batches the read so invoice
rendering costs one query rather than four.

### Who controls AI

Three independent gates. A workspace *member* appears in none of them:

1. **Platform (operator)** — is AI available at all, which provider, which key.
   A cost and data-processing decision.
2. **Plan** (`Plan.ai_insights`) — has this workspace paid for it. An
   entitlement on the subscription, bought per workspace.
3. **Workspace owner** (`Tenant.ai_enabled`) — an opt-out, always available.

Choosing where a household's financial data gets sent is a decision made *for*
everyone in the household. It belongs to the operator who chose the vendor and
the owner who can decline — not to whichever member opened a settings page.
Opting out is always available; opting in is not.

```
GET  /api/v1/platform/settings/   health.read
POST /api/v1/platform/settings/   staff.manage
```

---

## 5. Metrics

Conventions are stated because these numbers get quoted to boards:

* **MRR** normalises annual plans (`price / 12`), so it is a run-rate rather
  than a series that spikes every January.
* **Complimentary subscriptions are excluded.** A comp is real usage and zero
  revenue.
* **Trialing subscriptions are excluded** and counted separately.
* **Free plans are excluded from ARPA** — including them drags it toward zero.
* **MRR is per-currency, never summed.** Summing needs an FX rate, and baking
  today's rate into history makes last quarter's MRR move when rates do.
* **Collected revenue is net of refunds.**
* **LTV is `null`, not infinity, when churn is zero.** A fabricated number gets
  quoted as if it meant something.
* **The forecast is labelled a linear extrapolation** and clamped to ±50%/month.

> **Implementation note.** `_revenue_subscriptions()` excludes comps via an id
> subquery, *not* `.exclude(metadata__complimentary=True)`. For a row whose JSON
> lacks the key — every ordinary subscription — the path lookup yields SQL NULL,
> so `NOT (NULL = true)` is NULL rather than TRUE and Postgres drops the row.
> The naive form reported **zero MRR platform-wide**. See
> `test_ordinary_subscriptions_are_not_mistaken_for_complimentary_ones`.

---

## 6. Usage telemetry and the RLS boundary

Storage and transaction counts live in RLS-protected tables the console cannot
read. `platform.capture_usage_snapshots` binds each tenant's context in turn —
exactly as a member's request would — and copies out **counts and byte totals
only**. No financial content crosses the boundary; only magnitudes do.

`TenantUsageSnapshot` is not a forbidden persisted projection: a snapshot is an
observation with a timestamp, and recomputing last month's storage figure from
today's data would destroy the trend it exists to show.

---

## 7. API

All routes under `/api/v1/platform/`. No route accepts `X-Tenant-ID`.

| Method & path | Capability |
|---|---|
| `GET /me/` | any active staff |
| `GET /capabilities/` | `staff.read` |
| `GET /dashboard/` | `platform.dashboard.view` |
| `GET /analytics/?report=…` | `platform.analytics.read` |
| `GET /tenants/` | `tenant.read` |
| `GET /tenants/{id}/` | `tenant.read` |
| `PATCH /tenants/{id}/` | `tenant.write` |
| `POST /tenants/{id}/suspend/` · `reactivate/` | `tenant.suspend` |
| `POST /tenants/{id}/close/` | `tenant.delete` |
| `POST /tenants/{id}/extend-trial/` · `change-plan/` · `cancel-subscription/` · `resume-subscription/` · `reset-billing/` | `subscription.write` |
| `POST /tenants/{id}/complimentary/` | `subscription.grant` |
| `POST /tenants/{id}/credit/` | `credit.issue` |
| `POST /tenants/{id}/impersonate/` | `tenant.impersonate` |
| `GET /impersonations/` | `audit.read` |
| `POST /impersonations/{id}/end/` | own session, or `audit.read` |
| `GET /invoices/`, `/payments/`, `/subscriptions/` | `billing.read` |
| `POST /invoices/{id}/void/` | `invoice.write` |
| `POST /payments/reconcile/` | `payment.reconcile` |
| `GET /refunds/` | `billing.read` |
| `POST /refunds/` | `refund.request` |
| `POST /refunds/{id}/approve|reject/` | `refund.approve` |
| `GET/POST /coupons/` | `coupon.read` / `coupon.write` |
| `GET /dunning/cases/` | `dunning.read` |
| `POST /dunning/cases/{id}/recover|cancel/` | `dunning.manage` |
| `GET/POST /dunning/policies/` | `dunning.read` / `dunning.manage` |
| `GET/POST /staff/` | `staff.read` / `staff.manage` |
| `GET /audit/` | `audit.read` |
| `GET /health/` | `health.read` |
| `GET /notifications/` | `platform.notification.read` |
| `POST /notifications/[{id}/]ack/` | `platform.notification.manage` |
| `GET/POST/DELETE /saved-views/` | any active staff |

Pagination is **offset-based** here, unlike the tenant API's cursor pagination:
admin lists need "jump to page 40" and a total count, and these tables are
thousands of rows rather than millions.

---

## 8. Scheduled work

| Task | Schedule | Purpose |
|---|---|---|
| `platform.run_dunning` | hourly | Execute due retries, reminders, suspensions |
| `platform.mark_overdue_invoices` | daily 00:30 | `PENDING` → `OVERDUE` |
| `platform.expire_impersonations` | every 5 min | Close abandoned sessions |
| `platform.capture_usage_snapshots` | daily 04:00 | Cross-RLS usage telemetry |
| `platform.sweep_alerts` | every 15 min | Health signals → acknowledgeable alerts |

---

## 9. Health

Every probe is defensive to the point of never raising — a health dashboard that
500s when Redis is down has failed at the moment it was needed. Status
vocabulary: `ok` / `degraded` / `down` / `unknown`.

`unknown` is distinct from `down`: an unconfigured SMS provider is not an
outage, and colouring it red trains operators to ignore red. `unknown` never
degrades the rollup.

---

## 10. Frontend

* Routes: `/admin/*`, lazily loaded as its own chunk so customers never
  download the console.
* `AdminGuard` refuses flatly rather than redirecting — a redirect would confirm
  `/admin` exists and that the visitor merely lacks access.
* The rail is always the inverse surface. An operator with both apps open must
  know at a glance which one they are about to act in.
* `useCapability` reads the **server-resolved** capability list from `/me/`, so
  the client never reimplements the role mapping. Hiding a control is a
  courtesy; the API enforces independently.
* `ReasonDialog` gates every audited action. Free text, not a dropdown — a
  dropdown produces a log where every entry says "Other".
* Built entirely on existing design tokens, so dark mode and WCAG contrast come
  for free.

---

## 11. Configuration

```bash
PLATFORM_IMPERSONATION_TTL_MINUTES=30   # impersonation grant lifetime
PLATFORM_QUEUE_BACKLOG_THRESHOLD=500    # queue depth → "degraded"
```

```python
# settings — the entity that issues invoices
INVOICE_ISSUER = {
    "name": "Acme Ltd",
    "address": "1 Example Street, Nairobi",
    "email": "billing@acme.example",
    "tax_id": "P051234567X",
}
```

---

## 12. Getting a testable admin

```bash
python manage.py seed_platform_demo
```

Creates a Platform Owner (`admin@ledgerflow.test` / `PlatformAdmin!2026`) plus
ten demo workspaces chosen so every screen has something real to render:
healthy monthly and annual subscriptions, a trial ending in three days, a
converted trial and a lapsed one, an account already in dunning, a suspended
workspace, an overdue invoice, account credit, and a churned customer.

Flags: `--email`, `--password`, `--admin-only`, `--require-mfa`.

Notes on the design:

* **2FA is waived by default** so the seeded account is immediately usable, and
  the command says so loudly on stdout. Pass `--require-mfa` to keep the
  production posture.
* **Refuses to run with `DEBUG` off** unless
  `--i-know-this-is-not-production` is passed. Seeding fake customers into a
  production database would corrupt every revenue figure the console reports.
* **Idempotent.** Re-running resets the admin password (a forgotten seed
  credential helps nobody) and tops up missing demo data rather than
  duplicating it.
* **Tenants and subscriptions are backdated.** Without it, churn computes a
  single cancellation over a base of zero and reports 100% — arithmetically
  correct and a completely misleading first impression.
* **The seed never binds a tenant context**, so it cannot write household
  financial data even by accident. A test asserts exactly that, rather than
  asserting "no ledger rows exist", which would be vacuous: reading a
  tenant-scoped table with no tenant bound returns zero rows either way.

For production, use the narrower bootstrap instead:

```bash
python manage.py bootstrap_platform_owner --email ops@example.com
```

---

## 13. Visual verification

`scripts/ui_smoke.py` drives a real Chromium against a running stack and fails
on any console error, any blank page, or any missing landmark. It exists
because unit tests and API calls answer a different question than "does this
render": a page can satisfy every assertion about its data and still throw on
mount or hide its content behind a CSS mistake.

Covers all eleven console routes plus tenant detail, dark mode, mobile, the
operator→console redirect, and both customer-side bug fixes. Screenshots land
in `/tmp/ui-shots/`.

Two findings from the first run, both in the harness rather than the product:

* The dev server returns `index.html` for `/sw.js` (the PWA worker is generated
  at build time), so service-worker registration fails at error level. Filtered
  as a dev-only artifact.
* Screenshotting 1.2s after `networkidle` captured loading states. React Query
  had not resolved; the assertion was photographing a spinner.

```bash
python3 scripts/ui_smoke.py     # requires Django on :8000 and Vite on :5173
```

---

## 14. Tests

| File | Count | Covers |
|---|---|---|
| `tests/test_platform_admin_rbac.py` | 34 | Roles, capabilities, permissions, IP/MFA gates, audit immutability, staff governance |
| `tests/test_platform_admin_operations.py` | 51 | Tenant lifecycle, subscriptions, impersonation, metrics, directory N+1, API flows |
| `tests/test_billing_operations.py` | 46 | Invoicing arithmetic, credits, refund workflow, coupons |
| `tests/test_dunning_engine.py` | 23 | Policies, scheduling, execution, recovery, suspension, webhooks |
| `tests/test_invoice_documents.py` | 26 | PDF rendering, email delivery, task behaviour, API |
| `tests/test_platform_seed.py` | 13 | Seed guardrails, idempotency, resulting metric shape |
| `tests/test_platform_separation_and_settings.py` | 26 | Operator/customer separation, settings resolution, secret handling |
| `tests/test_empty_state_feedback.py` | 10 | Setup actions produce visible feedback (investments, debt) |
| `frontend/…/pages/admin/AdminSettingsPage.test.tsx` | 8 | Secret masking, value provenance, read-only mode |
| `frontend/…/pages/investments/SecuritiesTable.test.tsx` | 6 | Tracked securities render before any trade |
| `frontend/…/pages/admin/admin.test.tsx` | 19 | Capability gating, guard, reason enforcement, invoice actions, formatters |

Backend **1168 passing** (939 baseline + 229). Frontend **636 passing**
(603 baseline + 33). `tsc -b` clean, `vite build` green. The suite passes twice
in a row against a reused database — see below.

### Bugs the tests caught during development

1. **Suspended dunning cases never progressed.** The due-attempt sweep filtered
   on `status == OPEN`, so suspension stranded a case forever — the account lost
   access but was never cancelled and the case never resolved. Fixed by making
   "live" a first-class concept (`LIVE_CASE_STATUSES`) covering OPEN and
   SUSPENDED, and widening the partial unique index to match.
2. **MRR reported zero platform-wide.** The JSON `exclude()` trap described in
   §5.

3. **Seeded `sort_order` overflowed `smallint`.** The seed used plan price as
   catalog position; a KES price of 129,000 minor units exceeds a
   `PositiveSmallIntegerField`. Caught by Postgres on first run.

Both product bugs have named regression tests. The invoice-arithmetic and
over-refund invariants were additionally verified by reverting the fixes and
confirming the suite went red on exactly the right tests.

### Two product bugs reported from a running instance

Both had the same root cause wearing different clothes: **a page gated its
entire body on a derived summary that stays null until transactional activity
exists**, so the setup step the empty state instructed the user to take
produced no visible change.

* **Investments.** `securities` was fetched but never rendered — used only to
  enable buttons. Adding a security changed nothing on screen, so the user
  reasonably added it again and got "already tracked", contradicting everything
  visible. The backend was correct throughout; reproducing the flow showed 201,
  a correct list, and a correct 422. Fixed with a `SecuritiesTable` that renders
  whenever securities exist, and two genuinely distinct empty states.
* **Debt.** `debt_views()` drops accounts with a zero balance, which is right
  for "what you owe" — a paid-off card is not debt and would put a meaningless
  row in the payoff plan. But it made a just-added credit card invisible. Fixed
  with a separate `tracked_liabilities()` selector and `GET /debt/debts/tracked/`
  that includes zero-balance accounts and **never feeds planning arithmetic**
  (there is a test asserting exactly that).

### A pre-existing test-suite bug, fixed

The suite could not run twice in a row. `django_db(transaction=True)` flushes
every table on teardown, and the flush does not spare rows written by data
migrations — specifically the FX rates from `fx/0002_seed_rates`. Every later
test then saw an empty rate table, and because `pytest.ini` sets `--reuse-db`,
the loss persisted into the *next* invocation. The symptom was FX tests that
passed on a fresh database and failed on the second run, which reads as
flakiness and is not. CI never saw it because CI always builds a fresh database.

Django's own remedy, `serialized_rollback=True`, does not fix this: it restores
at the start of the next *transactional* test, leaving the ordinary tests in
between looking at an empty table. The fix is an autouse fixture in
`tests/conftest.py` that re-applies the seed when it has been wiped, reading
the rates from the migration module so the two can never disagree.

Verified by running the full suite twice consecutively without `--create-db`:
1132 passing both times.
