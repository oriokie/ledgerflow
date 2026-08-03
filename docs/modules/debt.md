# `debt` — Debt Planner

Closes the last gap named in the product audit: `AccountType.LOAN` and
`CREDIT_CARD` existed, but with no interest rate or minimum payment anywhere,
so the coach's debt insight had to order debts by *size* rather than by what
they cost.

## What this app stores, and what it doesn't

A liability's **balance** is already in the ledger, posted by real transactions.
What the ledger has no opinion about is the **terms** — the rate, the minimum,
the due day. Those aren't financial events, they're the contract.

So `DebtProfile` stores terms and nothing else:

- **It never posts a journal entry.** Recording a 24% APR doesn't move money.
- **It never stores a balance.** That would be a second source of truth for the
  one number that has to reconcile.

Payoff plans are projections, computed on demand — the same discipline as the
cash-flow calendar. A stored plan is a plan that goes stale the moment a
payment posts.

### Why `debt_kind` rather than new account types

`AccountType` drives the ledger's asset/liability split. Adding mortgage,
student loan, vehicle loan and BNPL as account types would ripple through net
worth, cash flow, and every selector that partitions accounts. To the ledger
they are all liabilities and differ only in their terms — which is exactly what
`DebtProfile` is for.

Supported kinds: credit card, mortgage, personal loan, student loan, vehicle
loan, BNPL, other.

## The payoff engine

`payoff.py` is pure arithmetic with no ORM, so the maths is directly testable
and a what-if costs nothing but a function call.

### The rollover is the whole mechanic

The monthly budget stays constant; what changes is how it's split. Every debt
gets its minimum, the remainder goes to one target, and when that target clears
its minimum joins the pool for the next. Payments accelerate without the user
finding another penny — which is the entire insight snowball and avalanche are
selling.

### Two details that are easy to get wrong

**Interest is charged before payment is applied, and payment covers interest
first.** Subtracting the payment and *then* charging interest understates payoff
time by months on a real balance. The order here matches how lenders post.

**A minimum below the monthly interest never pays anything off.** The balance
grows regardless, and a naive loop runs forever. The simulator detects it — if
total owed didn't fall this month it never will, since the budget is constant
and the ordering deterministic — and reports it. "This debt never clears at this
payment" is real, common, and genuinely actionable.

## Strategies

| Strategy | Optimises | Cost |
|---|---|---|
| Avalanche | Total interest | Always the cheapest |
| Snowball | Time to first clearance | Slightly more interest |
| Custom | The user's own order | Whatever they choose |

Presented as a **comparison**, not a recommendation with a winner. Avalanche
always wins on interest and snowball often clears a first debt sooner, and which
matters more is a judgement about the person, not the arithmetic — a plan
abandoned in month four saves nothing at all.

Savings are measured against **minimums only**, which is what happens if the
user changes nothing. Comparing strategies against each other would flatter
whichever was listed second.

`debt_recommendation()` suggests avalanche when it saves more than **5% of the
interest bill**, snowball otherwise. A share rather than a flat amount: a fixed
threshold dismisses a real saving on a small debt and over-weights a trivial one
on a mortgage.

## Alerts

Deliberately few — a dashboard that flags everything gets closed.

1. **Critical:** a debt growing despite on-time payments. The most serious thing
   that can be true of a debt.
2. **Warning:** the annual interest cost. Monthly interest is easy to shrug off;
   the annual figure is the same fact stated so it registers.
3. **Info:** debts missing terms, so they can't be planned around yet.

## Integrations

**Coach.** The debt insight now ranks by rate and quotes the monthly interest,
because rates finally exist. Its rationale previously said they weren't tracked —
that sentence is gone.

**Cash flow.** `committed_monthly_minor()` exposes total minimums as committed
outflow. It is deliberately **not** auto-injected into the cash-flow calendar:
a user with both a debt profile and a recurring transaction for the same payment
would be double-counted, and a false overdraft warning is the worst thing this
product can produce.

**Goals.** A `debt_payoff` goal kind already exists; the planner's figures give
it a target that is derived rather than guessed.

## API

| Method | Path |
|---|---|
| `GET` | `/api/v1/debt/debts/` |
| `GET` | `/api/v1/debt/debts/summary/` — 204 when nothing is owed |
| `GET` | `/api/v1/debt/debts/payoff/?strategy=&extra_monthly_minor=&months=` |
| `GET` | `/api/v1/debt/debts/extra-payment-curve/` |
| `PUT`/`DELETE` | `/api/v1/debt/debts/{account_id}/terms/` |

## UI

`/debt` — summary and alerts, then strategy comparison with a live extra-payment
field, then the month-by-month schedule, then the debts themselves.

The payment schedule splits every payment into **interest and principal**. That
split is the whole story of a debt: seeing that £180 of a £200 payment went to
interest explains a balance that has barely moved far better than any summary.

## Testing

