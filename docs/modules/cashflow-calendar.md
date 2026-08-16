# Cash Flow Calendar

A day-by-day projection of liquid balance. Answers the question a monthly
summary cannot: **will I go negative before payday, and on which day?**

Month totals routinely look healthy while the balance dips below zero
mid-month, and that dip is what actually costs a user an overdraft fee.

## What it is not

**Projection, not record.** No ledger entry is written and nothing is cached —
a stale forecast is worse than a slow one. Day one is the *actual* liquid
balance; every day after it is inference. That distinction is the reason the
calendar can be trusted at all.

## Sources of future movement

| Source | What it contributes |
|---|---|
| `IncomeSource` | Salary and other dated income from /income, at the full payment on the payday. Sources already linked to a posting template are skipped so they are not counted twice. |
| `RecurringTransaction` | Subscriptions, loan payments, standing transfers, and income captured as a posting template |
| `Bill` | Unpaid and overdue bills, plus projected future occurrences of recurring ones |
| Liquid balances | The starting point |

Recurring occurrences are expanded with `nth_occurrence` against the original
anchor, never by repeated increments, so a "31st of the month" schedule doesn't
drift to the 28th after one short month.

A recurring **bill** only spawns its successor when paid, so the stored row
covers just the next instance. Projecting the rest from `recurrence_frequency`
is what stops the calendar showing rent once and implying three rent-free
months after it.

Overdue bills are pulled forward to the window start: the money hasn't left
yet, so it still belongs in the projection. Dropping it would overstate the
balance.

## Two non-negotiable disciplines

**Single currency.** Like `net_worth` and `cashflow_statement`, this refuses to
sum across currencies. It projects the dominant liquid currency and names it in
the response, so the UI can be honest rather than silently adding euros to
dollars.

**Internal transfers net to zero.** Moving money from checking to savings does
not change how much cash you hold. Counting it would manufacture a fake dip
and, worse, a fake overdraft warning — the most damaging thing this feature
could do, because it would train users to ignore the real ones. Only the leg
that crosses the boundary of the projected set counts, which correctly captures
a standing payment to an external credit card.

## Guardrails

- Default horizon 60 days; hard ceiling 365. Beyond a year a projection built
  from today's schedule is fiction.
- Max 400 occurrences expanded per template, so a daily schedule can't produce
  an unbounded series.
- Returns `None` (HTTP 204) when the workspace holds no liquid account. An empty
  calendar would imply a zero balance, which is a claim rather than an absence.

## API

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/finance/cashflow-calendar/` | `?start=&days=&currency=`. 204 when nothing to project. |
| `GET` | `/api/v1/finance/cashflow-calendar/{YYYY-MM-DD}/` | One day's detail. 404 for past days. |

`days` is validated at the serializer (1–365) so an absurd window is a clear 400
rather than a silently different result.

Past days return 404 by design: the past is record, not projection, and callers
should read the ledger.

## UI

Three views over one dataset — **month**, **week**, **timeline** — with a day
detail modal on click.

Two independent visual channels, and neither is ever the sole carrier of
meaning:

- **colour** → severity of the projected closing balance
- **icon** → the kind of movement

Every cell also shows the balance as text and exposes a full sentence to
assistive tech. Under `prefers-contrast: more`, tints are dropped and severity
falls back to heavier borders plus the always-present text.

Severity has a deliberate `low` band below 10% of the opening balance. The day
the balance gets *thin* is more actionable than the day it goes negative — by
then there's no time to move money.

Cells show the projected **closing** balance rather than the day's net movement,
because the running balance is what determines whether a payment clears.

On phones the grid keeps its week shape (a calendar without one isn't a
calendar) but drops to the day number and severity tint, with figures one tap
away.

## Testing

`tests/test_cashflow_calendar.py` — 25 tests. The ones that matter most guard
against *manufactured* figures:

- an internal transfer must not appear at all;
- a transfer leaving the projected set must;
- ordering decides the overdraft — the same two movements are safe or unsafe
  depending on which lands first;
- the trough is reported even when the window ends healthy.

`calendarUtils.test.ts` (12) — grid padding uses `null` rather than a fabricated
day, local-midnight date parsing (UTC parsing would shift the grid a column
west of Greenwich), and severity banding.

`CashflowCalendar.test.tsx` (8) — including that a negative balance keeps its
minus sign in the accessible name.

## A bug this feature surfaced

`formatAmount()` returns the *magnitude*: the `Money` component renders
direction as a separate visual treatment. That makes it wrong for standalone
text, where dropping the sign turns a projected overdraft of −$200 into a
comfortable "$200.00" — in both the cell text and the screen-reader label.

`formatAmountSigned()` was added for standalone-text use. Anywhere an amount is
rendered outside `<Money>`, it should be used instead.

An audit for the same defect elsewhere found one more: the analytics cash-flow
chart plots a **Net** line straight from `net_minor`, which is negative in any
month the user overspent — so its tooltip rendered a £450 shortfall as a
comfortable "£450.00". Fixed, and `lib/money.test.ts` now pins the contract
between the two formatters so the whole class of bug can't return silently.

Category and goal-projection tooltips were checked and are safe: both plot
magnitudes that cannot go negative.
