# LedgerFlow — Pre-Launch Production Audit

**Scope:** full stack — 202 API endpoints, 38 frontend routes, 21 Django apps,
customer app + platform console.
**Method:** static analysis, live API probing, axe-core WCAG scanning, and
Playwright against a running stack with seeded data. Every finding below was
reproduced; nothing is inferred from reading code alone.

**Status: all functional findings resolved.** The verdict below was written
before the fixes; it is left intact as the record of what was found.

**Original verdict: not ready for public launch.** One issue (F-1) breaks a shipped
feature for every user. Two more (F-2, F-3) are dead ends users will hit within
minutes. The engineering foundation underneath is unusually strong — see
§6 — so the gap is narrow, but it is real.

---

## Severity summary

| ID | Severity | Area | Issue | Status |
|---|---|---|---|---|
| F-1 | **Blocker** | Functional | Every CSV/PDF export returns 401 | **Fixed** |
| F-2 | **High** | Functional | Securities cannot be edited or deleted | **Fixed** |
| F-3 | **High** | Functional | Tags cannot be edited or deleted | **Fixed** |
| A-1 | **High** | Accessibility | Money cents below WCAG AA contrast | **Fixed** |
| A-2 | **High** | Accessibility | Scrollable tables keyboard-inaccessible | **Fixed** |
| A-3 | Medium | Accessibility | Tertiary text fails AA on tinted rows | **Fixed** |
| A-4 | Medium | Accessibility | Admin console had no skip link | **Fixed** |
| U-1 | Low | UX | Sub-24px auth links (not "every page") | **Fixed** |
| P-1 | Medium | Product | No in-app onboarding | Open |
| P-2 | Medium | Product | Invoices cannot be composed by hand | Open |
| P-3 | Low | Product | SMS dunning modelled, no adapter | Open |

---

## 1. Functional review

### F-1 — BLOCKER: every export link returns 401

Both export surfaces build a bare URL consumed by `<a href download>`:

```ts
// src/api/debt.ts:120  and  src/api/reports.ts:29
exportUrl: (…) => `/api/v1/debt/debts/payoff/export/?…`
```

A plain anchor sends **no `Authorization` header and no `X-Tenant-ID`**. Both
endpoints extend `TenantScopedAPIView` with `IsTenantMember`, so both reject it.

Reproduced against the running API:

```
What a plain <a href> sends (no headers at all):
   401  /api/v1/debt/debts/payoff/export/?strategy=avalanche
   401  /api/v1/analytics/reports/<slug>/export/

With the headers the API actually requires:
   204  /api/v1/debt/debts/payoff/export/     (204 = no debt for this tenant)
```

There is a second, independent failure in the same line. The URL is
origin-relative and `vite.config.ts` explicitly configures **no dev proxy**
("no proxy needed because the backend enables CORS"). So in development the
link resolves against `localhost:5173`, Vite returns `index.html`, and the user
downloads an HTML file named after the report. In production Caddy serves one
origin so the path reaches Django — and then 401s.

**Blast radius:** the debt payoff export and all 18 analytics reports. Every
export control in the customer app.

**Fix:** use the authenticated `getBlob()` helper that already exists in
`src/api/client.ts` and is already used correctly by the admin invoice PDF
download — fetch the blob, `URL.createObjectURL`, click a synthetic anchor,
revoke. Roughly 15 lines, already written once in `useDownloadInvoice`.

This is worth dwelling on: the correct pattern exists in the codebase and is
tested. The customer-facing exports predate it and were never migrated. That is
the shape of most of what follows — not carelessness, but two eras of code
where the newer convention never propagated backwards.

### F-2 / F-3 — HIGH: create-only resources

Probed live:

```
SECURITY   PATCH 404   DELETE 404
TAG        POST 201    PATCH 404   DELETE 404
```

Neither `investments/securities/` nor `finance/tags/` has a detail route. Both
can be created and never corrected.

F-2 compounds the bug reported from production. `create_security` enforces a
case-insensitive uniqueness check with the message *"BONDKEDDD is already
tracked in this workspace."* So a user who fat-fingers a ticker gets a
permanent, unfixable, undeletable row that also blocks re-creating the correct
symbol if the typo collides. There is no escape except database access.

F-3 is milder but unbounded: tag lists only ever grow, and a misspelled tag is
forever.

