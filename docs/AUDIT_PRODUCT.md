# LedgerFlow — Product Review

**Method.** Inventoried the shipped surface first — 202 API endpoints, 31 pages,
21 modules — then looked for what a user would reach for and not find. Several
gaps I expected to report turned out to be built already; those corrections are
in §5, because a review that recommends work you have finished is worse than no
review.

**Headline.** This is a more complete product than the pre-launch stage
suggests. The gaps are not missing *features* so much as three missing
**connections**: to the user's bank, to the user's inbox, and to the user's
first five minutes.

---

## 1. Priority summary

| # | Gap | Category | Impact |
|---|---|---|---|
| G-1 | No bank aggregation — import is manual CSV only | Workflow | **Highest.** Determines whether the product gets used weekly or abandoned |
| G-2 | Statement reconciliation scaffolded but unreachable | Workflow | **Built** |
| G-3 | Notifications never leave the app | Notifications | **Built** |
| G-4 | No onboarding for a deep product | QoL | High. 18 reports and 6 debt tools nobody is shown |
| G-5 | No UI language support, despite the stated principle | i18n | Medium-high if launching outside en-* |
| G-6 | Household audit history written but unreadable | User mgmt | **Built** |
| G-7 | No scheduled/emailed reports | Reporting | **Built** |
| G-8 | Saved views exist for operators, not customers | QoL | Low-medium |

---

## 2. The three that matter

### G-1 — Bank aggregation

CSV import exists and is genuinely well built: idempotent on
`(account, external_id)` with a content-hash fallback, posts through the same
`record_expense`/`record_income` path as manual entry so the ledger stays
authoritative, and returns per-row errors while still importing valid rows.
`Transaction.external_id`, the unique constraint and `TransactionSource.IMPORTED`
were all put in place for aggregation as well as CSV — the module docstring says
so explicitly.

So the scaffolding is deliberate and correct. What is missing is the connection.

This is the difference between a product someone opens weekly and one they
abandon in week three. Everything downstream — budgets, the anomaly detector,
cash runway, the health score, all 18 reports — is only as good as how current
the transaction data is, and manual CSV export from a bank is a chore people do
twice and then stop. **Every feature in this product is downstream of this one
gap.**

Regionally it is not one integration but a portfolio: Plaid or Teller for North
America, TrueLayer or GoCardless for the UK/EU, and — given the M-PESA support
already in billing and the Nairobi-shaped defaults in the seed data — Kenyan
bank feeds or M-PESA statement ingestion, which no aggregator covers well.

The honest recommendation is to start with **one** aggregator against the
existing `IMPORTED` path, prove the reconciliation loop end to end, and only
then widen. The model layer is ready; the work is provider integration, token
storage, and a sync scheduler.

### G-2 — Reconciliation is unreachable

`TransactionStatus` declares four states:

```python
PENDING    = "pending"     # observed (bank feed) but not cleared
POSTED     = "posted"      # written to the ledger
RECONCILED = "reconciled"
VOID       = "void"
```

`RECONCILED` is **read** in two places — `finance/selectors.py` and
`budgeting/selectors.py` both count it alongside `POSTED` — and **written
nowhere**. No service sets it, no endpoint exposes it. The state is unreachable.

That is a half-built feature rather than an absent one, which is a more
interesting problem: the design anticipated reconciliation, the selectors
respect it, and the transition was never built.

It matters because reconciliation is the trust ritual of a ledger product.
"Tick off what actually cleared against my statement, and tell me the
difference" is how a user comes to believe the numbers. Without it, LedgerFlow
shows a balance the user has no way to *confirm* — and a personal finance app
that cannot be confirmed gets checked against the bank's app instead, at which
point the bank's app is the product.

The build is small relative to its value: a status transition, a per-account
reconcile screen showing cleared vs uncleared against an entered statement
balance, and a difference figure that must reach zero. It pairs naturally with
G-1, since a bank feed is what makes `PENDING` meaningful.

### G-3 — Notifications never leave the app

Nine notification kinds exist and are well chosen: budget threshold, budget
exceeded, low balance, large transaction, anomaly, bill due, bill overdue, goal
achieved, goal milestone. Delivery is in-app plus Web Push, with
`delivered_channels` on the model and a comment stating that other channels are
future work.

The consequence: **"your electricity bill is due tomorrow" only reaches someone
who has already opened the app.** That inverts the purpose. Bill reminders,
low-balance warnings and anomaly alerts are precisely the notifications whose
value is in reaching someone who is *not* thinking about their finances.

Web Push helps but does not close it — desktop push requires the browser
running, and iOS Safari requires the PWA to be installed to the home screen,
which most users never do.

