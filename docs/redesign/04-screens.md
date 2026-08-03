# Screen-by-Screen Redesign

Every major screen, with a concrete recommendation. Findings referenced as
`[A§n]` point at [`01-audit.md`](01-audit.md).

---

## 1. Today (was: Overview) — `/`

**The premise.** This is the only screen most users will open on most days. It
must answer three questions in the first screenful: *how much have I got*,
*what's about to happen*, and *is anything wrong*.

### Desktop

```
┌────────────────────────────────────────────────────────────────────────┐
│  Good evening, Amina                              [ Month ▾ ]          │
│                                                                        │
│  NET WORTH                                                             │
│  KES 39,149.31                    ╭──────── settled ──┊─ projected ─╮  │
│  ▲ 154.0% · 6 months              │        ╱‾‾‾‾‾‾‾‾‾‾┊╌╌╌╌╌╌       │  │
│  assets 42,283.81 · debts 3,134.50│  ____╱             ┊             │  │
│                                    ╰────────────────────┴─────────────╯ │
│                                            Jan          today      Sep  │
├────────────────────────────────────────────────────────────────────────┤
│  NEEDS YOU (only renders when non-empty)                               │
│  ⚠ 12 transactions uncategorised        → review                       │
│  ⚠ Rewards Credit Card missing terms    → add                          │
├───────────────────────────────┬────────────────────────────────────────┤
│  THIS MONTH        day 2 of 31│  NEXT 14 DAYS                          │
│  in    KES 0.00               │  ┊ nothing scheduled                   │
│  out   KES 81.26              │  ┊ add your bills to see what's coming  │
│  ───────────────────────────  │                                        │
│  vs. same 2 days last month:  │  GOALS                                 │
│  out  ▼ 38%                   │  Emergency Fund   ████░░░░  19%        │
└───────────────────────────────┴────────────────────────────────────────┘
```

**Changes and why**

| Change | Fixes |
|---|---|
| Range control moves to the right of the title, subordinate | [A§2.1a] |
| The net-worth chart is the **Meridian**: solid left of today, dashed `horizon` right | The concept made literal on the first screen |
| "This month" compares **same-days-last-month**, and says so | [A§2.1b] — the day-2 nonsense |
| Onboarding becomes a single dismissible strip, server-persisted | [A§2.1c] |
| One `<Figure size="hero">`; every other number is `secondary` or `inline` | [A§2.1d] |
| "Needs you" renders **only when non-empty** — no empty exception panel | — |

### Mobile — the fold contract

Today the first monetary figure sits at **y=1233** [A§2.1]. Target: **≤480px**.

```
 0px   ┌─────────────────────────┐
       │ ☰   Otieno Household  ⌕ │   48px
       ├─────────────────────────┤
       │ NET WORTH               │
120px  │ KES 39,149.31           │   ← the number, above the fold
       │ ▲154% · 6mo             │
       │ ╱‾‾‾╌╌╌                 │   sparkline 64px
       ├─────────────────────────┤
340px  │ ⚠ 12 to review       →  │
       ├─────────────────────────┤
       │ in 0.00  ·  out 81.26   │
480px  └─────────────────────────┘
```

Greeting drops to a 15px line (and disappears entirely on the second visit of
the day). Range control moves below the fold. Onboarding becomes one strip.

---

## 2. Activity (was: Transactions) — `/activity`

The strongest existing screen [A§2.2]. Changes are additive.

| Add | Why |
|---|---|
| **Saved views** in the rail — "Uncategorised", "Over KES 5,000", "Groceries MTD" | The screen that most needs saved filters has none [A§2.2a] |
| **Sticky header + sticky bulk-action bar** when rows are selected | [A§2.2b] |
| **Transfers collapse to one row** with a `⇄` glyph and both account names; expandable to the two ledger legs | [A§2.2c] — correct in the ledger, confusing in the list |
| **Certainty column treatment**: pending rows get the `ochre` dotted underline, scheduled-future rows render `horizon` dashed | The Meridian concept in the ledger |
| **Inline edit** on amount, payee, date — not just category | Reduces a modal round-trip |
| **⌘K integration**: `$>500`, `@Everyday Checking`, `#Groceries` | Turns the palette into a query bar |

Keep: row density, the inline category dropdown, the optimistic update, bulk
selection.

---

