# `investments` — Portfolio Tracking

Closes the gap flagged in the product audit as a launch blocker: `AccountType.INVESTMENT`
existed, but an investment account was treated as a cash-like balance with no
holdings, cost basis or lots.

## The one decision everything follows from

> **The ledger holds cost. Market value is derived and never posted.**

What you paid for a security is a fact: money moved, and a double-entry pair
records it. What it is *worth today* is an opinion that changes every second and
that you have not realised. Posting an unrealised gain would put a number in the
ledger that no transaction produced, and the ledger would stop reconciling to
anything real.

Four figures, kept deliberately distinct throughout:

| Figure | Source | In the ledger? |
|---|---|---|
| Cost basis | Sum of open lots | Yes — exact |
| Market value | Latest quote × quantity | No — an estimate |
| Unrealised gain | The difference | No |
| Realised gain | Booked on disposal | Yes — real income |

A portfolio view that blurs those is how people come to believe they have money
they haven't made.

## Accounting

```
Buy       DEBIT  investment asset (cost + fees)
          CREDIT cash

Sell      DEBIT  cash (net proceeds)
          CREDIT investment asset (at COST of lots disposed)
          + balancing line to realised gain/loss

Dividend  DEBIT  cash
          CREDIT dividend income

Split     no entry — nothing moved
```

The subtle one is the sale. The asset is relieved at what it **cost**, not at
what it sold for, and the gap is the realised gain. Crediting at proceeds
instead makes book value drift from the lots that formed it, and the error
compounds silently with every sale. There's a test named for exactly this.

A split posts nothing. More units, same money — posting anything would invent
value from a relabelling.

Dividends are income, never added to cost basis. Capitalising them would
understate every subsequent gain.

## Lots, not averages

Cost basis is tracked per **lot** — one purchase, one price, one date. Two
purchases of the same stock at different prices are two different tax facts, and
averaging on purchase loses information that cannot be reconstructed.

A lot's `quantity` and `cost_minor` never change; only `quantity_remaining`
shrinks as it's disposed of. That keeps the original purchase a stable
historical fact after partial sales.

**FIFO** is the default disposal method — the most widely applicable, and what a
user without a stated preference means. The lot model makes LIFO or specific
identification a change to `_consume_lots_fifo` alone: no schema, no migration.

Disposals `select_for_update()` the lots, so two concurrent sales can't both
believe they consumed the same shares.

## Unpriced holdings

A security with no quote returns `None` for price, market value and unrealised
gain — never zero. A zero in a market-value column reads as a total loss.

This propagates consistently:

- **Allocation excludes them entirely.** Counting an unpriced position as 0%
  would inflate every other slice while the pie still summed to 100% — still
  wrong, but invisibly so.
- **The summary reports `unpriced_count`**, so the UI can say the total is
  partial rather than presenting it as complete.
- **The net-worth adjustment ignores them**, so it never claims a gain on a
  position nobody has valued.

## Net worth integration

The ledger carries investments at cost, so net worth read straight from balances
understates a portfolio that has grown.

`GET /api/v1/finance/net-worth/` therefore returns **both**, side by side:

| Field | Meaning |
|---|---|
| `assets_minor`, `net_minor` | Book value — investments at cost, straight from the ledger |
| `unrealized_gain_minor` | The overlay: market value less cost, across priced holdings |
| `market_assets_minor`, `market_net_minor` | Book value plus the overlay |

Kept separate rather than folded together on purpose: one is what the books say,
the other what the market says, and a single blended number would put an
unposted gain into a figure that is supposed to reconcile. The overlay is 0 when
nothing is held or nothing is priced.

## Currencies

A GBP account cannot hold a USD security. That needs an FX policy this module
doesn't have, and refusing is honest where guessing a rate would not be. Hold
foreign securities in an account of that currency.

`portfolio_summary` is single-currency, matching net worth and the cash-flow
statement.

## Broker integration readiness

The seam is `record_price` and the service layer. A market-data or broker sync
job records quotes and trades through the same services a user does — nothing
else in the module changes. `Security.external_id` and `PriceQuote.source` exist
to carry provider identity.

Securities are **tenant-scoped** rather than global reference data. A household
may hold things no provider lists — a private company stake, a physical asset —
and a shared registry would either exclude those or be polluted by them.

## API

| Method | Path |
|---|---|
| `GET`/`POST` | `/api/v1/investments/securities/` |
| `GET` | `/api/v1/investments/holdings/` |
| `GET` | `/api/v1/investments/portfolio/` — 204 when empty |
| `GET` | `/api/v1/investments/portfolio/history/?months=` |
| `POST` | `/api/v1/investments/trade/{buy\|sell}/` |
| `POST` | `/api/v1/investments/prices/` |
| `POST` | `/api/v1/investments/dividends/record/` |
| `GET` | `/api/v1/investments/dividends/` |
| `POST` | `/api/v1/investments/splits/` |
| `GET` | `/api/v1/investments/transactions/` |

## UI

`/investments` — summary, performance, allocation, holdings, in that order:
what it's worth, how it got there, what's in it.

Trades, securities and prices are all entered from this page — "Add security",
"Update prices", and "Record trade", with Buy/Sell also on the holdings section.

The trade form asks for the **total consideration**, not a unit price: that's
what a contract note shows, and deriving a total from a rounded unit price would
disagree with the cash that actually moved. Fees are a separate field because
they're treated differently on each side — capitalised into cost on a buy,
deducted from proceeds on a sell — and folding them into the amount would
misstate the gain either way. The price form, by contrast, takes a **per-unit**
price, because that's the shape a quote comes in.

Selling narrows the security picker to open positions and shows the units held,
catching the most common error before the server has to reject it.

The performance chart plots **market value against cost basis**. The gap between
the lines is the unrealised gain, and seeing cost rise as you invest explains
why value rose without implying the whole increase was growth. A value-only
chart makes contributions look like performance.

Allocation charts render an accessible list alongside the donut — the chart is
decorative, the list is the source of truth and easier to read exact percentages
from.

## Testing

`tests/test_investments.py` — 45 tests. The accounting ones pin the four known
ways this goes wrong: relieving at sale price instead of cost, capitalising
dividends, posting unrealised gains, and losing lot identity by averaging.

### Historical cost is replayed, not approximated

`_cost_at()` replays the transaction log to work out what a position cost on a
past date, consuming lots FIFO exactly as the sales did.

An earlier version read each lot's *current* remaining quantity, which meant a
position bought in January and sold in June appeared to have cost nothing in
February — the cost line on the performance chart sagged toward zero in exactly
the months the user was invested. Four tests now pin the replay, including that
it agrees with the live cost-basis figure for today.

## Multi-tenancy

All five tables carry fail-closed RLS (`0002_rls_investment_tables`). Holdings
describe what a household owns and what it's worth, so this is not optional
hardening.