**Fix:** `SecurityDetailView` and `TagDetailView` with PATCH + soft DELETE.
Both models already inherit `SoftDeleteModel`, and both unique constraints are
already scoped to live rows — so delete-then-recreate will work correctly the
moment the endpoint exists. The data layer is ready; only the API surface is
missing.

### Clean results

Everything else in the functional sweep came back clean, and the negative
results are worth recording:

- **Zero** `TODO`/`FIXME`/`NotImplemented` in 21 backend apps or the frontend.
  (The `placeholder` hits are legitimate domain vocabulary — "placeholder
  category" is a real concept in the automation engine.)
- **Zero** dead buttons (`onClick={() => {}}`, `href="#"`) outside the
  intentional component showcase.
- **Zero** dead links: every navigation target resolves to a declared route.
- **Zero** orphan pages: every route is reachable from nav, the command
  palette, or an email link (`/invite`, `/reset-password`, `/auth/callback`).
- **Zero** frontend calls to non-existent endpoints (152 call paths against 202
  routes).
- **No CRUD gaps on primary resources.** Four detail views lack DELETE —
  transactions, invoices, tenants, receipts — and all four are *correct*:
  they expose `void`, `void`, `close` and `discard` respectively. Never hard-
  deleting a posted financial record is the right invariant for a
  double-entry ledger, and the codebase holds it consistently.

---

## 2. Accessibility review

Audited with axe-core (WCAG 2.1 A + AA) across 14 pages, both shells.

**First run: 2 serious violations. Both fixed. Re-run: clean across all 14.**

Automated tooling catches roughly a third of WCAG criteria. A clean axe run is
a floor, not a certificate — see §5 for what still needs a human.

### A-1 — Money amounts below contrast minimum (fixed)

`.lf-amount-cents` de-emphasised minor units with `opacity: 0.62`. Measured
against the real tokens:

| Colour | Full | At 0.62 | Required |
|---|---|---|---|
| `verdant-600` (income) | 5.29:1 | **2.86:1** | 4.5:1 |
| `ink-900` (spending) | 17.48:1 | **4.49:1** | 4.5:1 |
| `ink-500` (transfer) | 5.23:1 | **3.83:1** | 4.5:1 |

Income cents were at 2.86:1 — roughly *half* the required contrast, on the
`Money` component used in 39 files. This affected essentially every number in
the product.

My first attempt raised the alpha to 0.85 and axe still failed. The reason is
the finding: **two of the three money colours have under 1.0 of contrast
headroom**, so no alpha low enough to read as de-emphasis can also clear AA.
Opacity was structurally the wrong instrument. The fix removes it entirely and
lets the existing `font-size: 0.85em` carry the de-emphasis — which costs no
contrast at all.

> Worth flagging honestly: my initial calculation used a *guessed* hex for
> verdant rather than reading the token, and reported 4.65:1 where the true
> value was 3.98:1. The browser caught what my arithmetic got wrong. Compute
> from the real token, then verify in the engine.

### A-2 — Scrollable tables not keyboard-accessible (fixed)

`.lf-table-wrap--sticky` sets `overflow: auto; max-height: min(72vh, 780px)`,
creating a scroll container reachable only with a pointer. WCAG 2.1.1. Applies
to all 11 sticky tables; axe flagged only `/admin/billing` because that was the
one page where content actually overflowed at test width — the other ten are
latent.

Fixed in `Table.tsx`: `tabIndex={0}` + `role="region"` + an accessible name
drawn from the existing caption, applied only when `stickyHeader` is set (a
non-scrolling table with a tab stop is just a focus trap for nothing).

### A-3 — Tertiary text on tinted rows (fixed)

`--lf-ink-400` (#656c81) measured 4.33:1 against the selected-row tint
(#e8e8fb). Darkened to #5f6679 → 4.74:1 on tint, 5.73:1 on plain surface.

### A-4 — Admin console had no skip link (fixed)

`AppShell` has `<a class="lf-skip-link" href="#main">`. `AdminShell` had
`<main id="main">` but no skip link — so an operator navigating by keyboard
tabbed through the entire 12-item rail on every page load. WCAG 2.4.1. This was
a defect in code written for this project, caught by comparing the two shells.

### Passing

- **Keyboard focus indicators** present on first tab stop.
- **Landmarks and labels** clean on all 14 pages.
- **Dark mode** verified visually and by contrast maths — all money colours
  clear AA in both themes after the A-1 fix.

---

## 3. Responsive and mobile

Tested at 390×844 (iPhone-class) across 8 pages, both shells.

- **Zero horizontal overflow.** No page exceeds the viewport width — including
  the data-dense transaction and tenant tables, which fall back to the
  responsive card layout.
- The admin rail correctly collapses to a horizontal icon bar under 900px.

### U-1 — sub-24px tap targets (fixed, and the original report was wrong)

Root-caused in the browser: the two 15px anchors are **"Forgot password?" and
"Create an account" on the login screen** — bare inline links whose hit area is
the text box itself, under the 24×24 CSS px floor of WCAG 2.5.8.

The original claim that they appeared "on every page in both shells" was an
artifact: the Django server was down during that run, so authentication failed
and the harness measured the login screen every time. A detector that cannot
tell you which page it is actually looking at will report the same finding
everywhere.

Fixed with `display: inline-block; min-height: 24px; padding-block` on
`.lf-auth-shell a` — padding rather than a larger font, since these are
deliberately secondary to the submit button. Verified: no sub-24px controls
remain.

---

## 4. Security

No findings. Specifically verified:

- **No hardcoded secrets.** Every credential reads from the environment.
- `DEBUG` defaults from env; `production.py` pins `DEBUG = False`.
- **No dangerous constructs**: no `eval`, `exec`, `pickle.loads`, `shell=True`,
  `mark_safe`, or raw SQL.
- **Every one of 202 endpoints** declares or inherits a permission class. No
  accidentally-public route.
- RLS is fail-closed on tenant tables; the platform console operates on the
  control plane and structurally cannot read household financial data without
  an audited impersonation grant.
- Platform secrets are write-only through the API — the settings endpoint
  reports whether a credential is set and which layer supplied it, never its
  value. Confirmed in the browser: no secret reaches the DOM.

Note that F-1's 401 is the *auth layer working correctly*. The bug is the
client, not the boundary.

---

## 5. What this audit did *not* cover

Stating the limits, because an audit that implies completeness it does not have
is worse than a short one:

- **Automated a11y ≈ 30% of WCAG.** Not covered: whether heading hierarchy is
  logical, whether error messages are announced to screen readers, whether
  modals trap focus and restore it on close, whether the command palette is
  operable without a mouse. All need manual testing with an actual screen
  reader.
- **No load or performance testing.** No p95 latency figures, no N+1 profiling
  under realistic data volume. The tenant directory has an explicit
  fixed-query-count test; nothing else does.
- **No penetration testing.** The security section is a static review, not an
  adversarial one. No IDOR probing, no CSRF/session-fixation testing, no
  dependency CVE scan.
- **No cross-browser testing.** Chromium only. No Safari, Firefox, or real iOS.
- **Import/export, file upload, and notification delivery** were reviewed at
  the route level but not exercised end to end.
- **Email rendering** untested across clients.
- **Onboarding, empty and error states** were observed incidentally, not
  systematically walked.

---

## 6. What is genuinely strong

Worth recording, because it changes what the remaining work costs:

- **Financial correctness is enforced structurally, not by convention.**
  Money is integer minor units everywhere. Ledger entries and audit rows are
  append-only via database triggers, not application discipline. Tenant
  isolation is fail-closed RLS. Unique constraints are scoped to live rows.
- **The service layer is genuinely testable and tested.** 1,168 backend and
  636 frontend tests, passing twice consecutively against a reused database.
- **Design tokens are real.** Dark mode and the entire admin console inherit
  correctly from one token set — which is *why* A-1 and A-3 were single-line
  fixes rather than a sweep through 39 files.
- **The API contract is coherent.** Zero drift between 152 frontend call paths
  and 202 backend routes.

The defects found are almost all **surface-level and localised**. None of them
indicate an architectural problem, and none require redesign.

---

## 7. Recommended order before launch

1. **F-1** — export downloads. Blocker; the correct helper already exists.
2. **F-2 / F-3** — security and tag detail endpoints. Both data layers are
   already soft-delete ready.
3. **U-1** — identify the second small anchor.
4. Manual screen-reader pass over the top 5 flows.
5. Dependency CVE scan and a basic load test.

Items 1–3 are a day's work. Items 4–5 are the ones I would not skip, and are
exactly the ones automation cannot do for you.
