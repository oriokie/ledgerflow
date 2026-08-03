# LedgerFlow — UX & Front-end Audit

**Method.** Every finding below was verified against the running application
(seeded with 221 transactions, Jan–Aug 2026) or against the source. Findings
carry evidence: a measurement, a file:line, or an API response. Impressions
without evidence are marked as such.

**Scope.** 30 tenant routes, 12 platform-admin routes, 388 source files,
47,905 LOC, 27 stylesheets, 750 distinct class selectors.

---

## 0. The headline

**This is not a Bootstrap admin template, and treating it as one would waste
the best asset the project has.**

`src/styles/tokens.css` is a genuinely sophisticated design foundation. It
encodes a real opinion — money-in is verdant, money-out is *ink not red*,
carmine is reserved for things that are actually wrong — and it backs that with
a verified contrast floor, a dark theme, and a `prefers-contrast: more` block.
Most commercial fintech products do not have this.

> **Corrected in Phase 2 — see §4.1.** This section originally claimed the
> foundation "stops at primitives" and that every composite was missing. Seven
> of the eight components it proposed building already existed and were well
> adopted. The real finding is narrower and sharper, and it is stated below.

The problem is not the foundation. **The problem is a single missing
component.** Where the library provides a primitive, features use it. Where it
does not — and there is exactly one such concept — every feature hand-rolled
its own, and that is where the "assembled rather than designed" feeling comes
from.

The evidence is in *where the selectors live*:

| Concept | In the shared library | Scattered across feature stylesheets |
|---|---|---|
| Progress / meter | 11 | 10 |
| Empty state | 14 | 4 |
| **A labelled number ("stat tile")** | **3** | **71, across 13 files** |

`.lf-stat-band-item`, `.lf-cashflow-stat`, `.lf-goal-metric`,
`.lf-budget-summary-stat`, `.lf-portfolio-metrics`, `.lf-debt-metrics`,
`.lf-admin-kpi-value`, `.lf-hero-figure`, `.lf-compare-value`,
`.lf-acct-summary-item`, `.lf-report-score-value`, `.lf-stress-value` … all of
these are "a label with a number under it," and there was no `<Figure>` to use
instead.

That is the whole mechanism. Meter and EmptyState exist, so their styles
concentrate in the shared library and features consume them. The labelled
number did not exist, so thirteen features each invented one — with different
type sizes, label casing and alignment. It is why three figures in a single row
on the Goals page sat on three different baselines, and why one of them was
hand-styled with inline `var(--lf-*)` values to approximate a size the library
never offered.

**Build the one missing component and most of the "premium feel" problem
resolves itself** — not because the team lacked discipline, but because they
had nowhere to put this.

---

## 1. Systemic findings

### 1.1 The type scale is defined, then bypassed — **high**

`tokens.css` defines a clean 1.20 modular scale of 7 steps. The Accounts page
renders **11 distinct font sizes**:

```
9.44px  11.10px  11.33px  13.33px  13.60px  16px  19.2px  23.04px  27.65px  33.84px  39.81px
        ^token   ^off     ^token   ^off                                      ^off
```

Four are off-scale, produced by `em`-relative sizing compounding inside nested
components (`.lf-amount-cents` at `0.85em` inside an already-scaled parent).
**9.44px is below any legibility floor** and is being used for live UI text.

Goals renders 10 sizes. Every audited screen renders 9–11 against a 7-step
scale. The scale is not the source of truth; it is a suggestion.

### 1.2 Fourteen breakpoints, four of them off-by-one pairs — **high**

```
479  519  560  639  640  720  760  767  768  899  900  1023  1024  1600
          639/640 ─┘    767/768 ─┘   899/900 ─┘    1023/1024 ─┘
```

There is no breakpoint token. Each stylesheet picked its own. The off-by-one
pairs mean two components change layout one pixel apart, and at 640px, 768px,
900px and 1024px exactly, some components have *no* rule applying.

`--lf-content-max: 1200px` with a single `1600px` query means **ultrawide is
effectively unsupported**: on a 2560px display the app is a 1200px column in a
1360px void.

### 1.3 Layout is hand-rolled per feature, and it is provably wrong in places — **high**

There is no layout primitive (`Stack`, `Row`, `Grid`). Every feature hand-writes
flexbox. On the Accounts page this produces a measurable defect:

**`.lf-acct-item-name` overlaps `.lf-acct-item-meta` by 130px.**

