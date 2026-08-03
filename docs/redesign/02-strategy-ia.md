# Redesign Strategy, Information Architecture & Navigation

---

## 1. Strategy

### 1.1 The thesis

> **A personal finance product earns "premium" by being *certain* about what it
> knows and *honest* about what it doesn't. Everything else is decoration.**

The audit found three trust defects (a 100/100 score from 45% of inputs; a
two-day sample reported as a 97% improvement; an empty flagship chart) and
roughly a hundred cosmetic ones. The cosmetic problems make the product feel
cheap. The trust problems make it feel *wrong*, and no amount of glass,
gradient or spring animation compensates for a number the user has stopped
believing.

So the redesign is organised around one idea, and the visual language is built
to serve it.

### 1.2 The organising concept: **Meridian**

Money is not a dashboard. It is a **line running through time**. To the left:
what has settled — banked, reconciled, certain. To the right: what is
projected — forecast, estimated, uncertain. **Today is the meridian.**

Every screen in LedgerFlow places the user somewhere on that line, and **the
visual language encodes certainty as a first-class property**:

| Certainty | Treatment |
|---|---|
| **Settled** — posted, reconciled | Solid fill, full-opacity ink, sharp edge, ledger duospace |
| **Pending** — authorised, not cleared | Solid fill, hairline dashed underline |
| **Projected** — forecast from recurrence | 60% opacity, dashed stroke, no fill |
| **Speculative** — model output, thin data | Dashed stroke *plus* an explicit confidence statement; never a bare number |

This is the differentiator. Monarch, Copilot, YNAB and Rocket all render a
forecast identically to a fact. LedgerFlow will not. A projection that *looks*
like a projection is both more honest and — because it removes the reader's
background anxiety about which is which — more calming.

It also resolves the audit's worst findings by construction:

- The Debt score of 100 from 45% of inputs becomes a **speculative** figure: it
  cannot render as a confident numeral, so the defect is unrepresentable.
- The Cash flow calendar's twelve identical numbers are all projections from
  *no* recurring data — so they render as a single dashed line with "nothing
  scheduled", not as twelve confident amounts.
- The Analytics 97% delta compares an incomplete period, so it is **pending**
  and must state its basis.

### 1.3 Design philosophy

1. **Colour is rationed.** Near-monochrome by default. Colour appears only
   where it carries meaning: money-in, alert, selection, projection. In a
   product where the only coloured things are meaningful, colour becomes
   information rather than decoration — and the result reads as an instrument,
   not a consumer app.
2. **Whitespace carries hierarchy, not rules and boxes.** Fewer borders, fewer
   cards-within-cards, larger gaps between things that differ in kind.
3. **One number per view earns the hero.** Every screen has a single primary
   figure. Everything else is subordinate typography.
4. **Progressive disclosure by default.** Show the answer; put the working
   behind a disclosure. ("How is this worked out?" already exists on the Debt
   page — generalise it.)
5. **Motion settles, never bounces.** Money is not playful. Elements arrive and
   come to rest; nothing overshoots.
6. **The empty state is a product surface, not a fallback.** A screen with no
   data must teach, not apologise — and must never render a grid of `0.00`.

### 1.4 What we are explicitly *not* doing

- Not discarding the token architecture (§4 of the audit)
- Not replacing the ledger duospace treatment — we are amplifying it
- Not adding a component framework; the primitive layer stays hand-rolled CSS
  + React, which is already working
- Not shipping confetti anywhere except a *completed* savings goal

---

## 2. Information architecture

### 2.1 The problem

**Twenty-one primary destinations in the rail.** Four of them (Coach,
Analytics, Reports, Insights) answer the same user question. Two of them
(Quick Add, Scan Receipt) are *actions*, not places — putting a verb in a
navigation list is a category error. Cash flow lives under "Intelligence"
while Bills and Recurring — the data that *produces* the cash-flow forecast —
live under "Money".

### 2.2 The principle

Organise by the **question the user is asking**, not by the database table
they'd need to answer it.

| The user asks | Destination |
|---|---|
| Where do I stand right now? | **Today** |
| What have I got, and where? | **Accounts** |
| What happened? | **Activity** |
| What's already committed? | **Plan** |
| Am I getting anywhere? | **Goals**, **Invest**, **Debt** |
| What does all this mean? | **Insights** |

### 2.3 Proposed structure — 21 destinations → 8

```
POSITION
  Today          /                 Overview — the command center
  Accounts       /accounts         Balances, wallets, net worth composition
  Activity       /activity         The ledger. Categories = a facet, not a page

COMMITMENT
  Plan           /plan             Budgets · Bills · Recurring · Cash flow
                                   (four tabs, one destination, one mental model:
                                    money that is already spoken for)

TRAJECTORY
  Goals          /goals            Savings goals + projections
  Invest         /investments      Portfolio
  Debt           /debt             Balances + payoff planning

MEANING
  Insights       /insights         Coach briefing · Trends · Reports · Anomalies
                                   (four tabs, replacing four separate routes)
```

**Removed from navigation entirely:**

| Was | Becomes |
|---|---|
| `/categories` | A facet inside Activity + a management panel in Settings |
| `/quick-add` | The `+` action (FAB / ⌘K / topbar) |
| `/receipts/scan` | An option inside the `+` action |
| `/automation` | Settings → Automation |
| `/members`, `/billing`, `/settings` | The workspace menu (top-left), where workspace-scoped admin belongs |
| `/coach`, `/analytics`, `/reports` | Tabs within Insights |
| `/bills`, `/recurring`, `/cashflow`, `/budgets` | Tabs within Plan |

**Route compatibility.** Every retired path redirects to its new home with the
correct tab preselected (`/bills → /plan?tab=bills`). No bookmark breaks. This
is a routing change, not a data change.

