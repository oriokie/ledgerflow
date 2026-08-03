# Automation Engine

Detects patterns in transactions and proposes what to do about them. The
governing rule, from which everything else follows:

> **Automation proposes; a person disposes.**

Nothing in this module writes to the ledger. The single action applied without
a tap is a category on a very high-confidence suggestion, and even that is
recorded as `auto_applied` and remains reversible — an action nobody can review
isn't automation, it's something happening to you.

## The keystone: merchant normalisation

Card descriptors are hostile. The same coffee shop arrives as
`SQ *COFFEE HOUSE 1234`, `SQ*COFFEE HOUSE`, and `COFFEE HOUSE 4471`. Until
those collapse to one merchant, every other detector works with noise:
recurring detection misses a subscription that changed descriptor, duplicate
detection over-fires, and category learning never accumulates enough examples
to be useful.

`normalize_merchant` strips processor prefixes (`SQ *`, `TST*`, `PAYPAL *`),
reference codes, store numbers and embedded dates.

**Conservative by design.** Over-normalising is worse than under-normalising:
merging two genuinely different merchants silently corrupts every figure
derived from the pair, while leaving them separate merely misses a convenience.
The reference-code rule requires two digits, or a digit after the first
character — so `8XY2Z` is stripped and `7Eleven` survives.

Aggregators whose prefix *is* the merchant resolve directly: `AMZN Mktp
US*1A2B3C` would otherwise reduce to "US", which tells the user nothing.

## Detectors

All pure functions in `detect.py`, no ORM — directly testable and identically
reproducible, the same discipline as `debt/payoff.py`.

| Detector | Fires when | Deliberately strict about |
|---|---|---|
| Transfer | Equal, opposite, different accounts, within 4 days | **Exact** amounts only |
| Duplicate | Same account, amount, merchant, within 3 days | Debits only; reported as a candidate |
| Refund | Credit after a charge from the same merchant | Ordering, which is what distinguishes it |
| Recurring | 3+ charges on a consistent cadence | Every gap must fit, not just the mean |
| Income | Regular credits with no matching charge or transfer | Runs after those claim theirs |
| Split | Merchant categorised several ways before | 4+ examples across 2+ categories |
| Category | Learned merchant history | 60% agreement, 2+ examples |

**Transfers require exact amounts.** A near-match is far more likely to be two
unrelated transactions than a transfer that lost money in flight, and pairing
those would silently erase a real expense — the most damaging thing this module
could do.

**Recurring checks every gap, not the average.** Alternating 1-day and 59-day
gaps average to monthly and are nothing of the sort.

**Duplicates are never asserted.** Two identical coffees on one day are normal.
The copy says "worth checking — repeats are often legitimate", and approving one
deletes nothing.

## Learning

`MerchantProfile` accumulates category counts from decisions the user actually
made. Suggestions are grounded in their own behaviour rather than a shared
model — two households categorise the same supermarket differently and **both
are right**, so a global model would be confidently wrong for one of them.

**A rejection withdraws a vote.** It is the most informative signal the system
receives: it says the engine was wrong in a specific, correctable way.
Discarding it is how automation stays bad forever, and worse — without
`unlearn_category`, an engine that made a mistake the user corrected would keep
voting for its own error and grow more confident in it.

**A genuinely split history suggests nothing.** Below 60% agreement, a
suggestion is a coin toss presented as a recommendation.

## Review workflow

Suggestions are **persisted, not recomputed**, so a decision can be recorded
against one and the queue stays stable while someone works through it — a list
that reshuffles under the user as they tap is unusable.

`dedupe_key` identifies the *finding*, not the run. The scanner runs repeatedly
over overlapping windows; without stable identity every run would re-propose
everything already dismissed. A decided suggestion is never resurrected.

Bulk review exists because a hundred suggestions one tap at a time is a queue
nobody finishes. Each is applied individually so one failure can't take the
batch, and rows already decided in a concurrent session are skipped rather than
failing it.

`queue_summary` reports an **approval rate** — the engine's accuracy measured
against the only judge that matters. `None` until something has been decided,
because an accuracy figure from no data is not an accuracy figure.

## A bug this work surfaced

The importer can't leave a transaction uncategorised: the ledger needs a
category for a valid posting, so imported rows land in a lazily-created
"Uncategorized" category.

That broke two things at once. The category detector never fired for imported
rows — **the exact case it exists to serve** — because they had a category. And
the learning engine accumulated votes for "Uncategorized" itself, growing
steadily more confident in a category that means *we don't know*.

`is_placeholder_category` fixes both in the service layer, so `detect.py` stays
free of product-specific names.

## API

| Method | Path |
|---|---|
| `POST` | `/api/v1/intelligence/automation/scan/` |
| `GET` | `/api/v1/intelligence/automation/queue/` |
| `POST` | `/api/v1/intelligence/automation/{id}/{approve\|reject}/` |
| `POST` | `/api/v1/intelligence/automation/bulk/` |
| `GET` | `/api/v1/intelligence/merchants/` |

The merchant endpoint exposes the learning, including the raw descriptors that
normalised together — a user who asks why two things were grouped, or why a
category keeps being suggested, deserves to see the counts it came from.

## UI

`/review` — the queue, most confident first. The reasoning is **always
visible**, not behind a disclosure: unlike a coach insight this asks the user
to act, and nobody should approve something without seeing why it was proposed.

Confidence is banded ("Very likely" / "Likely" / "Worth checking") rather than
shown as a percentage, for the same reason as the goal forecast — a calibrated
estimate rendered to the point implies a precision it doesn't have.

Every card offers **both** accept and dismiss. A card with only an accept
button isn't a review.

## Testing

`tests/test_automation_detect.py` — 50 tests, no database. Normalisation is
tested hardest because everything depends on it, and the detectors are tested
for their refusals as much as their findings.

`tests/test_automation_services.py` — 29 tests covering the learning loop,
idempotent scanning, and the accounting-safety guarantees: scanning never
writes to the ledger, approving a duplicate deletes nothing, approving a
transfer re-posts nothing.

## Multi-tenancy

Fail-closed RLS on both tables (`0006_rls_automation_tables`). The
suggestion↔transaction join has no `tenant_id` of its own and is scoped through
its parent — without that it would be the one unguarded path to which
transactions a workspace has been asked about.
