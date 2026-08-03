# `fx` — Exchange Rate Reference Data

The smallest module in the system — currently reference data only, not yet
wired into any posting path. Documented here primarily as the seam for
cross-currency support.

## Domain model

| Model | Purpose | Key fields |
|---|---|---|
| `ExchangeRate` | A timestamped, source-attributed rate | `base_currency`, `quote_currency`, `rate` (`DecimalField`, 24 digits/12 decimal places — enough precision for any real-world pair), `as_of`, `source` (e.g. `"ecb"`, `"openexchangerates"`) |

Not tenant-scoped — exchange rates are global reference data, same as
`finance.Institution`. Unique on `(base_currency, quote_currency, as_of, source)`;
`rate` must be positive (`CheckConstraint`).

Every rate is timestamped and attributed to a source **specifically so
historical conversions are reproducible and auditable** — if a cross-currency
transaction is ever posted, the exact rate used at posting time must be
traceable, not re-derived from "whatever the latest rate happens to be now."

## Current status

No services, no selectors, no API — just the model and its migration.
`ledger.services.post_journal_entry` currently **requires** every line in an
entry to share one currency and raises `LedgerError` otherwise; `finance`'s
`record_transfer` similarly requires both accounts to share a currency
(`CurrencyMismatchError`). `finance.selectors.net_worth()` and `cash_flow()`
both return **per-currency** results rather than summing across currencies —
deliberately, so that when cross-currency support lands, nothing downstream
has to change its contract to stay correct; they already refuse to produce a
meaningless blended total.

## Extension points

See [`../EXTENSION_POINTS.md#cross-currency-support-documented-not-yet-built`](../EXTENSION_POINTS.md#cross-currency-support-documented-not-yet-built)
for the intended design: a `fx.services.convert()` producing a rate-attributed
`Money`, and a transfer-like service that posts a **three-line** entry
(source currency out, an FX clearing account, destination currency in) so the
audit trail shows exactly which rate was used. This keeps the "all lines of
an entry share one currency" invariant in `ledger` intact — a cross-currency
"transfer" becomes two same-currency legs through a clearing account, not an
exception to the ledger's core rule.

## Testing

No dedicated test file yet — `ExchangeRate` has migration coverage only. Add
`tests/test_fx.py` when the service layer lands.