## 3. Accounts — `/accounts`

| Fix | Detail |
|---|---|
| **The overlap bug** [A§2.3a] | `.lf-acct-item-main` → `<div>` with `display:flex; flex-direction:column`. Better: replace with `<Stack gap="1">`. One line, ships in Phase 0 |
| **Wallets demoted** [A§2.3b] | Empty Wallets becomes a single "Group accounts into wallets →" link under the list, not a full-height empty card |
| **Negative asset flagged** [A§2.3c] | A cash account below zero gets an `ochre` badge: "Below zero — check for a missing deposit". Never silently rendered |
| **One `<Figure>` treatment** [A§2.3d] | Assets/Liabilities/Net worth and the IN/OUT/NET tiles become the same component at two sizes |
| **Headings** [A§2.3e] | Selected account name becomes the panel's `<h2>` |

**Add:** a net-worth composition bar (stacked, sequential ramp, direct labels)
so "where is my money" is answered visually, not by reading four numbers.

---

## 4. Plan (was: Budgets + Bills + Recurring + Cash flow) — `/plan`

The consolidation argued in [`02-strategy-ia.md §2.4`](02-strategy-ia.md).

```
Plan                                     [ Budget · Bills · Recurring · Forecast ]

  COMMITTED THIS MONTH
  KES 2,940.00 budgeted   ·   KES 81.26 spent   ·   day 2 of 31
  ███░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  on track
```

**Budget tab.** Keep almost verbatim — it is the best screen in the product
[A§2.4]. Two fixes: on days 1–3 the pacing signal says *"too early to tell"*
rather than "on track"; the "Everything's within budget" card becomes a single
line of `ink-500` text.

**Forecast tab (was Cash flow).** This is the rewrite [A§2.6].

> **Rule: a calendar renders only when the days differ.**

When there are no scheduled items, the whole tab collapses to:

```
   Nothing scheduled

   Your balance is flat at KES 42,283.81 because no bills or
   recurring income are set up yet.

   [ Add a bill ]   [ Detect from history ]
```

That replaces twelve identical numbers with one sentence and a way out. When
scheduled items *do* exist:

- **One** stat row, not two [A§2.6b] — lowest point, date, days below zero
- **One** control: a range selector. The `Calendar│Outlook` and
  `Month│Week│Timeline` toggles collapse into a single view switcher
  [A§2.6c]
- Days render `horizon` dashed — they are projections and must look like it
- The calendar starts on the user's week-start preference and never renders a
  first row with a single populated cell [A§2.6d]

**Bills / Recurring tabs.** Merge into one list with a "repeats" flag. A bill
and a recurring payment are the same object with a different cadence; two
screens for one concept is the IA problem in miniature.

---

## 5. Goals — `/goals`

| Fix | Detail |
|---|---|
| **Card action alignment** [A§2.5a] | `<Grid>` gives children `display:grid; grid-template-rows: 1fr auto` so action rows share a baseline |
| **Summary band** [A§2.5b,c] | One `<Figure size="hero">` for "Saved across goals"; target and count become `inline`. The 19% label moves to sit *on* the meter |
| **Suggestions visually distinct** [A§2.5d] | Suggestion cards get no fill, a dashed `horizon` border, and an "Idea" eyebrow. A recommendation must never look like a commitment |
| **Headings** [A§2.5e] | Each goal card title becomes `<h3>` |

**Add:** a projection line per goal — "on track for March 2027 at
KES 400/month" — rendered `horizon` dashed, with the contribution assumption
stated. This is the highest-value addition on the screen and the data already
exists (`goals/forecasting.py`).

---

## 6. Insights (was: Coach + Analytics + Reports + Insights) — `/insights`

```
Insights                          [ Briefing · Trends · Reports · Anomalies ]
```

**Briefing tab.**

| Fix | Detail |
|---|---|
| `TemplateNarrator` removed from copy [A§2.8a] | Replace with a `<Provenance>` component: "Written from your own figures" + an info affordance disclosing the method. Never a class name |
| Pluralisation [A§2.8b] | A `plural(n, "account")` helper, applied product-wide. Also fixes "1 DEBTS" |
| Headline stated once [A§2.8c] | Briefing headline, body and the first insight card currently repeat verbatim. The body summarises *the rest* |
| Coloured numerals get labels [A§2.8e] | "1 worth a look" / "2 opportunities" — colour supports the label, never replaces it |