`tests/test_debt_payoff.py` — 52 tests. The engine tests run without a database
and pin the cases a naive implementation gets wrong: interest ordering, the
rollover, the final payment settling exactly, and the never-clears detection.

Two bugs were found by these tests during development:

1. **Stuck detection never fired for a single debt.** The original condition
   excluded the target debt, so a lone underwater debt ran to the 480-month cap
   instead of being reported. Replaced with a simpler check — if the total owed
   didn't fall this month it never will — which is both correct and obviously so.

2. **Clearing terms was a one-way door.** `DebtProfile` is soft-deletable, so
   `clear_debt_terms` left a row the alive-only manager couldn't see. Re-adding
   terms then collided with the one-to-one constraint, and the selector kept
   reading the deleted profile through `select_related`. Both fixed, and a test
   now covers the clear/re-add cycle.

## Debt intelligence (extension)

Layered onto the original planner without changing any of its architecture:
`payoff.py` is still pure, no balances are duplicated, no schedules persisted,
and every pre-existing API response keeps its shape.

### Rate timelines subsume promotional rates

Variable rates and intro offers are **one mechanism, not two**. A promotional
rate is simply the first period in a schedule whose second period is the
standard rate, so a 0%-for-18-months card, a tracker mortgage and a fixed loan
all run through one code path.

`DebtRateHistory` is append-only by intent: recording a change never edits an
earlier entry, so a projection run last March still uses the rate in force
then. Future-dated entries are the point — a lender notifying a rise in three
months lets the plan account for it now.

The legacy `promotional_apr` fields are translated into a schedule at read
time, so existing data keeps working with no migration.

**A schedule describing only future changes falls back to the fixed rate**, not
to zero. A partial timeline degrading to a 0% projection would understate every
figure that depends on it.

### Compounding

Every frequency collapses to an equivalent monthly rate via
`(1 + r/n)^(n/12) − 1`, with continuous as the limit `e^(r/12) − 1`. That is
what keeps the month-stepping loop ignorant of compounding entirely — adding a
frequency is one line, not a change to the schedule logic.

The ordering `annual < monthly < weekly < daily < continuous` is a mathematical
fact and is pinned as an invariant: if it ever fails, a conversion has broken.

### Fees

Capitalised onto the balance rather than paid alongside, which is how a card
annual fee actually behaves — charged *to* the card, then itself accruing
interest. Tracked separately from interest throughout, so a low-rate card with
a high annual fee cannot look cheap.

An annual fee lands in a single nominated month rather than being spread;
smoothing it would hide a £150 hit behind a £12.50 average.

### Offsets

Interest is charged on `balance − offset`, clamped at zero. **Neither balance
moves** — offsetting is an arrangement with the lender about how interest is
computed, not a transfer, so nothing posts to the ledger.

Only positive balances count: an overdrawn account contributing a negative
would *increase* the interest charged. Only asset accounts qualify, and only in
the debt's own currency.

### Refinance and consolidation

Simulation only. Both take frozen inputs and return projections; neither
touches a stored debt.

**Refinance reports a breakeven month**, because that is the number that
actually decides it. A lower rate always flatters the total-interest figure,
but closing costs are paid up front — a deal that saves money over twenty years
can cost money over three, and if the user expects to move or repay before
breakeven the saving never arrives.

**Consolidation is judged on lifetime cost, never the monthly payment.**
Consolidation almost always lowers the monthly figure — that is its selling
point — but stretching the term can raise the total even at a lower rate. There
is a test for precisely that trap.

### Flexible extra payments

Real repayment money is lumpy: a bonus in March, a refund in July, a raise from
month nine. `ExtraPayments` carries a baseline, one-off lump sums, and step-ups
that persist from their month onward.

The **most recent** step-up wins, not the largest — a later reduction is as real
as a later increase, and taking the maximum would quietly ignore someone telling
us their circumstances worsened.

A constant monthly extra is normalised into the same structure, so there is one
code path rather than two. A future lump sum also suppresses the never-clears
verdict, since a debt that stalls now but is rescued in month six does clear.

### Debt Stress Score

0–100, **higher is better**, matching the financial health score. Inverting one
relative to the other would be a persistent source of misreading.

Components: debt-to-income (0.25), payments-vs-income (0.20), interest burden
(0.20), utilisation (0.15), average APR (0.10), payoff duration (0.10).

**Missing inputs are excluded, never defaulted.** Someone who hasn't recorded
their income is not scored as if they earn nothing — that would produce an
alarming figure derived entirely from an absence. Remaining weights are
renormalised and `coverage` reports how much was measurable, with
`is_provisional` set below 50%.

**Missed payments are a flat penalty, not a weighted component.** They are
categorically different from an unflattering ratio — they carry fees and mark a
credit file — and averaging that against a good utilisation figure would let a
real problem hide behind an unrelated strength. Capped at 25 points.

`explain()` returns every component, its contribution and a sentence saying
why, weakest first, because that is where an improvement moves the total most.

### Debt signals — one analysis, two surfaces