Email delivery is a small build: the fan-out shape already exists, the
`delivered_channels` list is already there, and `send_invitation_email` is a
working pattern to copy. What needs care is the preference surface — per-kind,
per-channel opt-outs — because a finance app that emails too much gets filtered
to spam, taking the bill reminders with it.

---

## 3. By requested category

### Quality-of-life

* **G-4 — no onboarding.** Empty states are unusually good (each carries three
  contextual tips, and they now distinguish "nothing here" from "set up but
  unused" after the investments/debt fix). But there is no first-run flow: no
  account setup wizard, no sample data, no product tour. For a product with 18
  analytics reports, six debt tools, an automation engine and a coach, discovery
  is a genuine problem — most of this will never be found. A five-step setup
  (add an account → import or add transactions → set one budget → set one goal)
  would convert far more of what is already built into value.
* **Undo.** Voiding is correct and reversible by design, but there is no
  general "undo that" for edits, bulk operations or imports. An import that
  lands 400 mis-categorised rows currently has no single reversal.
* **Global search.** A command palette exists for navigation; there is no
  cross-entity search ("find the £340 payment to the plumber in March").
  Transactions accept a `q` filter, but it does not span accounts, bills, goals
  or receipts.

### Workflow

* G-1 and G-2 above.
* **Rules from the UI.** `AutomationRule` and a suggestion queue exist. What is
  missing is the moment of leverage: "always categorise this merchant as
  Groceries" offered *at the point of categorising*, rather than as a separate
  rules screen the user must think to visit.
* **Recurring detection → scheduled transactions.** Recurring transactions and
  bills both exist; a detected recurring pattern promoting itself into a
  scheduled transaction with one confirmation would close the loop.

### Reporting and analytics

Genuinely strong: 18 reports, CSV export on each, cash-flow statement, cash
runway, net worth, health score, cohort-style trends, debt scenarios including
stress tests and consolidation modelling.

* **G-7 — nothing is scheduled.** Every report is pull-only. A monthly summary
  email is the single highest-value addition: it is the mechanism that brings
  people back, and all the computation already exists.
* **No custom report builder.** The 18 are fixed. Users will want "spending at
  X by month for the last two years", and the underlying selectors could
  support a small dimension/measure picker.
* **Tax-year reporting.** Reports are calendar-oriented; a UK or Kenyan user
  wants an April–April or July–June boundary. `default_timezone` and locale
  exist, but the fiscal year does not.

### Notifications

G-3 above. Beyond it: no digest/batching (nine alert types firing individually
will train people to ignore all of them), no per-kind preferences, and no quiet
hours.

### Settings

Six sections: Profile, Security, Preferences, Workspace, Categories & tags, AI
& insights. Missing:

* **Notification preferences are all-or-nothing.** Settings → Preferences has a
  Notifications section, but it contains exactly one control: a master push
  on/off. (The toggle itself is thoughtfully built — it hides when the browser
  cannot support push, and requests permission only on explicit click rather
  than page load.) There is no per-kind control across the nine notification
  types, so a user who finds bill reminders useful but large-transaction alerts
  noisy can only turn everything off. That is the setting people actually reach
  for, and turning everything off is the outcome.
* **Data & privacy** — GDPR export exists at the API but has no settings entry;
  users cannot find it.
* **Connected accounts** — needed by G-1, absent now.
* **Workspace security policy** — an owner cannot require MFA for all members,
  which is the one control a shared financial workspace most wants.

### User management

Roles (Owner/Member/Viewer), invitations, member management and the last-owner
guard are all solid.

* **G-6 — the household cannot see its own history.** Audit writes were added
  for destructive operations, but there is no read endpoint or UI. In a shared
  household this is the question people actually ask: "who deleted that?"
  Exposing the existing rows is the smallest high-value item on this list.
  (Note the isolation constraint recorded in `record()`: the table is
  deliberately not RLS-protected, so any read endpoint **must** filter
  `tenant_id` itself.)
* **No per-account permissions.** Roles are workspace-wide. A household with a
  teenager, or a couple keeping one account private, cannot express that.
* **No pending-invitation visibility** for the invitee before they accept.

### Administration

The platform console is comprehensive — 46 endpoints across tenants, billing,
invoices, refunds, coupons, dunning, analytics, health, audit and RBAC. Gaps
noted in the earlier audit remain: no bulk actions, no CSV/Excel export from
admin tables, invoices cannot be composed by hand, and SMS dunning is modelled
with no provider adapter.

### Automation

Rules, suggestions, anomaly detection, auto-categorisation, recurring detection,
goal auto-contributions and a dunning engine all exist. The stated principle —
*"automation proposes, a person disposes"* — is respected throughout, which is
the right call for money.

The gap is **reach**, not capability: automation currently acts on data the user
has already entered. Paired with G-1 it would act on data arriving continuously,
which is where it earns its keep.

### Accessibility

WCAG 2.1 AA clean across 14 pages after the contrast, keyboard-scroll, skip-link
and tap-target fixes. What automation cannot certify, and nobody has yet done:
a screen-reader pass, focus-management review on modals, and verification that
form errors are announced. Also absent: a reduced-motion audit beyond the one
media query, and any high-contrast mode.

### Internationalisation — G-5

The stated principle is *"Support multiple currencies, languages, time zones and
localization."* Three of four hold:

| | Status |
|---|---|
| Currencies | Full — multi-currency accounts, FX conversion, per-currency MRR |
| Time zones | Per-workspace `default_timezone` |
| Localization | `Intl`-based number/date formatting from `default_locale` |
| **Languages** | **Absent** |

`USE_I18N = True` on the backend, but there are **no translation catalogues, no
frontend i18n library and no locale files**. Every string is hard-coded English.

This is fine for an English-market launch and should be *called that* rather
than described as multi-language. If launching in Kenya — which the M-PESA
integration and seed data suggest — Swahili matters, and retrofitting i18n
across 31 pages costs far more than adopting it before the string count grows
again.

Two backend paths would need attention too: server-composed emails and the
error messages the API returns, which are currently English sentences the UI
displays verbatim.

### Offline

Better than most: a real offline queue with tests, a service worker, a web
manifest, Quick Add and receipt capture designed for mobile. Reasonable next
steps are read-caching of recent transactions and balances for genuinely offline
viewing, and a visible sync state so a user knows what has not yet reached the
server.

---

## 3b. Delivered since this review

| Gap | What shipped |
|---|---|
| G-3 | Email channel with opt-in defaults, a curated `EMAIL_WORTHY` subset, per-kind preferences UI, and `delivered_channels` recorded after send |
| G-7 | Monthly summary email on a beat schedule (08:00 on the 1st) |
| G-6 | `GET /tenancy/workspaces/activity/` — labelled entries, bulk-resolved actor names, MEMBER-and-above, explicit `tenant_id` scoping |
| G-2 | `RECONCILED` is now reachable: batch mark/unmark, a difference figure driven to zero, voided rows refused, uncleared list oldest-first |

Two defects surfaced while building, both caught by the new tests:

* **Batch reconciliation 500'd.** `AuditLog.target_id` was non-nullable, so an
  action spanning many rows could not be recorded. Made nullable — "one
  decision over fifty transactions" is a legitimate shape, and writing fifty
  audit rows would bury the entries that name a single object. The platform
  trail already modelled it this way.
* **`record(actor_id=None)` could not express a system action.** It fell
  through to the ambient request actor, so an automation rule firing *during* a
  user's request was attributed to the user — precisely backwards. Fixed with
  an `UNSET` sentinel separating "caller didn't say" from "caller said: nobody".

## 4. Suggested sequence

~~1. G-3 email notifications + G-7 monthly summary.~~ **Done.**
~~3. G-6 audit read.~~ **Done** (API; no UI yet).
~~4. G-2 reconciliation.~~ **Done** (API; no UI yet).

Remaining:

1. **Frontend for G-2 and G-6.** Both ship as APIs with no screen. A
   reconciliation endpoint nobody can reach is the same half-built state the
   gap described, one layer up.
2. **G-4 onboarding.** Converts what is already built into value that gets
   discovered.
3. **G-1 bank aggregation.** The largest build and the one that changes the
   product's category — but sequence it after 4, because reconciliation is what
   makes a feed trustworthy rather than merely noisy.
6. **G-5 i18n** — before the string count grows, if a non-English market is on
   the roadmap.

---

## 5. Gaps I expected and did not find

Recorded because I would have been wrong to report them, and because the list
says something about how complete this is:

CSV import · split transactions · transaction attachments · budget rollover ·
net worth tracking · multi-currency accounts · bulk operations · web push ·
receipt OCR · goal forecasting and recommendations · debt refinance,
consolidation and stress modelling · anomaly detection · cash runway ·
financial health score · GDPR data export · workspace closure · MFA with TOTP,
backup codes and passkeys · OAuth login · dunning · a full platform admin
console.

---

## 6. What this review did not cover

No user research, no analytics on actual usage, no competitive teardown, and no
pricing or packaging analysis. Every judgement about what users "reasonably
expect" is inferred from the product's own domain and stated principles rather
than measured — the single most valuable next input would be watching five
people attempt to set up a workspace unaided.