**Trends tab (was Analytics).** Three fixes, two of them P0:

1. **Honour `prefers-reduced-motion` in charts** [A§2.7a′]. Recharts animation
   is JS-driven and never sees the reduced-motion stylesheets. It also means bar
   shapes only exist after the first animation frame, so charts are blank
   anywhere `requestAnimationFrame` does not run — print, PDF export, a
   background tab. (An earlier claim that this chart rendered *nothing* was a
   measurement error and is retracted — see [`01-audit.md §4.2`](01-audit.md).)
2. **Expenses stop being red** [A§2.7b]. `CashFlowChart.tsx:32` →
   `--lf-chart-expense` (ink). This currently contradicts the system's own
   stated rule.
3. **Honest period comparison** [A§2.7c]. Never compare a partial month to a
   whole one. Either compare same-days-last-month, or label the figure
   `pending` and state the basis: *"2 days vs. 2 days last month"*.

Delta badges become inline `▲ 12%` beside the figure, not full-width bars
[A§2.7d]. The chart is renamed "Income vs. expenses" so "Cash flow" means one
thing [A§2.7e].

---

## 7. Debt — `/debt`

The worst trust defect in the product [A§2.9a].

**The score.** A 100/100 "Excellent" computed from 45% of inputs must not
render as a confident numeral. Under the Meridian rules it is `speculative`:

```
   Debt health

   ┌ ─ ─ ─ ─ ─ ┐
   ┊    ~100   ┊   Provisional
   └ ─ ─ ─ ─ ─ ┘
   Based on 45% of the usual inputs. Add interest rates and
   minimum payments for a real score.       [ Add terms ]
```

Dashed container, `horizon`, tilde prefix, "Provisional" label, and the caveat
*attached to the number* rather than 200px away. `<Figure>` makes this the only
representable form (§7.2 of the design system).

**The zero grid** [A§2.9c]. When no debt has terms, the analytics section
renders `<Empty>` — not "Interest KES 0.00 / Fees KES 0.00 / Average rate 0%".
Those zeros claim a measurement that was never made.

*Shipped in 4.9, one level finer than specified here.* "No debt has terms" is
not the only case: terms can be recorded on some debts and not others, and a
rate can be recorded while a minimum is not. So the gate is **per figure, on
its own input** — the average rate goes when no rate exists, the minimums total
goes when no minimum exists, and each can survive without the other. Partial
data keeps its figures and states its basis ("terms recorded for 1 of 3 debts")
rather than being suppressed, because a measurement over part of the balance is
still a measurement. Suppressing it would throw away something true; showing it
bare would overstate what was measured.

A recorded **0%** is a measurement and displays normally. The distinction the
whole page now turns on is *recorded* versus *derived-from-nothing*, never
*zero* versus *non-zero* — which is also why `weighted_apr` stopped averaging
untermed debts in at `apr = 0`.

**Pluralisation** [A§2.9b]: "1 debt".

---

## 8. Settings — `/settings`

| Fix | Detail |
|---|---|
| **Two inputs, one label** [A§2.10a] | Split into `First name` / `Last name` with individual `<label for>`. WCAG 3.3.2 |
| **Dead space** [A§2.10b] | Panel max-width 720px, left-aligned to the nav column, vertically top-aligned. Not a lonely card in a void |
| **One alignment grid** [A§2.10c] | Every row: label + description left, control right, single shared column boundary |
| ~~**Flatten** [A§2.10d]~~ | ~~Six leaf items don't need two levels. One list~~ — **not done, deliberately.** See below |

**Add:** autosave with an "All changes saved" affordance, replacing the
`Save changes` button. Settings is the canonical autosave surface.

**Correction (4.11) — the grouping stays.** "Six leaf items don't need two
levels" counts the items and not what the levels are carrying. The two groups
are not topical, they are **scope**: settings that change things for you, and
settings that change things for everyone in the workspace. In a multi-tenant
product that is the most consequential property a setting has. Flattening would
make renaming your own display name and renaming the workspace read as the same
kind of act, to save two lines of nav.

Kept, with the labels changed from `Account` / `Workspace` to **`Your account`**
/ **`Whole workspace`** so the grouping states its own meaning instead of
leaving it inferred from two nouns.