Root cause — [`AccountList.tsx:29-35`](../../frontend/app/src/pages/accounts/AccountList.tsx#L29):

```tsx
<span className="lf-acct-item-main">      {/* flex:1; min-width:0 in CSS */}
  <span className="lf-acct-item-name">…</span>   {/* nowrap + ellipsis */}
  <span className="lf-acct-item-meta">…</span>
</span>
```

`.lf-acct-item-main` is styled `flex: 1; min-width: 0` but rendered as a
`<span>`, which is `display: inline`. Flex sizing does not apply, no block
formatting context is created, `text-overflow: ellipsis` on the child can never
fire because the child has no constrained width — so the account name, its type
label and its balance all run into each other. Visible at 1280px on the default
seeded data ("Rewards Credit Card" / "Credit card").

This is a one-line fix. It is included here because it is *symptomatic*: a
`Stack` primitive would have made it unrepresentable.

### 1.4 Card grids do not align their action rows — **medium**

Goals, "Suggested for you": two cards side by side, `Set this up` buttons at
`y=418` and `y=397`. A 21px misalignment on the primary action of a two-card
grid. Cause: cards size to content with no shared baseline row. Every card grid
in the product has this property.

### 1.5 Pluralisation is unimplemented — **medium**

- Debt page eyebrow: **"1 DEBTS"**
- Coach briefing: **"KES 3,134 outstanding across 1 accounts"** (twice on one screen)

There is no plural helper anywhere in the codebase. Every count in the product
is a latent instance of this.

### 1.6 Internal implementation names leak into user-facing copy — **high (trust)**

Coach page, under the briefing:

> "Written from your own figures by **TemplateNarrator**."

`TemplateNarrator` is a class name. This is on the flagship "intelligence"
surface, in the sentence whose entire job is to make the user trust the
narration.

### 1.7 Token bypass in the styling layer — **medium**

- 53 hardcoded hex values in stylesheets outside `tokens.css`
- 183 inline `style={{…}}` objects across 80 components
- `polish.css` (38 selectors) and `premium.css` (16 selectors) exist as
  *corrective layers applied after the fact* — the names are an admission that
  the base layer did not deliver the intended finish

Encouragingly, discipline elsewhere is good: the `<Card>` primitive is used 55
times against only 4 raw `.lf-card` usages, and `!important` appears 6 times in
27 files.

---

## 2. Screen-by-screen

### 2.1 Overview (Dashboard) — `/`

**Works.** Net worth as hero with sparkline and 6-month delta; financial health
score; cash-flow calendar preview. The information selection is genuinely good.

**Findings**

| # | Finding | Severity |
|---|---|---|
| a | Date-range control ("This month / Last month / 30 days / Year") sits *above* the hero, so the first thing the user sees is a control, not their money | med |
| b | "This month" on Aug 2 shows Income KES 0.00 / Spending KES 81.26 — technically true, useless. A month-to-date view on day 2 must either compare to same-days-last-month or default to a 30-day window | high |
| c | The onboarding checklist ("4 of 5 done") outranks all financial content and occupies the full fold. Its dismissal is client-side only — clearing storage brings it back | med |
| d | Two stat treatments on one screen: the hero's `.lf-hero-figure` and the Income/Spending/Net row | med |

**Mobile (375×812) — severe.** Measured: `document.scrollHeight = 4967px`; the
**first monetary figure appears at y=1233** on an 875px viewport. A user opening
the app on a phone sees a greeting (88px H1 wrapping to 2 lines), a wrapped
segmented control, and an onboarding card — **no financial information above the
fold, and none within the first screenful and a half.** The segmented control
wraps "This month" and "30 days" onto two lines each while "Year" stays on one,
so the four options have three different heights.

### 2.2 Transactions — `/transactions`

**Works.** The strongest screen in the product. Inline category dropdown per
row, bulk selection checkboxes, search, filters, import/export affordances.
Row density is right. Optimistic categorisation was already fixed (see
`PX_AUDIT.md`).

**Findings**

| # | Finding | Severity |
|---|---|---|
| a | No saved views / saved filters despite being the screen that most needs them | med |
| b | No column customisation, no sticky header on scroll | med |
| c | Transfers render as two separate rows ("Scheduled transfer" ×2, ±400.00) with no visual pairing — correct in the ledger, confusing in the list | med |
| d | Amount column is the only right-aligned column but shares no vertical rule with the header | low |

### 2.3 Accounts — `/accounts`

**Findings**

| # | Finding | Severity |
|---|---|---|
| a | **Text overlap, 130px** (§1.3) | high |
| b | The *empty* "Wallets" section occupies more vertical space than the account list — an empty state outranking real data | med |
| c | Cash Wallet shows **−KES 65.84**: a negative balance on a cash asset account is surfaced with no flag, warning, or explanation | med |
| d | Three stat treatments on one screen: the Assets/Liabilities/Net Worth band, the section subtotals, and the IN/OUT/NET tiles | med |
| e | The selected account's name is not a heading element — screen-reader outline for this screen is `h1 Accounts → h2 Wallets → h3 No wallets yet`. The primary content has no place in the outline | high (a11y) |

### 2.4 Budgets — `/budgets`

**Works.** Genuinely well done. Spent / Budgeted / Remaining, a period-progress
bar with "Day 1 of 31 · 30 left · On track for this period", per-category meters
with "KES 538.74 left · on track". This is the clearest screen in the product
and should be the model for the others.

**Findings**

| # | Finding | Severity |
|---|---|---|
| a | On day 1–2 of a month every category reads "on track" by construction; the pacing signal is not yet meaningful and should say so | low |
| b | "Everything's within budget" panel is a full card for one sentence | low |

### 2.5 Goals — `/goals`

| # | Finding | Severity |
|---|---|---|
| a | Card action rows misaligned by 21px (§1.4) | med |
| b | The "SAVED ACROSS GOALS / TARGET / ACHIEVED" band uses three different type sizes with three different baselines and no alignment grid | med |
| c | "19%" floats at the far right of the progress bar, ~1100px from the label it qualifies | med |
| d | Suggestion cards ("Clear your credit card balance") are the same visual weight as real goals — recommendation and commitment look identical | high |
| e | Only two headings on the entire page (`h1 Goals`, `h2 Suggested for you`); goal cards are not headings | high (a11y) |

### 2.6 Cash flow — `/cashflow`

**The weakest screen in the product.**

| # | Finding | Severity |
|---|---|---|
| a | **The same number is rendered 12+ times.** With no scheduled items the projection is flat, so Starting balance, Lowest point, Ends at, Projected low point, Balance on Sep 30 *and every day cell* all read `KES 42,283.81`. A calendar whose every cell is identical is a wall of noise that should collapse to one sentence | high |
| b | Two stat rows stacked ~200px apart present the *same figures* in *different typography* — one in the ledger duospace with letter-spacing, one not | high |
| c | **Three segmented controls on one screen** with three different scopes: `Calendar│Outlook`, `5 weeks│2 months│3 months│6 months│12 months`, and `Month│Week│Timeline` — no hierarchy indicates which governs which | high |
| d | The month grid starts Monday but Aug 2 2026 is a Sunday, so the entire first row is one populated cell in the far-right column and six empty ones | med |

### 2.7 Analytics — `/analytics`

| # | Finding | Severity |
|---|---|---|
| a | ~~**The flagship chart renders no data.**~~ **RETRACTED — this was a measurement error.** See §4 below | — |
| a′ | **Chart animation ignores `prefers-reduced-motion`.** Recharts animation is JavaScript-driven and never sees the stylesheets' reduced-motion rules, so a user who asked for less motion still gets every bar growing and every line sweeping. It also means bar shapes are not committed to the DOM until the first animation frame — so bars are absent anywhere `requestAnimationFrame` does not run (background tab, print, PDF export) | med (a11y) |
| b | **The chart violates the design system's central rule.** `CashFlowChart.tsx:32` fills Expenses with `--lf-status-danger` (carmine). `tokens.css:12-18` states carmine is reserved for genuinely wrong states and the chart ramp deliberately excludes it: *"A grocery run never deserves the same color as a failed payment."* The product's most prominent chart breaks its own most emphatic opinion | high |
| c | **Partial-month comparison presented as fact.** On Aug 2 the page reports "EXPENSES ↘ 97%" in green and "INCOME ↘ 100%" in red — comparing two days against a full month. Rendering a 2-day sample as a 97% improvement is actively misleading in a financial product | **critical (trust)** |
| d | Delta badges are full-width filled bars beneath each stat, reading as progress meters rather than deltas | med |
| e | The chart is titled "Cash flow" while a separate top-level nav item is also "Cash flow" — two different things, one name | med |

### 2.8 Coach — `/coach`

| # | Finding | Severity |
|---|---|---|
| a | `TemplateNarrator` leaked into copy (§1.6) | high |
| b | "across 1 accounts" ×2 (§1.5) | med |
| c | The same headline appears three times on one screen: briefing title, briefing body sentence, and insight card title | med |
| d | Two more segmented controls (`Today│This week│This month`, `Active│Saved│Dismissed`) — the 4th and 5th distinct implementations of this control in the product | med |
| e | Stat row uses coloured numerals (amber "1", green "2") with no legend or explanation of what the colours mean | med |

### 2.9 Debt — `/debt`

| # | Finding | Severity |
|---|---|---|
| a | **A "100 / Excellent" score displayed alongside "Based on 45% of the usual inputs" and "1 debt missing terms".** Presenting a perfect confident score computed from under half the required inputs is the most serious trust defect in the product | **critical (trust)** |
| b | "1 DEBTS" (§1.5) | med |
| c | The page renders a full analytics dashboard of `KES 0.00` (interest, fees, cost of borrowing, monthly minimums, average rate 0%) rather than a setup state. This is a *zero* state being used where an *empty* state is required | high |

### 2.10 Settings — `/settings`

| # | Finding | Severity |
|---|---|---|
| a | **Two adjacent text inputs share a single "Name" label** with no individual labels — WCAG 3.3.2 failure; a screen reader announces both fields identically | high (a11y) |
| b | Content occupies the top ~35% of the viewport; the rest is empty canvas. No max-width centring, no fill | med |
| c | The Email row (label left, value right-aligned at x≈1533) and the Name row (label left, inputs starting x≈1018) use different alignment grids | med |
| d | Two-level navigation (Account / Workspace) for six leaf items | low |

### 2.11 Bills, Recurring, Categories, Investments, Members, Billing, Notifications

Audited structurally rather than exhaustively. All inherit the systemic
findings (§1): bespoke stat tiles, bespoke headers, bespoke empty states. No
screen-specific defect rose above the systemic ones. Concrete redesign
recommendations for each are in [`04-screens.md`](04-screens.md).

### 2.12 Authentication — `/login`, `/register`, `/forgot-password`

**Works, and is the best-crafted surface in the product.** Split panel, rotating
finance quotes, passkey / Google / Apple, tasteful grid texture, clean dark
treatment. It collapses correctly to mobile (verified at 375×812).

| # | Finding | Severity |
|---|---|---|
| a | The password reveal toggle sits *outside* the input rather than inside it, shortening the field and breaking the field's rectangle | low |
| b | The quote rotates per render, so a failed login changes the quote — a subtle signal that the page reloaded rather than rejected you | low |

### 2.13 Platform Admin — `/admin/*`

**Works.** Correct guard (a tenant user hitting `/admin` gets a clean "Not
available"). Operations-flavoured IA — Customers, Recovery, Promotions, Access,
Audit — that is *better structured than the tenant navigation*.

| # | Finding | Severity |
|---|---|---|
| a | **Twelve KPI tiles in a uniform 4-column grid, all identical weight.** MRR $75, ARR $896, ARPA $15, LTV $75, Collected today $0, MTD $0, Lifetime $245, Payment success 75.0%, Workspaces 11, Active 10, Suspended 1, New 1. Nothing is emphasised, so nothing is emphasised. This is precisely the "dozens of widgets" pattern the brief rejects | high |
| b | **The console has no distinct identity.** Same surfaces, same iris accent, same type as the tenant app. Only the sidebar tint and a shield glyph differ. An operator cannot tell at a glance which system they are in — which matters when one of them can suspend a customer | high |
| c | "Updated 8:29:21 PM" — second-precision raw locale string as a freshness indicator | low |
| d | **Mobile navigation is unusable.** Measured at 375px: `admin.css:295` sets `.lf-admin-nav-link span { display: none }`, leaving **eleven unlabelled 24×32px icons** in a horizontal scroller (`scrollWidth 494 > clientWidth 375`, one link off-screen entirely). 24px is well under the 44px this same codebase defines as `--lf-touch-target`, and nothing distinguishes Invoices from Recovery but the glyph | **critical** |
| d′ | **The rail inverts with the theme.** `.lf-admin-rail` uses `--lf-bg-inverse`, which is ink in light theme and `#f6f7f9` in dark — so the dark console gets a near-white sidebar (measured `rgb(246,247,249)` on a 1280px viewport, `data-theme="dark"`). This may well be deliberate — the token is doing exactly what its name says — but it is worth an explicit decision rather than a default | low |
| e | 12 tiles × ~330px tall on mobile ≈ 4,000px of scrolling to read twelve numbers | high |

---

## 3. Cross-cutting

### 3.1 Accessibility

| Finding | Standard |
|---|---|
| Two inputs sharing one label (Settings) | 3.3.2 Labels or Instructions |
| Primary page content not in the heading outline (Accounts, Goals) | 1.3.1 Info and Relationships |
| 9.44px rendered text | 1.4.4 Resize Text (practical) |
| Admin nav links ~26px wide on mobile | 2.5.5 Target Size |
| Colour-only meaning in Coach stat numerals | 1.4.1 Use of Colour |

**Credit where due:** `tokens.css` ships a verified contrast floor, a
`prefers-contrast: more` block, `prefers-reduced-motion` handling in 7 places,
a skip link, and `--lf-touch-target: 44px`. The token layer takes accessibility
seriously; the composite layer does not consistently honour it.

### 3.2 Trust

Two findings in this audit are trust defects rather than usability defects,
and in a financial product they outrank everything else:

1. A confident "100 / Excellent" from 45% of inputs (Debt)
2. A 2-day sample reported as a 97% improvement (Analytics)

A user who catches either of these stops believing the other numbers.

*A third — an empty flagship chart — was reported here and has been retracted;
see §4.*

### 3.3 Performance

**Good.** Route-level code splitting on all 42 routes; the admin console is a
separate chunk so customers never download it; optimistic updates landed in the
PX pass; React Query with tenant-scoped keys.

**Watch:** 27 stylesheets totalling ~250KB of CSS are loaded globally rather
than per-route — a `/login` visit downloads `debt.css`, `cashflow-calendar.css`
and `admin.css`. Service-worker registration fails in dev (`sw.js` served as
`text/html`); needs verification against a production build.

---

## 4. Corrections

Two claims in this document were wrong. Both are recorded rather than quietly
edited, because the *reason* each was wrong is useful.

### 4.1 "The composite layer is missing" — overstated

§0 originally said the design system "stops at primitives" and Phase 2 listed
eight components to build. **Seven of the eight already existed** — `Stack`,
`Inline`, `Grid`, `PageHeader`, `Meter`, `EmptyState`, `Badge`,
`SegmentedControl` and `Table` are all exported from `src/ui/`, and adoption is
good:

| Component | Usages |
|---|---|
| `Card` | 125 |
| `Money` | 95 |
| `Stack` | 71 |
| `Badge` | 57 |
| `Grid` | 49 |
| `EmptyState` | 40 |
| `PageHeader` | 20 |

The error came from counting selectors without asking **where they live**. 116
selectors across six concepts looked like six missing components. Splitting
that count by file shows the opposite: for Meter and EmptyState the majority
sit in the shared `components.css`, which is what adoption looks like. Only the
labelled number was genuinely unserved — 3 shared selectors against 71
scattered across 13 feature stylesheets.

The corrected finding is narrower and more actionable: **one missing component,
not six.** `<Figure>` shipped in Phase 2; §0 has been rewritten accordingly.

The lesson is the same one as §4.2 below: a count is not a diagnosis. The
distribution was the evidence, and it was one `grep` away.

### 4.2 Retraction: the "empty chart"

This audit originally reported, as one of three headline trust defects, that the
Analytics chart rendered no data — axes, gridlines and legend drawing while bars
and line did not, with the API confirmed to be returning six months of non-zero
values.

**That was wrong, and the error was mine.** The chart works.

The audit was conducted through a headless browser pane running as a **hidden
tab**. Measured directly: `document.visibilityState === "hidden"` and
`requestAnimationFrame` fires **zero frames in 400ms**. Recharts animates bars
up from zero height via rAF and does not commit the bar shape to the DOM until
the first frame lands — so with rAF starved, the bars genuinely were absent from
the DOM, and absent from every screenshot. `<Area>` and `<Line>` emit their path
declaratively and animate a stroke-dash afterwards, which is why those rendered
and made the failure look selective and therefore real.

Setting `isAnimationActive={false}` makes all eleven bars appear immediately
with correct geometry (26×105px, 26×108px, …) and correct fills. Nothing was
broken.

Two things are worth taking from this:

1. **The finding that survives is a real one, just smaller** (§2.7a′): chart
   animation ignores `prefers-reduced-motion`, and any environment without rAF
   sees no bars. That is now fixed.
2. **A screenshot from an instrumented environment is evidence about the
   instrument as much as the product.** Every other finding in this document
   was re-checked against a DOM measurement or a source file rather than an
   image alone.

---

## 5. What to keep

A redesign that discards these would be a downgrade:

1. **The money-colour semantics.** money-in verdant / money-out ink / carmine
   reserved. This is a real opinion, correctly argued in-code, and nearly
   unique in the category.
2. **The ledger column.** Every monetary amount in a duospace face with tabular
   figures. It is the product's signature and it is *functionally* right.
3. **The token architecture.** Primitive → semantic layering in framework-
   agnostic CSS custom properties.
4. **The accessibility floor**, including the forced-contrast block.
5. **The Budgets screen**, as the reference for what a good LedgerFlow screen
   looks like.
6. **The admin IA** — Customers / Recovery / Promotions / Access is better
   thought out than the tenant nav.
7. **The auth experience.**

---

*Continues in [`02-strategy-ia.md`](02-strategy-ia.md).*