`debt_signals()` produces every observation the module has: promotional
expiries with a countdown, notified rate rises, fee-heavy products, offset
opportunities, the most expensive borrowing, and repayment milestones.

Both the **coach** and the **debt dashboard alerts** read from it. The coach
adapts signals into insights rather than recomputing them, so the two surfaces
can never disagree about the same debt — which is what would happen if each
derived its own view of a rate timeline.

Wording is deliberately careful where the data doesn't support a stronger
claim. The refinance signal says *where the cost is concentrated*; it does not
say a better product is available, because we hold no rate data to support
that. The offset signal notes the money stays available, since that is what
makes offsetting attractive and what people misunderstand about it.

Milestones exist because a planner that only ever reports problems is one
people stop opening — but they are measured against the recorded original
principal, never invented encouragement.

### Analytics

`debt_analytics()` derives every series from **one** simulation. Running the
simulator per chart would be slower and capable of disagreeing with itself.

The payment-split chart stacks principal, interest and fees rather than showing
one payment bar. That split is the point: early payments are mostly interest,
and watching the principal band grow explains the rollover better than any
figure. Green reduces what you owe; red and amber don't, and the caption says
so rather than leaving it to the colours.

**Monthly velocity is the first month's principal**, not an average over the
plan. Averaging would flatter it, since the rollover accelerates later — the
honest answer to "how fast is this actually falling?" is what's happening now.

CSV export writes **major units with two decimals**. A spreadsheet is where
this is going, and a column of minor-unit integers is a trap for anyone who
sums it.

### Simulator UI

Refinance and consolidation both had complete, tested backends and **no way for
a user to reach them** — the same "needs a UI control" gap that hid compounding
and fees. Both now have modals.

Each states plainly that nothing is changed. "Record a refinance" could
reasonably be read as applying one, and a simulator that looks like an action
is a genuinely dangerous ambiguity in a financial product.

**Refinance leads with breakeven, not the lifetime saving.** A lower rate
always flatters the total-interest figure, but closing costs are paid up front.
The copy goes further and says it outright: *"if you expect to repay or move
before month 14, switching costs you money."*

**Consolidation shows monthly and total side by side**, and when a lower
payment costs more overall it names the trap rather than leaving the user to
spot it: *"a smaller monthly payment over a longer term can cost more in total,
even at a lower rate."* That is the exact mechanism consolidation advertising
relies on.

### PDF export

A document rather than a data dump: it leads with the summary that makes the
table meaningful — strategy, budget, debt-free date, total interest — then the
month-by-month schedule with repeating headers across pages.

A plan that never clears renders a plain statement at the top rather than
raising, because that user most needs the document.

`reportlab` was importable in the development environment but **absent from
`requirements/base.txt`**. Relying on a transitive dependency is how a deploy
breaks on a clean build, so it is now declared explicitly.

### New API

| Method | Path |
|---|---|
| `GET`/`POST` | `/api/v1/debt/debts/{id}/rates/` |
| `PUT` | `/api/v1/debt/debts/{id}/offsets/` |
| `POST` | `/api/v1/debt/debts/{id}/refinance/` |
| `POST` | `/api/v1/debt/debts/consolidate/` |
| `POST` | `/api/v1/debt/debts/scenarios/` |
| `GET` | `/api/v1/debt/debts/stress/` |
| `GET` | `/api/v1/debt/debts/borrowing-cost/` |
| `GET` | `/api/v1/debt/debts/analytics/` |
| `GET` | `/api/v1/debt/debts/payoff/export/` — CSV |
| `GET` | `/api/v1/debt/debts/payoff/export.pdf` — PDF |

Every original endpoint keeps its existing shape; a test asserts it.

### Testing

`tests/test_debt_intelligence.py` — 100 tests, plus the original 52 still
passing unchanged. The engine tests run without a database.

Two gaps these caught during development:

1. The new model fields were added and the service was never extended to accept
   them, so compounding and fees were **unreachable through the API** despite
   existing on the model.
2. The same fields were then reachable through the API but **absent from the
   terms form**, so a user still couldn't set them. They now sit behind an
   "Interest and fees" disclosure — one click away rather than cluttering the
   common case.

The pattern is worth naming, because it recurred three times: a capability
needs a model, a service path, an API field *and* a UI control before it exists
for anyone. Compounding and fees stalled at the API; refinance and
consolidation stalled at the API with complete simulators behind them. A test
asserting the coach's insight taxonomy is fully reachable caught the same class
of problem when six new debt kinds were added — that kind of coverage assertion
is the cheapest defence against it.

## Multi-tenancy

Fail-closed RLS on `debt_debtprofile` (`0002_rls_debt_tables`) and
`debt_debtratehistory` (`0004_rls_rate_history`). The offset M2M join table has
no `tenant_id` of its own and is scoped through its parent profile — without
that it would be the one unguarded path to which accounts offset which debts.

Debt terms describe what a household owes and on what terms.