---

## 9. Investments, Bills, Recurring, Categories, Members, Billing, Notifications

These inherit the systemic fixes rather than needing bespoke redesign.

| Screen | Recommendation |
|---|---|
| **Investments** | Portfolio value as `<Figure size="hero">`; holdings as `<DataTable>`; allocation as a sequential-ramp bar with direct labels, not a donut. ~~Cost basis is a known gap (`PRODUCT_AUDIT.md §1.4`) — until it exists, returns are `speculative` and must say so~~ |

**Correction (4.10).** That last clause was wrong, and I wrote it by citing
`PRODUCT_AUDIT.md §1.4` without checking it against the code. §1.4 says
investments are "NOT IMPLEMENTED"; the module has since been built, with
per-lot cost basis computed from the ledger rather than stored. Returns are not
speculative for want of a cost basis.

The certainty problem on this screen was a different one, and a real one:
`latest_price_minor` returned a quote's *price* and discarded its *date*.
Quotes here are typed in by hand — there is an "Update prices" button, not a
market feed — so market value was only ever as current as the last time someone
entered a number, and the page presented it under the heading "what it's worth
today". A six-month-old quote and this morning's rendered identically. The date
is now carried through to both the holding and the summary, the total is dated
by its **stalest** input, and market value and total return carry `projected`
while cost basis, realised gains and dividends carry `settled`.

*An audit finding is evidence about the code at the time it was written, not a
standing fact. Citing one into a recommendation without re-reading the code is
how a stale claim gets laundered into a plan.*
| **Bills / Recurring** | Merge (§4). One list, cadence as a property. Next-due date is `horizon` dashed |
| **Categories** | Leaves the nav; becomes a Settings panel plus a facet in Activity. Tree view with inline rename and drag-to-reparent |
| **Members** | Moves under the workspace menu. Role changes need a confirm step; role meanings shown inline, not in a tooltip |
| **Billing** | Plan card + usage meters using `<Meter>`. Entitlement limits stated before they are hit, not at the point of refusal |
| **Notifications** | Merge with the bell popover — one inbox, two presentations. Group by day; unread is a left `meridian` rule, not a dot |

---

## 10. Authentication

Keep [A§2.12]. Two small fixes: move the reveal toggle inside the password
field's rectangle; freeze the rotating quote per session so a failed login does
not change it.

**Add:** on the workspace picker, show each workspace's net worth and member
count — the choice is currently made from a name alone.

---

## 11. Platform Admin — `/admin/*`

Identity treatment specified in [`02-strategy-ia.md §4`](02-strategy-ia.md);
dashboard restructure specified there too.

| Fix | Detail |
|---|---|
| **Mobile rail is broken** [A§2.13d] | `.lf-admin-rail` collapses to 375×64 with `background:#F6F7F9` — a *light-mode* token hardcoded into a dark console — and 11 links crushed into ~26px each. **P0.** Replace with a drawer + a 5-slot bottom bar, and delete the hardcoded colour |
| **12 equal tiles → 1 hero + exception panel** [A§2.13a] | MRR with sparkline as hero; "Needs attention" above it; the rest as dense supporting lines |
| **Distinct identity** [A§2.13b] | `[data-product="platform"]` theme block |
| **Freshness** [A§2.13c] | "Updated 8:29:21 PM" → "Updated 2 minutes ago" with a refresh affordance |
| **Mobile scroll** [A§2.13e] | Tiles become a 2-column compact grid; ~4,000px → ~900px |

Keep the IA (Customers / Recovery / Promotions / Access / Audit) — it is better
structured than the tenant navigation and needs no change.

---

## 12. States

Every screen needs four, and today most have one.

| State | Rule |
|---|---|
| **Empty** | Teach. Icon + one sentence of *why this is useful* + one action. Never a grid of `0.00` |
| **Loading** | Skeletons matching final layout, after 200ms. Never a spinner on a full page |
| **Error** | What failed, whether data is stale, and a retry. Never "Something went wrong" alone |
| **Partial** | **New.** Data loaded but insufficient for the conclusion — the Debt-score case. Renders `speculative` with its caveat |

The "partial" state is the one the product is missing, and it is the one a
finance product most needs.

---

*Continues in [`05-interaction-a11y-performance.md`](05-interaction-a11y-performance.md).*
