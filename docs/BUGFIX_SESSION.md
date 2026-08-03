# Bug fix session — six reports from a running instance

Six concrete issues reported from an actual deployed instance, plus two
backend crash tracebacks. All six fixed; every fix independently verified by
temporarily reverting it and confirming its regression test actually fails,
not just that it passes.

## 1. `/debt` — "this page has no button"

Real. `DebtPage`'s `PageHeader` had no `actions` prop and its `EmptyState`
had no `action` prop — a first-time visitor with no credit card or loan
account on file saw a title, a description, and static tips, with nothing
clickable anywhere on the page. Every analogous empty state elsewhere
(Investments, Goals) has a CTA; this one never did.

Fixed with a button routing to `/accounts`, since debt tracking derives from
credit-card/loan account balances rather than a standalone entry flow.
`DebtPage.test.tsx` — the page had no test file at all before this.

## 2. No AI on/off control at `/settings/intelligence`

The read-only deployment-level config (provider, model, API key) is
deliberate and correctly documented — a workspace member choosing where the
household's data gets sent would be deciding that for everyone else. But
there was genuinely no per-workspace opt-out at all, even a bare on/off
switch independent of *which* provider is configured.

Built end-to-end: `Tenant.ai_enabled` (default `True`, additive — nothing
changes for an existing workspace), gated at the coach's actual call site in
`coach.py` rather than the registry (which is deliberately settings-only and
tenant-agnostic), an admin-only PATCH using the codebase's own `required_role`
property pattern, and a real Switch in `IntelligencePanel`.

Two mistakes caught while building this, both fixed before shipping: a stray
`?? True` (JavaScript syntax in Python), and a first version of the gate test
that would have been a false positive (`.filter().update()` against a tenant
row that didn't exist, with too weak an assertion to prove the LLM path was
actually skipped). Rewritten to patch the registry itself and assert it's
never reached — proven genuine by reverting the gate and confirming the test
fails.

## 3. Duplicate "Add transaction" on the dashboard

Real. `AppShell`'s persistent header carries "Add transaction" on every page.
`DashboardPage`'s own greeting header repeated the identical button pointing
at the identical destination — visible twice at once, specifically on the
one page where AppShell's copy was already there. Removed the dashboard's own
copy; a test pins that the page's own render never reintroduces it.

## 4. Family/Couple workspace type selection "not working"

Real, and the mechanism was interesting: the backend's `TenantType` has only
`personal` / `household` / `organization` — no `couple` or `family` value
exists at all, and nothing in the backend actually branches on the
distinction. Submitting either option hit a clean 400 from DRF's
`ChoiceField` ("couple" is not a valid choice"), surfaced as an unhelpful raw
validation message. From the user's side: pick "Couple," submit, nothing
happens.

Fixed on the frontend only, with a translation applied at submission rather
than by giving two `<option>` elements the same value (which would break
native `<select>` selection — the browser can't tell which of two
identically-valued options a click chose once the bound value re-renders).
"Couple" and "Family" stay genuinely distinct, selectable options in the
picker; both now submit `type: "household"`.

## 5. "Add Security" button non-responsive on `/investments`

Traced to bug 6b below. Before assuming the frontend needed a fix, it was
checked carefully: `SecurityModal` already caught `ApiError` and rendered a
banner, and `client.ts` already fell back to `.text()` for non-JSON
responses (a raw Django DEBUG error page) rather than crashing on a failed
`.json()` parse. So this was never literally frozen — the banner would have
shown a generic **"Request failed."**, which is unhelpful but not silent. No
frontend change was needed; the fix is entirely in the service layer (6b),
after which the same banner shows a specific, actionable message instead.

## 6. Backend crash tracebacks

### 6a — `KeyError: 'due_label'`

Deeper than a missing key. The recommender proposed a `"schedule_transfer"`
action referencing `from_account_id` / `to_account_id` / `on_date` — none of
which `Bill` has model support for (it's settled against a Payee, not
transferred between two of the user's own accounts) and none of which the
frontend ever read; it always just linked to `/bills` regardless. A comment
already in the codebase confirmed `context.upcoming_bills` was "previously
always empty," so this whole branch had never run against real data before.

Fixed: the selector now computes a real `due_label` and carries the bill's
own id; the recommender proposes only `{"action": "bill_upcoming", "bill_id":
...}`, which is what the frontend already correctly routes. Regression tests
go through the real selector — the exact path that had never been exercised.

### 6b — `IntegrityError: duplicate key value violates unique constraint`

`create_security()` did a bare `.create()` with no duplicate check.
`Security.save()` uppercases and strips the symbol, so "vti" typed after
"VTI" already exists collides at the database constraint even though they
looked different as typed — a completely plausible real scenario, and worse,
exactly what a user re-clicking a button that *looked* unresponsive would
trigger on their retry.

Fixed with a pre-check for a clear message plus an atomic `IntegrityError`
backstop for the race the pre-check alone can't close (two concurrent
submissions of a genuinely new symbol could both pass the check before
either commits). The view already caught `InvestmentError` and returned a
proper 422 — confirmed, not assumed. Tested at both the service and API
layers, including the case-only-collision and repeat-submission scenarios.

## Testing discipline used throughout

Every fix in this session was verified the same way: after writing the test,
the underlying fix was temporarily reverted and the test was run again to
confirm it actually fails — then the fix was restored and the test rerun to
confirm it passes. A test that only ever passes proves nothing about whether
it would have caught the bug it claims to guard against; several of the
tests here would have been false positives without this step, and two were
rewritten after catching that in themselves.

## Final state

902 backend tests, 579 frontend tests, tsc clean, lint clean (1 pre-existing
warning, unrelated to this session), build green.