### 2.4 Why "Plan" is one destination and not four

Budgets, Bills, Recurring and Cash flow are four views of a single fact: *money
that is already spoken for.* A budget is a limit you set; a bill is a payment
you owe; a recurrence is a bill that repeats; the cash-flow calendar is all of
them laid on a timeline. Today the user must visit four screens and reconcile
them mentally. Unified, the forecast is visibly *derived from* the bills and
recurrences on the adjacent tab — which is also what makes the cash-flow
calendar's emptiness self-explaining rather than mysterious.

---

## 3. Navigation

### 3.1 Desktop rail

```
┌──────────────────────┐
│  ◇ The Otieno House… │  ← workspace switcher (⌘⇧K), owns Members/Billing/Settings
├──────────────────────┤
│  ⌘K  Search or jump  │  ← command palette trigger, always visible
├──────────────────────┤
│  ★ Pinned            │  ← user-pinned views: "Groceries this month", a saved filter
│    Groceries · MTD   │
├──────────────────────┤
│  Today               │
│  Accounts       39.1k│  ← live value on the rail item itself
│  Activity          12│  ← count of transactions needing review
│                      │
│  Plan            ⚠ 2 │  ← 2 bills due this week
│                      │
│  Goals          19%  │
│  Invest              │
│  Debt                │
│                      │
│  Insights         ●  │  ← unread insight dot
└──────────────────────┘
   ⌄ collapse to 64px icon rail
```

Three changes that matter:

1. **The rail carries data.** A navigation item that shows its own headline
   value ("Accounts 39.1k", "Plan ⚠ 2") lets the user answer most questions
   without navigating at all. This is the single highest-leverage navigation
   change available and it is cheap — the data is already fetched for the
   dashboard.
2. **Pinned views.** Any filtered state in Activity, any report, any category
   drill-down can be pinned to the rail. This is what converts a monthly-visit
   product into a weekly-habit product.
3. **Collapsible to a 64px icon rail**, persisted per user. At ≥1600px the rail
   stays expanded and the content column widens rather than centring in a void.

### 3.2 Command palette (⌘K)

Already exists (`CommandPalette.tsx`) and is good. Extend it from a navigator
into the product's primary input surface:

- `> ` actions — "add transaction", "import CSV", "new budget line"
- `@` accounts — jump to or filter by account
- `#` categories
- `$` amounts — `$>500` finds transactions over 500
- Recent + frequent destinations ranked ahead of alphabetical
- Every action reachable by keyboard shows its shortcut inline

### 3.3 Mobile

**Bottom tab bar — five slots, one of them a verb:**

```
   Today      Activity        ⊕         Plan       Insights
                          (add money
                            action)
```

`Accounts`, `Goals`, `Invest`, `Debt` live in the Today screen's account strip
and in a "More" sheet from the avatar. The centre `⊕` opens an action sheet:
Add transaction · Scan receipt · Add bill · Transfer.

**The mobile fold contract.** Measured today: the first monetary figure on the
dashboard appears at **y = 1233px on an 875px viewport**. New rule, enforceable
in a test:

> On any screen, on a 375×812 viewport, the primary figure must render within
> the first 480px.

Concretely on Today: greeting collapses to a single 15px line above the balance
(or is dropped on repeat visits within the day), the range control moves *below*
the hero, and the onboarding checklist becomes a single dismissible strip.

### 3.4 Breadcrumbs

Not needed. The IA is two levels deep everywhere (destination → tab). Tabs are
self-locating; breadcrumbs would be chrome without information. The one
exception is Admin → Customers → *tenant detail*, which gets a back-link with
the tenant name rather than a full breadcrumb trail.

---

## 4. Platform Admin: a deliberately different product

The console must not look like the customer app. An operator with the power to
suspend an account should never be one glance away from thinking they are in
their own budget.

**The distinction is structural, not decorative:**

| | Tenant workspace | Platform console |
|---|---|---|
| Surface | Warm paper / warm graphite | **Cool slate**, one step darker |
| Accent | Meridian teal | **Signal amber** |
| Density | Comfortable (44px rows) | **Compact (32px rows)**, operator default |
| Type | Display grotesk headings | **Ledger duospace headings** — a terminal, not a magazine |
| Corners | 16px cards | **8px** — squarer, more utilitarian |
| Motion | Settle, 200ms | **Instant**, ≤80ms; operators repeat actions |
| Chrome | Greeting, personality | Environment badge, data freshness, actor identity |

Same tokens, different *semantic assignment*. Costs one theme block; buys an
unmistakable "you are in the control room" signal.

**Dashboard restructure** — replacing 12 equal tiles:

```
┌─────────────────────────────────────────────────────────────┐
│  NEEDS ATTENTION                                            │
│  ⛔ System down                     → investigate            │
│  ⚠  1 account in payment recovery   → open recovery queue    │
└─────────────────────────────────────────────────────────────┘

  MRR                          Δ         │  Workspaces   11
  $75  ▁▂▃▅▆█                 +12%       │  Active       10
  ─────────────────────────────────────  │  Trialing      0
  ARR $896 · ARPA $15 · LTV $75          │  Suspended     1 ⚠
                                          │  New (30d)     1
  COLLECTION                              │
  Today $0 · MTD $0 · Lifetime $245       │
  Payment success 75.0% ⚠ 1 failed / 30d  │
```

One hero (MRR, with its trend), one exception panel above it, everything else
demoted to dense supporting lines. The operator's first question is "is
anything broken?" — so that answer goes first, and it is the only thing allowed
to use colour.

---

*Continues in [`03-design-system.md`](03-design-system.md).*
