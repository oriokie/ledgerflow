# Income

## 1. What was missing

The product modelled every way money **leaves** — bills, recurring expenses,
budgets with lines, debt profiles with rate history, categories, payees — and
had no model at all of how it **arrives**.

Income existed only as `RecurringType.INCOME` on a schedule template. Which of
those templates was a *salary* — the thing the cash-flow calendar anchors "can
I make it to payday?" on — was decided like this:

```python
label = f"{recurring.category.name} {recurring.memo}".lower()
if any(word in label for word in ("salary", "payroll", "wage", "paycheck")):
    return EventSource.SALARY
```

That was the one place in this product where a figure was derived from a name.
It failed silently and it failed hardest for the users the demo data describes:
a household paid in KES whose memo reads **"Mshahara"** got no payday marker at
all, on a screen built entirely around finding the next payday.

The marker was the cheaper half of the cost. Without a model of income the
product could not answer the questions personal financial management exists to
answer:

* What is my actual take-home rate?
* How much of my income is committed before I choose anything?
* Is my income trending down? (Spending anomalies were detected. Income
  anomalies were not — and a 20% income drop matters more than any category
  overspend.)
* What happens if one stream stops? `apps/debt/stress.py` stress-tests debt
  against rate rises; nothing stress-tested the income side.

## 2. Three models

| Model | Answers |
|---|---|
| `IncomeSource` | The **plan** — who pays you, how much, on what cadence, how reliably |
| `IncomeDeduction` | The gross→net gap, invisible to a ledger that only sees the net deposit |
| `IncomeReceipt` | The **record** — what actually arrived |

Plan and record are separate for the same reason `RecurringTransaction` is
separate from `Transaction`: editing what you expect to earn must not rewrite
what you were actually paid.

### Reliability is a certainty axis

`Reliability` is not a label, it is the input to how a figure may be drawn.

* `FIXED` — projected at face value.
* `VARIABLE` — projected from receipts, with its spread reported.
* `IRREGULAR` with no history — **speculative**. It renders through
  `<Figure certainty="speculative">`, whose type signature *requires* a
  `confidence` string. You cannot put an unbacked income figure on screen
  without saying why it is unbacked.

### Fortnightly is not semi-monthly

`IncomeFrequency` is deliberately its own enum rather than reusing
`finance.Frequency`. Fortnightly pay is 26 payments a year; semi-monthly is 24.
Collapsing them, or reasoning in "weeks per month", loses a fortnight's pay from
every annual figure. `PAYMENTS_PER_YEAR` has no entry for `AD_HOC` on purpose —
there is no honest number, so callers must handle its absence.

## 3. Rules the selectors keep

**Single currency.** Like `net_worth` and the cash-flow calendar, nothing is
summed across currencies.

**Absence is not zero.** Every figure that cannot be computed returns `None`.
The sharpest case: a percentage deduction on a source with no gross resolves to
`None`, not `0`. Returning zero would report a **take-home rate of 100% for
someone who is taxed** — the most misleading number this module could produce.
One unknowable deduction makes the whole monthly total unknown, because a
partial total presented as a whole is worse than no total.

**A measured figure beats a typed one.** For a `VARIABLE` or `IRREGULAR` source
with three or more receipts, the expected amount is the *observed mean* and the
user's stated figure is demoted to a fallback. Three is the floor: below it
`statistics.stdev` is undefined and a "mean" is the last value in disguise.

**Except for fixed income.** A salaried user who received one bonus has not had
a pay rise. Observation overrides expectation only where nothing was fixed in
the first place.

## 4. Committed income

The number this product could not compute before: it has always known the
numerator and never had the denominator.

```
committed = recurring bills + debt minimums + recurring expenses
ratio     = committed / monthly net income
```

Two decisions worth defending:

* **Only what repeats counts.** A one-off bill due this month is a real
  obligation but not a *commitment*. Including it would make the ratio swing on
  the timing of a single vet visit and destroy month-to-month comparison.
* **Two ratios, not one.** `committed_against_fixed_pct` measures the same
  commitments against only the income that is contractually promised. For a
  salaried household the two are identical and the second is noise. For a
  freelancer the gap between them *is* the finding — the rent is due whether or
  not the work arrives. Showing only the flattering ratio was the more
  comfortable option and the wrong one.

Debt minimums are filtered to the income's currency here rather than reusing
`debt.selectors.committed_monthly_minor`, which sums every debt's minimum
regardless of currency.

## 5. Migration, not a clean break

`income.0003_backfill_from_recurring_income` gives every existing income
schedule a real source, using the retired label heuristic **once, at migration
time**, to seed the kind.

That is the right place for it: a one-off, reviewable, correctable guess about
existing data, rather than a rule that silently re-runs on every projection
forever. Without it, replacing the heuristic would have traded "wrong for some
users" for "blank for all of them".

Three tests lock the change in: a payday marked from the model, the same payday
marked when the memo is in Swahili, and an English memo that no longer marks a
payday on its own. Not guessing has to mean not guessing in both directions.

## 6. What the harness caught

Two defects that only appeared once the screen had data — both instances of the
same lesson recorded in `01-audit.md`: **a route audited in its empty state is
barely audited.**

1. `/income` passed axe cleanly while empty. With two sources seeded, three
   duospace money figures inside a half-width card overflowed their own
   containers (`.lf-amount` is `nowrap`, so the box scrolled instead) and axe
   reported four keyboard-unreachable scrollable regions. Folding the swing
   figure into the expected figure's hint fixed the layout and reads better:
   the spread is a property *of* the expectation, not a sibling of it.

2. A household whose income is **entirely ad-hoc** — gig and freelance workers,
   the people this model exists for — resolved to no currency at all, got no
   summary, and was told they had no income. Caught by an API test asserting the
   summary was present; `_dominant_income_currency` now registers an ad-hoc
   source's currency at zero value rather than skipping it.

The demo seed now derives its income sources and every receipt from the
transactions it was already posting, so the observed mean the freelance source
projects from is a measurement of that workspace's own ledger. Seeding figures
that disagreed with their transactions would have put the exact defect this
model exists to prevent into the demo.
