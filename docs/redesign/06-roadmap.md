# Implementation Roadmap

Sequenced to **minimise regression risk**, which here means one thing:

> Never change the token layer and the component layer in the same commit.

The token layer is consumed by 750 selectors across 27 stylesheets. A palette
change and a markup change landing together makes every visual diff ambiguous —
you cannot tell whether a regression came from the colour or the DOM. Phases
alternate deliberately: **fix → build → adopt → swap**.

---

## Phase 0 — Truth and bugs (week 1) — **SHIPPED**

No design work. Ship the things that are simply wrong. Every item is
independently revertable.

| # | Task | Outcome |
|---|---|---|
| 0.1 | ~~Analytics chart renders nothing~~ → **honour `prefers-reduced-motion` in charts** | **Scope changed.** The original defect was a measurement error ([A§4.2](01-audit.md)). What was real: recharts animation is JS-driven and ignores the reduced-motion stylesheets, and bars do not exist in the DOM until the first rAF frame. New `usePrefersReducedMotion()` hook drives `isAnimationActive` on every series in `CashFlowChart` and `TrendsCard` |
| 0.2 | Admin mobile navigation unusable | **Fixed.** Was 11 unlabelled 24×32px icons in a horizontal scroller. Now labelled, `min-height: var(--lf-touch-target)`. Verified at 375px: 11 links, **0 under 44px** (101×44, 99×44, 69×44), with a scroll-affordance gradient |
| 0.3 | Debt score: attach the caveat, prefix `~`, label "Provisional" | **Fixed.** Renders `~100` in a dashed muted ring with a `PROVISIONAL` chip beside the band; `aria-label` states the coverage |
| 0.4 | Analytics: stop comparing 2 days to a full month | **Fixed.** `periodProgress()` detects a partial month; `DeltaBadge` takes `provisional` and withholds the good/bad colour (verified: all four tones now `null`); a basis line states "2 of 31 days … not yet like-for-like" |
| 0.5 | Accounts text overlap | **Fixed.** `.lf-acct-item-main` given `display:flex; flex-direction:column`. Verified: **0 overlapping text nodes** on the page |
| 0.6 | Remove `TemplateNarrator` from user copy | **Fixed.** New `providerLabel()` maps the internal identifier to "Written from your own figures. No AI involved." / "Written by AI from your own figures." |
| 0.7 | `plural()` helper | **Fixed.** `lib/plural.ts` (frontend) and `_plural()` (coach.py). "1 DEBT", "across 1 account". The two `detect.py` sites are guarded at ≥2 occurrences, so they were never wrong |
| 0.8 | Expenses stop being red | **Fixed.** New `--lf-chart-income` / `--lf-chart-expense` tokens. Expenses now `rgb(166,173,194)`, distinct from `--lf-status-danger` `rgb(224,89,106)`. Also caught the same violation on the dashboard forecast ("Projected spend" was carmine) |
| 0.9 | Settings: split the two name inputs | **Fixed.** Two visible `<label>`s + `autocomplete`. The original audit overstated this — `aria-label`s did exist, so it was not the 3.3.2 failure claimed; the real problem was placeholder-only *visible* labelling and a `htmlFor` pointing one "Name" label at the first of two fields |

**Verification.** Frontend suite **644 passed / 104 files** under `TZ=UTC`;
`tsc -b` clean; `oxlint` clean apart from one pre-existing warning.
`verify_palette.py` green.

**Two things found on the way:**

- **The test suite is not timezone-independent.** Five tests in
  `dashboard/metrics.test.ts` fail on any machine east of UTC (this one is
  UTC+3) and pass under `TZ=UTC`. Pre-existing, unrelated to Phase 0, but it
  means the suite is red by default for the person who wrote it. Worth pinning
  the TZ in the vitest config.
- **The backend suite cannot run locally**: the `app` Postgres role lacks
  `CREATEDB`, so every test errors at database setup. Also pre-existing.
  `hypothesis` is missing from the installed dev dependencies.

**Risk: very low.** These are defects; there is no design debate to have.

---

## Phase 1 — The measurement harness (week 2) — **SHIPPED**

Build the thing that stops regressions before touching anything visual.

| # | Task | Outcome |
|---|---|---|
| 1.1 | `verify_palette.py` into CI | **Done.** Runs in the `lint` job |
| 1.2 | Per-route DOM assertions | **Done.** [`scripts/audit_routes.py`](../../scripts/audit_routes.py) — 31 routes × 2 viewports in real Chromium: text overlap, tiny text, target size, horizontal overflow, heading outline |
| 1.3 | Type-scale assertion | **Done.** Same script: more than 7 distinct computed font sizes fails the route |
| 1.4 | Visual regression | **Approach changed** — computed-style fingerprints instead of pixel snapshots. Reasoning below |
| 1.5 | Token-bypass lint | **Done** as [`scripts/check_style_tokens.py`](../../scripts/check_style_tokens.py) rather than stylelint. Reasoning below |
| 1.6 | *(added)* **Frontend CI** | The frontend had **no CI at all** — 644 tests, `tsc` and the linter gated nothing |

### Three decisions worth recording

**1.5 — a stdlib checker, not stylelint.** The three rules needed (no literal
colours outside `tokens.css`, no `em` font sizes, no colour/type in inline
`style={{}}`) are string matching over files. stylelint would have added a
dependency tree to do that, and the repo already has a convention for exactly
this — `check_design_system.py` is a stdlib checker in `scripts/`.

**Both linters are ratchets, not walls.** There are 53 literal hexes, 29
`rgb()` calls and 2 `em` font sizes already in the tree. Failing the build on
all of them on day one gets the check disabled within a week. The current
counts are the ceiling: add one and CI fails; remove one and it asks you to
lower the ceiling. The numbers only move down.

**1.4 — fingerprints, not screenshots.** Pixel snapshots taken on macOS never
match ones rendered on CI's Linux — different font rasterisation and subpixel
antialiasing guarantee a diff on every run — so they would need a pinned
container to mean anything, and even then a diff only says *that* a page
changed.

`audit_routes.py --snapshot` instead records each route's **visual
fingerprint**: every distinct rendered colour, font size, family, weight,
radius and shadow. 62 route/viewport pairs, 1,640 distinct values, **55KB of
reviewable JSON**.

This answers the question Phase 3 actually asks. The product renders **29
distinct colours** in total. After the token swap every one of them should have
moved; any that hasn't is one of the 53 literals the token layer does not
reach, and a JSON diff names it. A pixel diff cannot.

The baseline is committed at
[`docs/redesign/snapshots/pre-meridian.json`](snapshots/pre-meridian.json).

### What the harness found on its first run

343 findings across 31 routes. **These numbers were substantially inflated —
see the correction below.**

| Kind | As first reported | Actual |
|---|---|---|
| `target-project` | 197 | **179** |
| `target-aa` | 116 | **72** |
| `overlap` | 15 | **2** |
| `type-scale` | 15 | 5 *(after the type fix)* |
| `heading-outline` | 12 | 12 |
| `h-overflow` | 3 | 2 |
| `tiny-text` | 1 | 0 *(after the type fix)* |

> **Correction (found during Phase 4.2).** The probe treated any element with a
> non-zero rect as visible. But an element scrolled out of a clipping ancestor
> still reports `getBoundingClientRect()` at its *laid-out* position, not its
> painted one — so on the transactions ledger, where the sticky wrapper clips
> ~1,200px of rows (`scrollHeight` 1866 vs `clientHeight` 646), every row below
> the fold "overlapped" the pagination footer drawn beneath the container.
>
> Chasing the first of those phantoms is what surfaced it: two `static`
> elements cannot overlap, so the measurement had to be wrong before the
> product was. `vis()` now walks every ancestor with `overflow: auto|scroll|
> hidden` and rejects elements outside its box.
>
> **13 of 15 overlaps and 46 of 118 AA target failures were phantoms.** The
> claim in Phase 1 that these were "WCAG 2.5.8 AA failures" was overstated by
> roughly 40%; the 72 that remain are real. Table-heavy routes were worst hit,
> which is why `/transactions` and `/admin/tenants` topped the list.

**Determinism mattered.** An early version reported 181 small targets on one
run and 197 on the next, because it sampled during the skeleton→content swap.
It now waits for two consecutive identical DOM shapes with no skeletons
present.

> **Correction (found during Phase 4.3).** "Two consecutive full runs produce
> byte-identical counts" was written from a sample of two, and it does not
> hold. A run taken immediately after editing source can under-count by ~2 out
> of ~340 — the settle helper waits for the DOM to stop changing shape, but a
> route whose *nested* async section swaps after the outer control count has
> stabilised can still be sampled early.
>
> Consecutive runs against a warm server do agree; a run taken right after a
> code change may not. The practical rule is **re-baseline from a second run,
> never the first**, and treat a ±2 move as suspect rather than as a finding.
> Phase 4.3 spent real effort chasing a 2-count "regression" that was a stale
> baseline. That cost is the argument for stating the limitation here.

**Exit criteria — met.** CI red on any introduced violation. Baselines
committed.

**Risk: none.** No production code changed. Two pre-existing bugs were fixed to
make the suites runnable at all: `npm run lint` was linting `node_modules` and
had never passed, and the vitest suite failed for anyone outside UTC.

---

## Phase 2 — The composite layer (weeks 3–5) — **SHIPPED, scope cut by 7/8**

**The first thing this phase found was that it was mostly unnecessary.** Seven
of the eight components listed here already existed in `src/ui/` and were well
adopted (`Card` 125 usages, `Money` 95, `Stack` 71, `Badge` 57, `Grid` 49,
`EmptyState` 40, `PageHeader` 20). Building them would have produced duplicates
of working code.

| # | Component | Status |
|---|---|---|
| 2.1 | **`<Figure>`** | **Built.** The one genuine gap |
| 2.2 | `<Stack>` `<Inline>` `<Grid>` | Already existed — `ui/Layout.tsx` |
| 2.3 | `<PageHeader>` | Already existed — `ui/Typography.tsx` |
| 2.4 | `<Meter>` | Already existed — `ui/Meter.tsx` |
| 2.5 | `<EmptyState>` | Already existed — `ui/EmptyState.tsx` |
| 2.6 | `<Badge>` `<Chip>` | Already existed — `ui/Card.tsx` |
| 2.7 | `<SegmentedControl>` | Already existed — `ui/Toggle.tsx` |
| 2.8 | `<Table>` | Already existed — `ui/Table.tsx` |

The audit's error is corrected in [`01-audit.md §4.1`](01-audit.md): raw
selector counts were read as missing components, when the distribution showed
adoption. Where a primitive exists its styles concentrate in the shared
`components.css`; only the labelled number was unserved, 3 shared selectors
against 71 scattered.

### What `<Figure>` is

[`src/ui/Figure.tsx`](../../frontend/app/src/ui/Figure.tsx) — a labelled number
with four sizes, four tones, and **certainty as a required dimension**.

```tsx
<Figure label="Net worth" size="hero" amountMinor={3914931} currency="KES" delta="▲ 154%" />
<Figure label="Rent" amountMinor={120000} currency="KES" certainty="projected" />
<Figure label="Debt health" value="100" certainty="speculative"
        confidence="Based on 45% of the usual inputs." />
```

**The type system enforces the trust rule.** `certainty="speculative"` makes
`confidence` a required prop via a discriminated union — verified by removing
the `@ts-expect-error` in the test and confirming `tsc` reports `TS2322`. The
Debt page's "100 / Excellent" from 45% of inputs is now a **compile error**,
not a code-review note.

**Alignment is structural.** Label and value rows have fixed line heights per
size, so sibling figures align without `subgrid` and without callers
remembering to match. Verified in Chromium at 1280 / 768 / 375: every visual
row shares one label top and one value top, including where the grid wraps to
2×2 on mobile.

**A seam for Phase 3.** Two new tokens — `--lf-certainty-pending` and
`--lf-certainty-projected` — point at existing values today and get repointed
at the Meridian `horizon` hue in the token swap, so no component changes then.

**Exit criteria — met.** `<Figure>` and `<FigureRow>` in `/_ui` with all sizes,
certainties and tones, in both themes. 13 unit tests. **Zero production
consumers** — adoption is Phase 4, per the fix → build → adopt → swap sequence.

**Risk: none.** Additive only; 657 tests pass, route audit unchanged.

---

## Phase 3 — The token swap (week 6) — **SHIPPED**

One PR, `tokens.css` plus two literal fixes it exposed. No markup, no component
changes.

```
--lf-ink-900   #151928 → #1a1917   blue-black → warm graphite
--lf-fog-*     → --lf-paper-*      cool white → warm paper
--lf-iris-*    → --lf-meridian-*   indigo     → teal
--lf-verdant-* → --lf-jade-*
--lf-carmine-* → --lf-vermilion-*
--lf-amber-*   → --lf-ochre-*
+ --lf-horizon-*                   new: the future only
```

**Old names kept as aliases.** 86 references to `--lf-iris-600` and friends
live outside `tokens.css`; aliasing them (`--lf-iris-600: var(--lf-meridian-600)`)
is what kept this to one file. Phase 4 migrates them as each feature stylesheet
retires. Nothing new should reference them.

### The verifier was rewritten first

`verify_palette.py` used to carry its own copy of the palette, which made it a
check on a *proposal* rather than on the product. It now **parses
`tokens.css`, resolves every `var()` chain, and checks the pairings components
actually render** — 22 text pairs, 9 non-text pairs, chart separation, per
theme. A colour can no longer regress without the check failing.

It earned that on the first run, against the *pre-swap* palette:

> **DARK chart normal: ΔE 0.0** — `--lf-chart-expense` and
> `--lf-certainty-projected` were the identical `#a6adc2`. In dark mode a
> projected amount was indistinguishable from settled spending. The swap
> resolves it: `certainty-projected` is now `horizon`, and separation goes
> **0.0 → 41.6**.

### What the fingerprint diff showed

The Phase 1 snapshot is what made this reviewable. Comparing 62 route/viewport
pairs before and after:

| Property | Distinct values | Unchanged after the swap |
|---|---|---|
| `color` | 12 | **1** |
| `background` | 17 | **2** |
| `border` | 8 | **1** |
| `shadow` | 7 | 2 (dark-theme `rgba(0,0,0,…)`, correctly untouched) |
| `radius` | 7 | **7** — not part of this phase |
| `fontSize` | 18 | **18** — not part of this phase |

Colour moved almost completely; everything outside the phase's scope is
provably untouched. That second half is the part a pixel diff cannot give you.

Cross-referencing the survivors against the 33 literal colours in the
stylesheets found **exactly three shipping in a default render**, and they
needed three different judgements:

- `admin.css:76` — `color: #fff` on a vermilion badge. A real colour. **Fixed**
  → `var(--lf-paper-000)`.
- `premium.css:54,64` — `color-mix(…, #ffffff)` lightening the button gradient.
  A real colour. **Fixed** → `var(--lf-paper-000)`.
- `auth.css:45` — `#000` inside a `mask-image`. **Not a colour**: in a mask the
  channel that matters is alpha, and tokenising it would make the mask follow
  the theme, which is exactly what it must not do. Left, with a comment saying so.

The remaining 30 literals sit on states the fingerprint does not exercise —
hover, focus, modals, admin-only branches — which is a real limit of the
technique and is stated rather than papered over.

### Breakpoints: documented, not tokenised

The plan called for `--bp-*` custom properties. **They cannot work**:
`@media (min-width: var(--bp-md))` never resolves, because media queries are
evaluated before custom properties. A `--bp-*` token would look authoritative
and silently do nothing.

So the six canonical breakpoints (480 / 640 / 768 / 1024 / 1280 / 1600) are
documented in `tokens.css` and **enforced** by a new `off-scale-breakpoint`
rule in `check_style_tokens.py`. It ratchets at 47 — the current count of
media queries using one of the other eight widths.

**Exit criteria — met.** `verify_palette.py` green in both themes. Fingerprint
diff reviewed. Zero hardcoded colours in any default render. Route audit
unchanged (no regressions), 657 tests pass, production build clean.

**Risk: medium, bounded, instantly revertable** — it is one file plus two
one-line CSS fixes.

---

## Phase 4 — Screen migration (weeks 7–12) — **4.1–4.8 SHIPPED**

One screen per PR, in descending order of traffic. Each PR: adopt the composite
components, apply the [`04-screens.md`](04-screens.md) spec, delete the
screen's bespoke stylesheet.

### 4.1 Today — done

| Change | Result |
|---|---|
| **Mobile fold contract** | First monetary figure moved from **y=1233 → y=217** on a 375×812 viewport. Target was ≤480 |
| **Horizontal overflow on `/`** | Fixed. `scrollWidth` 404 → 375. `.lf-cal-summary` was a non-wrapping flex row of two `text-lg` amounts. Route-audit `h-overflow` ratchet lowered 3 → 2 |
| **`<Figure>` adopted** | 5 figures on the page. Net worth and Financial health are `size="hero"`; income/spending/net are a `<FigureRow>`. All rows verified aligned at 375 / 1280 |
| **`CashFlowSummary` rebuilt** | Was three `<Card>`s each wrapping a local `StatTile` — three bordered boxes for three numbers in one sentence, and a fourth private implementation of the labelled number. Now one card, one `FigureRow` |
| **`HealthCard` inline style removed** | Was `<p className="lf-amount lf-amount--hero" style={{color: …}}>` — the exact bypass the token lint exists to catch |
| **Onboarding demoted** | Renders below the hero once an account and a transaction exist, and collapses to the single current step. It leads only when there is nothing else to show |
| **Segmented control** | Four options at 375px wrapped "This month" and "30 days" to two lines while "Year" stayed on one — three segment heights in one control. Now `nowrap` + scroll: **one height across all options** |
| **`.lf-hero-figure` deleted** | Retired by `<Figure size="hero">` |

**Mobile-first, properly.** The first attempt used `@media (max-width: 639px)`
and the token checker rejected it — 639 is one of the off-by-one breakpoints
the system is retiring. The header was rewritten so the narrow layout is the
default and `min-width: 640px` restores the wide one. The ratchet caught this
on its author, which is the point of having it.

**Verification.** Fold contract met at 375px; zero horizontal overflow on `/`;
figure rows aligned at both viewports; 657 tests; `tsc`, lint, build and both
palette/token gates clean; route audit shows no regressions and one
improvement.

### 4.3 Accounts — done

Every item in [`04-screens.md §3`](04-screens.md), verified in Chromium:

| Fix | Result |
|---|---|
| **One `<Figure>` treatment** | 7 figures on the page, all rows aligned. `SummaryBar`'s five `.lf-acct-summary-*` selectors gone; `AccountDetail`'s IN/OUT/NET was **the fifth private `StatTile` in the codebase** — three bordered cards nested inside the card already containing them |
| **Net worth leads** | Was Assets → Liabilities → Net worth, at two sizes separated by rules, so the headline arrived last. Now `FigureRow lead`: the answer first, the working beside it |
| **Heading outline** | Account name `<div>` → `<h2>`. Outline was `h1 Accounts → h2 Wallets` with nothing for the account being read; now `h1 Accounts → h2 Cash Wallet` |
| **Negative asset flagged** | An asset below zero renders an ochre badge — "Below zero — check for a missing deposit or a double-counted expense". Liabilities excluded: owing on a card is normal, not an anomaly. Verified firing on the seeded Cash Wallet at −KES 65.84 |
| **Wallets demoted** | Empty, it was a full-height card with icon, heading, paragraph and button — taller than the real account list beside it. Now one line: "Group accounts into wallets" |
| **Overlap** | 0 text overlaps (the Phase 0 fix holds) |

**A regression I introduced in 4.1, caught here.** The route audit flagged
`target-project` up. Cause: 4.1's `nowrap` fix stopped segmented-control labels
wrapping, which made them a uniform **38px** — while they wrapped to two lines
they had cleared 44px *by accident*. Uniform and too small is still too small.
`min-height` now uses `var(--lf-touch-target)` directly; all seven segments
measure 44px.

**Left deliberately: `.lf-amount-cents`.** `/accounts` still renders 9 font
sizes against a 7-step scale, and one rule causes five of them —
`base.css: .lf-amount-cents { font-size: 0.85em }`, which compounds against
whatever size its parent is:

| Parent | Cents |
|---|---|
| 11.10px | **9.44px** ← the product's only sub-11px text |
| 13.33px | 11.33px |
| 16px | 13.60px |
| 23.04px | 19.58px |
| 39.81px | 33.84px |

Fixing it is ~6 lines and would remove five off-scale sizes and the `tiny-text`
finding **product-wide**. That is exactly why it does not belong in a
single-screen PR: `base.css` reaches every screen, and changing type on
eleven unverified screens is the ambiguous diff this roadmap is sequenced to
avoid. It wants its own change, with a fingerprint diff either side.

### 4.2 Activity — done

**The phase started by disproving its own brief.** `/transactions` carried five
of the fifteen recorded text overlaps. Measuring the first one showed two
`static` elements reported as colliding — which is impossible, so the
*measurement* was wrong before the product was. Cause and fix in the Phase 1
correction above; the ledger had no overlaps at all.

What shipped:

| Change | Detail |
|---|---|
| **Certainty in the ledger** | A `pending` row is a charge the bank has seen but not cleared, so the amount can still change. It now carries the same ochre dotted rule `<Figure certainty="pending">` uses, plus a `PENDING` label and a screen-reader note that the amount may change. Rendering it identically to a reconciled figure was the Debt-score mistake in miniature |
| **Transfers are legible as pairs** | A transfer posts as two rows, one per account — correct in the ledger, baffling in a list, because the same money appears twice with nothing linking them. Each leg now names both ends: `Emergency Savings ⇄ Everyday Checking` |
| **Seed exercises the feature** | `seed_tenant_demo` leaves the two newest card charges pending. A workspace where every row is reconciled cannot demonstrate the treatment, and a reviewer would reasonably conclude it was broken |

**Already correct, so left alone:** the sticky header (opaque background,
`z-index: 2` — rows pass underneath, not through) and the sticky bulk-action
bar. The spec listed both as work; neither needed any.

**Deliberately not attempted.** Saved views, inline editing of amount/payee/
date, and ⌘K query syntax (`$>500`, `@account`, `#category`) are all in
[`04-screens.md §2`](04-screens.md). They are feature work, not migration —
each needs its own design pass and its own tests, and half-building three of
them inside a migration PR is how a screen ends up with three unfinished
features instead of one finished one.

### 4.4 Budgets — done

The audit called this "the best screen in the product", so the spec was two
fixes rather than a rebuild. Both landed, plus the `<Figure>` adoption.

| Change | Detail |
|---|---|
| **"Too early to tell"** | On day 2 of a month every budget is trivially on track — 3% of a limit against 6% of the clock — and the product said so in the same words it uses on day 20. A verdict that is true by construction teaches the reader to ignore the verdict. New `paceIsMeaningful()` withholds it until **3 days *and* 10% of the period** have passed; for a calendar month, day 4 is the first day with an opinion |
| **…and the lines agree** | `BudgetLineRow` said "on track" per category regardless, so the page contradicted its own summary. The remaining figure is a fact and always shows; only the verdict waits |
| **No projection from a sliver** | `projectedSpendMinor` divided by the elapsed fraction with no floor, so two days of groceries extrapolated to a five-figure monthly habit. Now returns `null` below the same 10% threshold |
| **All-clear demoted** | "Everything's within budget" was a full bordered card with a heading and a body paragraph, giving the *absence* of problems more weight than most problems would get. Now one line of tertiary text |
| **`<Figure>` adopted** | `.lf-budget-summary-stat` + `.lf-stat-label` retired; Spent leads as `size="hero"`, budgeted and remaining beside it, aligned by construction |

Four new tests cover the thresholds, including why both conditions are needed:
the day count alone would judge a 365-day budget on day 3 (0.8% elapsed), and
the fraction alone would judge a 7-day budget on hour one.

### Two shared-primitive fixes found here

Both were flagged by the route audit on `/budgets` and both fixed far more than
this screen:

- **Icon buttons were 33×44.** `.lf-iconbtn` sets its width from padding and
  inherits height from the button size, so the delete and edit affordances on
  budget and goal rows were 11px under the target. `min-width: var(--lf-touch-target)`
  took **`target-project` from 179 → 118**.
- **Checkboxes were 13×13.** The native default — half the 24px WCAG 2.5.8
  floor — on every bulk-selection surface in the product: the ledger, the coach
  feed, the admin tables. Sized to exactly 24px (not 44: a 44px checkbox in a
  dense ledger row reads as a button and costs the row height that makes a long
  ledger scannable). **`target-aa` 73 → 58.**

`accent-color` keeps the native control, so platform focus, keyboard and
high-contrast behaviour come along rather than being rebuilt out of a styled
span — which is how checkboxes usually lose their semantics.

### 4.5 Cash flow / Forecast — done

The audit's weakest screen. Every item in [`04-screens.md §4`](04-screens.md):

| Change | Detail |
|---|---|
| **A calendar renders only when the days differ** | With nothing scheduled the projection is flat, so the grid drew the same figure in all 60 cells while the summary stated it four more ways. The one thing the screen never said was the user's actual situation. New `hasScheduledActivity()` collapses it to a sentence and two actions. The figure now appears **4 times, down from 12+** |
| **One stat row, not two** | Low point and closing balance were stated on the page *and* again inside the calendar 200px below, in different typography. The page owns them; the calendar draws days |
| **One control, not three** | `Calendar│Outlook` hides when there is nothing to switch between, and the calendar's own `Month│Week│Timeline` went with the duplicate row. **3 → 1** |
| **Projections look like projections** | Lowest point and Ends at carry `certainty="projected"` and render in `horizon`; Starting balance stays settled ink. The distinction is now visible at a glance |
| **No hollow verdict** | "Your balance stays above zero across this whole window" is true of a flat line by construction — the budgets "on track on day 2" problem again. It goes with the grid |

**The fixture was the tell.** Seven tests failed, all because `CashflowPage.test.tsx`
used `days: []` — every test ran against a projection with nothing in it, the
exact state the page now refuses to draw. Fixed the fixture, and added cases
for both new behaviours, including that inflow exactly cancelling outflow is
*informative* flatness and must still render.

### Four shared-primitive fixes found here

Chasing this screen's mobile overflow uncovered four defects in shared code:

| Fix | Effect |
|---|---|
| `.lf-segmented` had **`min-width: auto`** resolving to `min-content`, and **min-width beats max-width** — so the `max-width: 100%` added in 4.1 was silently overruled. Five window options = 428px on a 375px screen | part of `h-overflow` **2 → 0** |
| `.lf-page-header-actions` could not shrink below its content | ″ |
| `.lf-grid > *` — grid items default to `min-width: auto` too, so a card holding a long amount forced its column to 400px inside a 343px track | `target-project` **123 → 63** |
| `EmptyState` hardcoded `<h3>`, skipping a level under every page's `<h1>` — a 1.3.1 failure on eight routes | `heading-outline` **12 → 0** |

The heading fix is the clearest argument for migrating screen by screen: it had
been sitting in the shared component the whole time, and it took building one
more empty state to notice.

A hero `<Figure>` also spilled into its neighbour at 375px — "KES 42,283.81"
needs ~202px and a half-width column gives 143. The headline figure now takes
its own line on mobile, and `.lf-figure-value` scrolls rather than colliding.

### 4.7 Coach / Insights — done

| Change | Detail |
|---|---|
| **The largest remaining a11y defect** | All 24 of `/coach`'s `target-aa` findings were one element: "Why am I seeing this?" at **152×20px**, repeated once per insight card. It is the affordance that makes an automated insight trustworthy, and it was the hardest thing on the card to hit. `min-height: var(--lf-touch-target)` took **`target-aa` 58 → 32** |
| **The headline is no longer said three times** | `headline = warnings[0].title`, and the summary then listed `warnings[:3]` — starting with that same item. The same sentence appeared as the headline, as the first clause of the body, and again as the top insight card. The narrator now names only the insights the headline did *not* already cover, while still counting the whole group |

Two backend tests cover the new behaviour, including that dropping the echo
must not drop the tally: with two warnings the summary still reads "2 worth a
look" and names only the unread one.

**Two audit findings did not survive contact.** A§2.8e claimed the briefing's
coloured numerals had no labels — they have always been a `<dl>` with
`<dt>Worth a look</dt><dd>1</dd>`, so 1.4.1 was already satisfied and the
colour merely reinforces the label. And converting that `<dl>` to `<Figure>`
would have *lost* semantics for the sake of consistency: term–definition pairs
are exactly what a description list is for. Left alone, deliberately.

The insight card still restates the headline. That one is correct — the card
*is* the insight the headline was promoted from, and it carries detail and
actions the headline cannot. Three occurrences down to two is the fix; one
would mean hiding the insight.

### The backend test suite runs again

Flagged in Phase 0 and unresolved since: **1,631 backend tests could not run at
all.** Three causes, all environmental:

- the `app` Postgres role lacked `CREATEDB`, so every test errored during
  database setup — `ALTER ROLE app CREATEDB`
- `hypothesis` was missing, breaking collection of `test_money_properties.py`
- `reportlab`, `pywebpush` and `pytesseract` were missing, which accounted for
  **33 of the 33 failures** once the DB was unblocked — all three are declared
  in `requirements/base.txt`; the venv was simply incomplete

**1,629 of 1,631 now pass.** The remaining two need the `tesseract` *system*
binary, which is a Homebrew install rather than a pip one and was left for the
owner to decide on.

### 4.6 Goals — done

| Change | Detail |
|---|---|
| **Suggestions stop impersonating commitments** [A§2.5d] | A recommendation rendered with the same fill, border and weight as the goals the user actually chose. Now no fill, a dashed `horizon` edge — the same vocabulary `<Figure certainty="projected">` uses — and an `IDEA` eyebrow so the distinction survives greyscale and high-contrast, where a dashed border alone would not |
| **Action rows share a baseline** [A§2.5a] | The audit measured "Set this up" at y=418 and y=397 in a two-card row, because cards sized to their content. `margin-top: auto` on the last child pins every action to the bottom of the tallest card. Verified: both at **y=446** |
| **Summary band** [A§2.5b] | Three figures in three treatments — a hero `Money`, a default `Money`, and a `<span>` carrying its size, weight and colour inline — which is exactly why they sat on three baselines. One `FigureRow` |
| **Headings** [A§2.5e] | Goal names and suggestion titles were `<div>`/`<p>`. The page's outline is now `h1 Goals → h2 Suggested for you → h3 per suggestion → h3 per goal` |
| **Forecasts look like forecasts** | The estimated completion date is a model output rendered in the same ink as the settled amounts beside it. Now `horizon`; the confidence band below it already stated its basis ("based on 83% of recent months funded") |

**The projection line the spec asked to add already existed** — `GoalForecastPanel`
renders needed/actual/planned monthly, an ETA and a banded confidence. It only
needed the certainty colour.

**Left deliberately: the meter caption.** A§2.5c wanted "19%" moved onto the
bar rather than sitting at the card's right edge. Label-left / value-right
above a full-width track is the conventional meter pattern, and `Meter` renders
it identically on Budgets, Billing and Goals. Moving it on one screen would buy
proximity at the cost of making that screen the odd one out.

### Two more measurement corrections

Both surfaced by this screen and both fixed in the harness rather than the product:

- **`type-scale` was counting floating point as design drift.** The ledger-cents
  rule derives its size from the parent, and lands a couple of thousandths off
  the token it matches — `11.1062` against `11.104`. The check now rounds to
  0.1px before de-duplicating, and **6 findings became 1**. The single survivor
  is the hardcoded `fontSize: 12` in Recharts props, deferred to 4.8 — so the
  product's type is now on-scale everywhere except that one chart prop.
- **A `secondary` figure overflowed its column at 375px.** Two columns of 143px
  cannot hold "KES 24,000.00" at the `lg` step, which needs ~173px. The mobile
  `FigureRow` minimum went 120px → 160px, dropping a phone to one column while
  a tablet still gets four. Widening the column is the right lever rather than
  shrinking the type: the amount *is* the content.

### 4.8 Analytics / Trends — done

Most of `04-screens.md` §6 landed in Phase 0 (expenses off the error colour,
the partial-month comparison, reduced-motion charts). What was left:

| Change | Detail |
|---|---|
| **The last off-scale type value** | Eight chart call sites passed a bare `fontSize={12}` (one an `11`). Recharts renders that as an SVG presentation attribute, so `var(--lf-text-xs)` cannot be used and it has to be a literal number. New `CHART_TICK_FONT_PX`, and **`chartTheme.test.ts` parses `tokens.css` and fails if the two ever disagree** — verified by drifting it back to 12 and watching the test fail. `type-scale` **1 → 0** |
| **Deltas stopped impersonating progress bars** [A§2.7d] | They sat *below* each value in a flex column, which stretched an `inline-flex` pill to the card's full width. `ComparisonCards` is now a `FigureRow`, and `Figure` puts the delta beside the value where it cannot stretch |
| **"Cash flow" means one thing** [A§2.7e] | The chart was titled "Cash flow", which is also a top-level destination. It is a month-by-month comparison of in against out; `/cashflow` is a forward projection. Retitled "Income vs expenses" |

**Where `var()` does work**, five call sites already used it — `wrapperStyle`
and `contentStyle` are real CSS objects. The remaining literals were converted
too, so the distinction is now consistent rather than accidental.

### A cascade collision, of exactly the kind the audit was about

`.lf-delta` had **two definitions**: a filled pill in `dashboard.css` keyed off
`--up`/`--down` modifier classes, and a plain tone-coloured span in
`analytics.css` keyed off `data-tone`. Same class name, two conventions, and
whichever stylesheet loaded last decided what *both* looked like — which is how
the analytics deltas ended up wearing the dashboard's pill and reading as
progress bars.

One definition in `components.css` now, on `data-tone` to match
`.lf-figure[data-tone]`, with `HeroCards` converted off the modifier classes.

> A process note: removing the two duplicates and adding the replacement were
> separate shell commands, and the one adding it silently failed on a `cd` —
> leaving `.lf-delta` with no definition at all for a few minutes. Caught by
> grepping for the surviving rule rather than by assuming the edit landed.
> Verifying a removal is not the same as verifying the replacement.

### 4.i Interlude — the ledger-cents type fix

Not a screen. `base.css` reaches all of them, which is exactly why it was held
out of 4.3 and given its own change with a fingerprint diff either side.

**The rule:** `.lf-amount-cents { font-size: 0.85em }`. An arbitrary ratio, so
cents landed *between* token steps, and every amount size spawned a size that
existed nowhere else. Five of the nine distinct font sizes on Accounts came
from this one declaration — including the 9.44px that was the only sub-legible
text in the product.

**What it exposed.** Fixing the ratio to `1/1.2` only lands on the scale if the
scale is uniformly 1.2 — and it wasn't. `xl → 2xl` was a 1.44 jump. Three
stylesheets had already worked around the gap by reaching for
`var(--lf-text-3xl, 2rem)`, a token that never existed, so all three silently
rendered at a hardcoded 32px.

**The fix, in three parts:**

1. `--lf-text-2xl: 2.0736rem` fills the gap; the old 2.488rem hero step becomes
   `--lf-text-3xl`. All 11 consumers repointed first, so **no rendered size
   changed**.
2. `.lf-amount-cents: max(var(--lf-text-xs), 0.8333em)` — exactly one step,
   floored so it can never go sub-legible. Documented in
   [`03-design-system.md §3.1`](03-design-system.md) as the system's single
   sanctioned relative size, with the argument for why it earns the exception.
3. The two other stray `em` sizes removed (`.lf-sort-caret`).

**Measured, product-wide:**

| | Before | After |
|---|---|---|
| `tiny-text` findings | 1 | **0** |
| `type-scale` findings | 14 | **5** |
| Distinct font sizes across 62 route/viewport pairs | 18 | **15** |
| Bare `em` font sizes | 2 | **0** |

The fingerprint diff removed nine off-scale values (9.44, 11.33, 13.60, 16.32,
19.58, 23.50, 27.20, 32, 33.84px) and added six, every one on a token step —
while **colour, background, radius and shadow came back 100% identical**. That
second half is what made a `base.css` change reviewable: proof it was purely a
type change with no side effects.

Baseline: [`snapshots/post-type-scale.json`](snapshots/post-type-scale.json).

**Still off-scale:** a `12px` on `/` and `/analytics`, from eight sites
hardcoding `fontSize: 12` in Recharts props across four screens. That is chart
typography and belongs to 4.8.

### Remaining

| Order | Screen | Deletes |
|---|---|---|
| ~~4.1~~ | ~~**Today**~~ | ✅ |
| ~~4.2~~ | ~~**Activity**~~ | ✅ |
| ~~4.3~~ | ~~**Accounts**~~ | ✅ |
| ~~4.4~~ | ~~**Budgets**~~ | ✅ |
| ~~4.5~~ | ~~**Cash flow**~~ | ✅ |
| ~~4.6~~ | ~~**Goals**~~ | ✅ |
| ~~4.7~~ | ~~**Coach / Insights**~~ | ✅ |
| ~~4.8~~ | ~~**Analytics / Trends**~~ | ✅ |
| 4.2 | **Activity** | `transactions.css` (44) |
| 4.3 | **Accounts** | `accounts.css` (36) |
| 4.4 | **Plan — Budget tab** | `budgets.css` (23) |
| 4.5 | **Plan — Forecast tab** | `cashflow-calendar.css` (81) |
| 4.6 | **Goals** | `goals.css` (73) |
| 4.7 | **Insights — Briefing** | `coach.css` (69) |
| 4.8 | **Insights — Trends** | `analytics.css` (39), `insights.css` (33) |
| 4.9 | **Debt** | `debt.css` (97) |
| 4.10 | **Investments** | `investments.css` (25) |
| 4.11 | **Settings** | `settings.css` (53) |
| 4.12 | **Remaining** | `billing.css`, `camera.css`, `polish.css`, `premium.css` |

**Today first** because it is the highest-traffic screen and the fastest
feedback on whether the language works — and it delivered that feedback: the
`<Figure>` API needed no changes to cover five real call sites, which is the
signal that Phase 2's design settled correctly. **Debt late** because it has
the most selectors and the least traffic.

**Note on `dashboard.css`.** 4.1 retired the selectors the migration actually
replaced rather than deleting the file wholesale. The rest of it still serves
components this PR did not touch (`.lf-catbar-*`, `.lf-row-*`, `.lf-due-pill`,
the disclosure toggle). Deleting a stylesheet is the *result* of migrating
every component that uses it, not a step that can be taken first.

`polish.css` and `premium.css` are deleted, not migrated — they are corrective
layers whose corrections belong in the components.

### 4.9 Debt — done

The score treatment landed in Phase 0 (`~100`, dashed ring, PROVISIONAL chip),
so what remained was `04-screens.md` §7's other item — and it turned out to
have a defect underneath it that was not a display problem at all.

**The zero grid** [A§2.9c]. A debt with no terms recorded carries `apr = 0` and
`minimum_payment_minor = 0`, because there is nothing else it could carry. Both
cards then rendered those zeros as findings: *"Average rate 0% · Monthly
minimums KES 0.00"* in the same weight as the ledger total beside them, and a
whole card reading *"Cost of borrowing this year: KES 0.00"*. The last one is
the most misleading statement the product could make — it tells someone
carrying a balance that carrying it is free — and it was the **default state
for any debt whose terms had not been entered yet.**

The fix is one idea applied in four places: *a figure appears only when its own
input was measured.*

| Where | Before | Now |
|---|---|---|
| Summary metrics | `Average rate 0%`, `Monthly minimums 0.00` | Each figure gated on its own input; with neither recorded, one sentence saying so and an **Add terms** button |
| Borrowing cost | `KES 0.00 / 0.00 / 0.00` | "Not yet known. Interest and fees come from each debt's terms, not from your transactions" |
| Partial data | Figures shown bare | "Terms recorded for 1 of 3 debts — these figures cover those only" / "At least this much" |
| Analytics metrics | Rendered like settled totals | `certainty="projected"` — every figure in that card is simulator output |

`priced_count` (debts with a profile) ships on both payloads, mirroring the
`unpriced_count` the investments module already had for the same reason.

### The display bug was hiding an arithmetic one

`weighted_apr` averaged over **all** debts. An untermed debt contributes
`apr = 0` to that average, so *adding a credit card you had not entered terms
for made your borrowing look cheaper.* Two equal balances, one at 20% and one
untermed, reported 10% — a rate describing neither debt. It now averages over
the priced debts only, and `priced_count` says how many that was.

The same conflation appeared a third time: the "N debts missing terms" alert
fired on `apr <= 0`, which calls a **recorded 0% promotional card** missing.
A rate of zero is a rate. The predicate is now "no profile, or no minimum to
simulate against" — the two things that actually block a payoff plan.

### Two things I introduced and had to take back out

- **Redundant copy.** With nothing priced, the card explains the gap *and* the
  backend alert said "1 debt missing terms" 60px below it. Same fact, twice.
  The alert is filtered when the card has already made the point, and kept when
  only some terms are missing — there the card's note is an aside and the alert
  is what names the cost to the payoff plan.
- **A comment asserting something false.** I wrote that `debt_views` had no
  ordering and "fixed" it. It sorts by balance descending, and always did.
  Reverted both the claim and the redundant frontend sort. Reading the last
  line of the function before describing it would have cost nothing.

### WCAG 1.4.1 on the payment-split chart

The caption read *"Green reduces what you owe. Red and amber don't."* — which
names three bands by hue and nothing else. Under deuteranopia it conveys
nothing. The test covering it asserted that exact sentence, under a comment
claiming the point was "stated rather than left to the colours".

Stacking order is a colour-free encoding and was already load-bearing:
*"Each bar stacks principal at the bottom, then interest, then fees. Only the
principal reduces what you owe."* A `<Legend>` names each band, and the second
chart gained one too — it had been two unnamed curves. The test now asserts the
order-based phrasing **and** that no colour name appears.

### A guard that was never wired up

`tsconfig.app.json` excludes test files, so `tsc -b` never checked a single
fixture. The `typecheck:test` script existed and nothing ran it; it had drifted
into four failures where goal fixtures were missing fields `SavingsGoal` had
since gained. My own two fixtures were missing `priced_count` and compiled
fine. **A fixture that no longer matches its type has quietly stopped testing
what it claims to.** Fixed, and added to CI.

**Stylesheet:** 99 selectors → 89. `.lf-debt-total`, `.lf-debt-interest-note`,
`.lf-borrowing-amount` and both `dt`/`dd` pairs were this page's private
reimplementation of a labelled number; the mobile column-count override went
too, since `.lf-figure-row` already handles it the same way everywhere.

**Verified:** 6 new frontend tests on the summary card, 3 on borrowing cost,
3 backend tests pinning the rate basis and the recorded-0% case; 677 frontend
tests, 1,632 backend; route audit unchanged over two runs; the live page
checked in both states, with terms added to the demo card mid-check so the
priced path could be seen rather than assumed.

---

### 4.10 Investments — done

The spec for this screen (`04-screens.md` §9) had four items. Three were right.
The fourth said returns should render `speculative` "until cost basis exists",
citing `PRODUCT_AUDIT.md §1.4` — and **cost basis does exist**, computed per lot
from the ledger. §1.4 predates the module being built. I had cited an audit
finding into a recommendation without re-reading the code it described.

### The real certainty defect, which nothing had named

`latest_price_minor` returned a quote's price and **threw away its date.**

Quotes in this product are entered by hand — there is an "Update prices"
button, not a market feed. So "market value" is only ever as current as the last
time someone typed a number in, and the page presents it under *"what you hold,
what it cost, and what it's worth today."* A quote from March and one from this
morning rendered identically, in the same weight, with no way to tell them
apart. On the seeded portfolio that is a valuation **132 days old** described as
today's worth.

| Change | Detail |
|---|---|
| Date carried through | `latest_price` returns `(price, as_of)`; `priced_as_of` on every holding, `priced_as_of` + `stale_count` on the summary |
| Total dated by its **oldest** input | Not the newest. One symbol updated this morning must not present a portfolio last valued in March as today's worth |
| Certainty encoded | Market value and total return `projected`; cost basis, realised gains, dividends `settled` — the distinction the card's docstring had described all along and nothing on screen carried |
| Per-row culprit | "at Mar 24 price" beside the holding. The summary says the total is stale; without this the reader is told that and given no way to find which position caused it |

**No arbitrary staleness threshold.** Any "older than N days" rule would be
invented. Either the prices are today's or they aren't; if they aren't, the date
is stated and the reader judges.

### The donut, and why a six-step ramp is expressible when six categories were not

`AllocationChart` was a donut over a six-colour categorical ramp. Three faults
stacked:

1. It read `var(--lf-chart-6)` — **a token that does not exist.** Six or more
   slices handed recharts an invalid `fill`.
2. Identifying a slice meant matching its colour to a legend. Phase 2 already
   established that a six-way categorical set cannot hold separation under
   deuteranopia at these contrast constraints.
3. Angle and arc area are judged far less accurately than length.

One stacked bar fixes all three. The interesting part is the colour argument:
a **categorical** colour must be *identified*, so its floor is set by
identification (ΔE 20). A **sequential** ramp runs largest-first along one bar,
directly labelled beneath in the same order — position carries the identity, and
colour only has to show where one segment ends and the next begins. That is a
*discrimination* threshold, and 4.0 is a comfortable multiple of the ~2.3 JND.
Weaker floor, different job.

`--lf-ramp-1..6` is now gated in `verify_palette.py` on both counts. The first
draft failed the second one: two of six steps sat below 3:1 on white, so the
smallest slices of an allocation bar were effectively invisible. Retuned to
3.13:1 minimum, which costs the lightest adjacent step some separation
(ΔE 9.5 → 6.5) and is the right trade.

### A defect that only existed once there was data

The route audit went **heading-outline 0 → 2** after I seeded a portfolio.
`.lf-allocation-title` was a hardcoded `<h3>` sitting directly under the page
`<h1>`, while the sibling "Holdings" section beside it was correctly an `<h2>`.
Pre-existing, invisible for as long as the page had nothing to render. Fixed
with the same `level?: 2 | 3 | 4` prop `EmptyState` got in an earlier phase.

**The empty-state blind spot is worth naming:** every route the audit visits
with no data underneath it is a route the audit is barely checking. The Debt
page had the same shape — its worst defect only appeared once a debt existed.

### The 4.9 guard earned itself back immediately

`typecheck:test` — wired into CI one phase ago — caught all three investments
fixtures missing `priced_as_of` / `stale_count`. Before that phase they would
have compiled, and three test files would have quietly stopped covering the
field this phase exists to add.

**Stylesheet:** 25 selectors → 28, the only increase in Phase 4 — the ramp bar
is new UI, and it replaced a recharts `PieChart` rather than a stylesheet.
`.lf-portfolio-value` and both `dt`/`dd` pairs went to `Figure`; the file's
`max-width: 767px` block went with them, since `.lf-figure-row` already handles
narrow screens identically everywhere.

**Verified:** 10 new frontend tests, 3 backend; 686 frontend, 1,635 backend;
palette gates the new ramp in both themes; route audit back to zero regressions;
the live page checked against a seeded 7-holding portfolio carrying one
deliberately stale quote.

---

### 4.11 Settings — done

The settings shell was already the strongest in the product — `SettingsSection`,
`SettingsRow`, `DangerZone`, `SettingsAdvanced` were all in place, and A§2.10a
(two inputs under one label) had been fixed in Phase 0 with a comment explaining
why. What was left was structural, plus the one genuinely new behaviour Phase 4
adds anywhere.

### One grid per section, not one per row [A§2.10c]

`.lf-settings-row` was `display: flex; justify-content: space-between`. That
right-aligns every control, but the boundary between label and control falls
wherever each row's own content happens to end — six rows, six boundaries,
nothing for the eye to travel down.

The section owns the columns now and rows are `display: contents`, so the row
box dissolves and both halves become items of one grid. Measured on
`/settings/preferences`: **every label ends at x=855 and every control ends at
x=1191**, across two sections and six rows. Anything that is not a row — a
banner, the save status, the advanced disclosure — spans `1 / -1`.

**Dead space** [A§2.10b]: `max-width: 720px`, left-aligned to the nav column. At
1280px the unbounded version put a toggle 900px from the text it belonged to.

### Autosave, and the three ways it goes wrong

Only one panel still had a `Save changes` button; everything else already saved
on change. So "Settings is the canonical autosave surface" came down to
`ProfilePanel` — small enough to do properly.

| Failure | Guard |
|---|---|
| Saving on mount | A `committed` ref holding what the server is known to have; no write until the value differs from it |
| Losing an edit inside the debounce window | `onBlur` flushes immediately. Tabbing away and navigating is otherwise a silent discard — the failure that makes people distrust autosave |
| A stale response reporting success over a newer one | A sequence counter; only the newest response may set the status |

**Autosave without a status indicator is strictly worse than a button** — the
button at least told you when your work was committed. `SaveStatus` is a shared
primitive: `role="status"` for the confirmation (it must not interrupt typing),
`role="alert"` plus a retry for the failure (it must). It reserves its line
whether or not it has anything to say, so confirming a save never nudges the
panel — a layout that jumps at the moment of confirmation undermines the
confirmation.

Verified live: idle at 150ms, "All changes saved" after the debounce, and the
demo user's name restored to what it was.

### Where the spec was wrong: flattening

A§2.10d wanted the two nav groups collapsed into one list, because "six leaf
items don't need two levels". That counts the items without asking what the
levels carry. The groups are **scope** — what changes for you, versus what
changes for everyone in the workspace — which in a multi-tenant product is the
most consequential property a setting has. Flattening makes renaming yourself
and renaming the workspace read as the same kind of act, to save two lines.

Kept, and relabelled `Account`/`Workspace` → **`Your account`**/**`Whole
workspace`** so the grouping states its meaning rather than leaving it inferred.

### The last inline style literal

`background: "#fff"` on the MFA QR container. Not an oversight — a QR code is
black modules on a light quiet zone, and a phone camera cannot resolve it on a
dark surface. So the fix is not to tokenise it away but to **name the reason**:
`--lf-surface-scannable`, identical in both themes, documented as the one place
where not following the theme is correct. `inline-style-literal` is now **0**,
down from 2 at the start of Phase 4.

Three inputs in `SecurityPanel` carried `aria-label` and a placeholder but no
visible label. That was the real finding behind the audit's overstated
Settings a11y claim: the labels existed for screen readers, and a sighted user
lost the field's name the moment they typed the first digit. WCAG 3.3.2.

**Off-scale breakpoints:** 46 → 43. This file's `760px`/`560px` became `768px`
and `640px` — within 1% and 14% of the originals respectively, and both on the
scale everything else uses.

**Stylesheet:** 53 selectors → 63. Up, and honestly so: the autosave status,
its retry affordance, the scannable plate and the paired-field wrapper are all
UI that did not exist before. The row layout itself lost rules — its flex block
and its own media query are gone into the section grid.

**Verified:** 7 new autosave tests (including the mount guard and the
out-of-order response), 694 frontend tests, palette and token gates clean, route
audit unchanged, alignment measured in the browser rather than eyeballed. The
unconfirmed TOTP enrolment created while checking the QR plate was deleted
afterwards.

**Note on fake timers:** the autosave tests run on real timers against the real
800ms debounce. `vi.useFakeTimers()` deadlocked every interaction to the 5s test
timeout — `userEvent` and testing-library's `waitFor` each drive their own
scheduling and neither yielded. A second per case is worth testing the timing
that ships.

---

### 4.12 The remainder — done

`billing.css`, `camera.css`, `polish.css`, `premium.css` — four files with no
screen of their own. Reading them turned the phase into something more useful
than a tidy-up: a **whole-system dead-selector sweep**, since the same question
("does anything actually render this?") is worth asking everywhere at once.

**68 selectors across 13 stylesheets matched nothing in the codebase.** Most
were the bespoke figure implementations that `Figure` replaced in 4.1–4.11 —
`lf-acct-summary-*`, `lf-cashflow-stat-*`, `lf-compare-*`,
`lf-budget-summary-stat*`, `lf-goal-summary-stats`. The rest were genuinely
abandoned: a whole CSS bar-chart system (`.lf-bars`, `.lf-bar-track`,
`.lf-bar-fill--1..5`) superseded by `lf-catbar-*`, a `.lf-tip` tooltip nothing
ever used, `.lf-saved-flag` and its keyframes, `.lf-meter` (the `Meter`
component renders `lf-meter-row/-track/-fill` and never the bare class).

**Two duplicate definitions**, the same cascade collision as `.lf-delta` in 4.8:
`.lf-bar-track` in both `components.css` and `premium.css`, `.lf-goal-ms-fill`
in `goals.css` *twice* and `polish.css` once. All dead — `MilestoneTrack`
renders `-line`, `-dot` and `-label`, never `-fill`.

### Two refinements the sweep forced

*Comments are not code.* The first detector run reported 55 dead classes; three
of them were class names **inside comments I had written in earlier phases**
explaining what had been removed. Stripping comments before extracting selectors
dropped it to 52. Instrument before finding, again.

*A compound selector dies with any one of its classes.* `.lf-table
.lf-col-balance` kept passing a "does any class here live?" test because
`lf-table` lives — but for the selector to match, **every** class in it must be
on some element, and nothing carries `lf-col-balance`. The stricter rule is the
correct one.

### I broke twelve stylesheets, and the fingerprint harness caught it

The removal script rebuilt each rule's selector list with `",\n".join(...)`
**unconditionally** — including for rules it was not modifying. Two consequences:

1. It split on commas inside the **comment above** each rule, because the text
   before a `{` includes any preceding comment. 141 comment lines were broken
   mid-sentence across 12 files.
2. Worse: where a dead selector shared a comma-fragment with the tail of that
   comment, dropping the fragment **took the comment's `*/` with it** — so the
   comment swallowed the following rule. Nine rules were commented out this way.
   One of them was `.lf-section-title`.

This was caught by the computed-style fingerprint I snapshotted before starting:
`/coach` lost `19.2px` from its rendered font sizes, at both viewports. Nothing
in `tsc`, the linter, 694 unit tests, or the route audit's own thresholds
noticed — a valid stylesheet that silently stops applying a rule is invisible to
every one of them.

Repair was mechanical because the damage was: the joins inserted `,\n` before
fragments that had been `.strip()`ed, so every introduced line began at column 0
while genuine comment lines are indented. 141 lines rejoined on that signature,
nine comment terminators restored by hand, and the eight orphaned declaration
blocks (which belonged to correctly-deleted rules) removed.

**No selector was lost that should have survived, and no rendered value moved:**

```
0 of 62 route/viewport fingerprints differ from before the sweep
  (1,703 distinct rendered values, confirmed on a second run)
```

That is the whole argument for having built the harness in Phase 1. A change
that touches 13 stylesheets and deletes 68 selectors is exactly the change no
one can review by eye, and "the tests pass" would have shipped a page with a
missing heading style.

**The lesson I would keep:** a script that edits code must not rewrite the parts
it isn't changing. Had the join been conditional on actually having removed
something from that selector list, none of this would have happened.

**Totals:** 1,274 selectors remain across all stylesheets, **zero** of them
unreferenced. `literal-rgb` 29 → 28, `off-scale-breakpoint` 43 → 41,
`inline-style-literal` 0.

---

## Phase 4 — complete

| Metric | Start of Phase 4 | Now |
|---|---|---|
| `type-scale` findings | 15 | **0** |
| `heading-outline` | 12 | **0** |
| `h-overflow` | 3 | **0** |
| `tiny-text` | 1 | **0** |
| `overlap` | 15 | 2 |
| `target-aa` | 116 | 32 |
| `target-project` | 197 | 63 |
| `inline-style-literal` | 2 | **0** |
| Unreferenced CSS selectors | 68 | **0** |

*Phase 6 then took `overlap` to **0** and `target-aa` to 31 — a single latent
bug in the mobile table reflow had been producing the last two overlaps since
the baseline was first taken.*

With the standing caveat from Phase 1: roughly a third of the `overlap` and
`target-*` reduction came from **correcting false positives in the harness**,
not from changing the product. That distinction is recorded per-phase above and
should not be quietly dropped when these numbers get quoted.

---

**Exit criteria per PR.** Bespoke stylesheet deleted. Snapshots reviewed. Route
assertions pass. No new selectors matching the `<Figure>` guard.

**Risk: low per PR, and each is revertable in isolation.** This is why it is
twelve PRs and not one.

---

## Phase 5 — Navigation and IA (weeks 13–15)

The riskiest phase, so it lands last and behind a flag.

| # | Task |
|---|---|
| 5.1 | New route structure + redirects from all 12 retired paths |
| 5.2 | Rail with live values and pinned views |
| 5.3 | Tabbed `Plan` and `Insights` |
| 5.4 | Mobile bottom bar with centre `+` |
| 5.5 | ⌘K extended to actions and query syntax |
| 5.6 | `[data-product="platform"]` admin identity + dashboard restructure |

**Ship 5.1–5.4 behind a per-user flag** with the old nav available. IA changes
are the one category of redesign that measurably breaks habitual users; a flag
converts a gamble into a measurement. Watch: time-to-first-action, Activity
visits per session, support volume mentioning "can't find".

**Exit criteria.** Every retired path redirects with the right tab preselected.
Flag defaults on after two weeks of clean metrics.

**Risk: high on 5.1–5.3.** Mitigated by the flag and by redirects.

---

## Phase 5 — Navigation and IA — complete

The IA change ships **behind `navV2`, off by default**, with a switch in
Settings → Preferences. Flag off, the product is byte-for-byte what it was: the
21-item rail, every old route rendering its own page, and — deliberately — not
one extra network request, because the rail metrics are gated on the flag too.

### 5.1 Route structure and redirects — done

Eight retired paths, each redirecting **to the right tab**, not to a generic
hub:

```
/transactions → /activity          /coach     → /insights?tab=coach
/budgets      → /plan?tab=budgets  /analytics → /insights?tab=trends
/bills        → /plan?tab=bills    /reports   → /insights?tab=reports
/recurring    → /plan?tab=recurring
/cashflow     → /plan?tab=cashflow
```

Two details that decide whether a redirect is a kindness or an annoyance:

- **`replace`**, so the retired URL leaves no back-stack entry. Without it,
  Back from `/plan?tab=bills` returns to `/bills`, which forwards again — the
  trap where Back appears broken.
- **The incoming query is merged and wins.** `/transactions?category=abc` is
  somebody's saved filter; arriving at `/activity` without it would silently
  show them everything instead.

`/insights` is the one contested name — it *was* the anomalies page and now
belongs to the hub that made anomalies a tab — so the flag decides which
component that path renders.

### 5.2 Rail with live values — done; **pinned views not done**

`Accounts 39.1k`, `Goals 22%`, `Plan ⚠ 2`. The highest-leverage navigation
change available and nearly free, since the data is already in the query cache
for the dashboard. Each figure carries a visually-hidden sentence, because
"Accounts 39.1k" read aloud is not one.

**One metric from the spec was dropped rather than built.** §3.1 sketched
`Activity 12` — transactions needing review. There is no review state in the
data model: no flag, no triage queue, nothing that counts. That number would
have had to be invented, on the navigation surface, in a product whose Phase 4
was spent removing invented numbers. Activity carries no metric.

Absent, never zero: a rail reading `Plan 0` while bills are still loading makes
a claim about someone's week that it cannot support.

**Pinned views — done.** A pin is a **named URL**, nothing more, and that is
the whole design: any state the app can put in a location is pinnable, and no
screen needs to know pinning exists. The alternative — a bespoke "saved filter"
model per feature — is how this kind of thing rots.

The control lives in the topbar because a pin is a property of the *location*,
and the shell is the only thing that always knows the location. Naming is a
step rather than a silent default, because the point of a pin is recognising it
later: `Activity · filtered` is a bad rail item, `Groceries this month` is the
one worth having. The suggestion is pre-filled, so the common case is still
type-nothing-and-Enter.

Capped at eight — a rail of pins is a rail nobody scans — and the store is
validated on read rather than trusted, because the key is user-writable and a
malformed pin must not be able to take down the shell that renders on every
route. A `to` that is not a local path is discarded outright.

### 5.3 Plan and Insights as tab hubs — done

Four routes each collapse into one destination, reusing the existing page
components unchanged apart from an `embedded` prop that suppresses their
`PageHeader` (two `<h1>`s on one route is a broken outline — the exact defect
the route audit catches).

The tab lives in the query string, so it is linkable and bookmarkable and is
what the redirects target. `?tab=budgets` is normalised away, so `/plan` and
`/plan?tab=budgets` are not two URLs for one place.

The Cash flow tab immediately justified the merge: its empty state reads *"no
bills or recurring income are set up yet"* — and Bills is now one tab away
instead of one navigation away.

### 5.4 Mobile bottom bar with a centre verb — done

`Today · Activity · ⊕ · Plan · Insights`. The old rail listed "Quick Add" and
"Scan Receipt" as *places*; the bottom bar is a toolbar, which is exactly where
a verb belongs. `⊕` opens a sheet with the four things people open the app to
do. Built on `Modal` (a native `<dialog>`), so focus containment and
Esc-to-close come from the platform.

### 5.5 Command palette — the part that mattered is done

**The one real cost of 21 destinations → 8 is that "bills" stops being a
place.** So every tab is registered as a first-class jump target: typing
`bills` still matches in one keystroke and lands on `/plan?tab=bills`, labelled
*In Plan*. The palette is what stops a flatter rail costing anybody speed, and
it is the reason this IA change is survivable for existing users.

**Sigils — done.** `>` actions, `@` accounts, `#` categories, `$` amounts. With
no sigil the palette still searches everything, which is right for the common
case; the sigils are for when you already know the *kind* of thing you want.

`$` is the one that earns its keep, because there was no way to ask the
question at all: `$>500`, `$<20`, `$100-250`. It maps onto
`min_amount_minor` / `max_amount_minor`, so the filter runs **on the server
against the whole ledger** — a client-side version would filter whatever page
happened to be loaded and quietly answer a different question. A bare `$120` is
read as *about* 120 (±10%), because an exact-cent match almost never finds
anything and the intent is a lookup.

**Recent and frequent — done.** Alphabetical order is a property of the list,
not of the user. A per-command tally ranks matches, with frequency **decayed by
age**: halving every 30 days, so a burst of use from six months ago fades
instead of outranking this week's habit forever. Sorting is stable, so an
unused palette looks exactly as it was designed to.

### 5.6 Platform console identity and dashboard — done

**The console is not the customer app with a different logo.** Cool slate where
the product is warm paper, signal amber where it is meridian teal, 6/8px
corners where it is 16, 60–80ms motion where it is 200. An operator with the
power to suspend somebody's account must never be one glance away from thinking
they are in their own budget.

The mechanism is the point: `[data-product="platform"]` **reassigns the same
semantic tokens** rather than adding new ones, so every screen, component and
chart in the console inherits the identity without a single component knowing
the console exists. It is set on `<html>`, not on a shell element, because
`<dialog>` promotes to the top layer and portalled content escapes the subtree.
It is removed on unmount, which matters just as much — otherwise an operator
who leaves keeps the control room's palette in their own workspace, and now the
*customer* app is the one in disguise.

**`verify_palette.py` gates it as a third and fourth theme** on the same floors
as the other two. An unverified palette is how a control room ends up with 2:1
body text.

**Dashboard restructure.** Sixteen equal KPI cards in three equal grids asked
the operator to decide what mattered on every visit. It does not vary: the
exception panel answers "is anything broken?", then MRR is the number the
console exists to report, and everything else is context for it — ARR/ARPA/LTV
and the collection figures as dense inline facts, the estate as a column of
counts. Sixteen equal tiles is not a dashboard, it is a data dump with rounded
corners.

The sparkline draws the real `revenue_series` report, not a decorative squiggle,
and is absent rather than flat below two points.

### The defect I reintroduced, three phases after fixing it

The MRR delta first rendered **−100%**.

`revenue_series`' final point is the month *in progress*, and I compared it
against a completed month. That is precisely the partial-period defect the
Analytics screen was rebuilt around in Phase 4.8 — and it is easy to
reintroduce because the arithmetic is correct and only the basis is wrong,
which no type system or test suite I have will catch. It now compares the last
two **complete** months and says so inline: *"+300.0% vs prior full month"*.

Worth recording as a pattern rather than an incident: **every time a figure is
compared to another figure, the question is what basis each was measured on.**
That has now produced a defect on Analytics, on Debt, on Investments and here.

### The flag is honest but not sufficient

`navV2` lives in `localStorage`. That is enough for an opt-in preview and
nothing more: **there is no server record of who is in which arm, no way to
enrol a percentage, and no way to switch it off remotely.** The exit criteria
above — time-to-first-action, Activity visits per session, support volume
mentioning "can't find" — need the flag on the user model with the API
reporting it. Shipping the local flag and calling the measurement done would be
the same species of error as a figure with no data behind it.

### Two harness corrections this phase forced

**A real defect in new UI.** `.lf-tab` was 38px tall — under the 44px floor —
which nobody noticed while tabs were a secondary control on two screens. They
are the primary navigation *inside* Plan and Insights now. Fixed, and the fix
lowered `target-project` **63 → 61** by repairing the pre-existing tabs
elsewhere too.

**Double-counting I introduced.** Adding `/activity`, `/plan?tab=bills` and
`/insights?tab=reports` to the audit inflated the counts by 37 — every one a
second sighting of a control already counted at its legacy path. The ratchet
measures defects, not routes; slack like that is where a real regression hides.
The audit now visits each *page* once and adds only the hub chrome, plus a
second pass with the flag seeded so the flagged `/insights` is checked at all.

**And a check that was never checking.** `npx tsc --noEmit` resolves the root
`tsconfig.json`, which has `files: []` and only project references — so without
`-b` it type-checks **zero files and always exits 0**. Every "tsc ok" in phases
4.x was vacuous; the real coverage came from `npm run build`, which runs
`tsc -b`, and which ran every phase alongside it. There is now a `typecheck`
script that does the right thing, and CI calls it.

---

## Phase 6 — The additions (weeks 16+)

Only after the foundation is coherent. Ranked by value over effort.

| Feature | Why | Effort |
|---|---|---|
| **Projection line on goals** | Data exists in `goals/forecasting.py`; turns a static number into a plan | S |
| **Subscription detection** | Recurrence data exists; the single most-requested PFM feature | M |
| **Saved views in Activity** | Converts monthly visits into weekly habit | S |
| **Same-period comparison everywhere** | Generalises the Phase 0.4 fix | S |
| **Bill prediction from history** | Fixes the empty Forecast tab at its root | M |
| **Cash-flow forecast confidence bands** | The Meridian concept at full expression | M |
| **Financial milestones** | "First KES 50,000" — retention, tasteful | S |
| **AI assistant in ⌘K** | Natural-language query over the ledger | L |

**Not recommended:** achievement badges beyond milestones, streaks, social
comparison. They are engagement mechanics borrowed from products whose users
are not looking at their debt.

---

## Phase 6 — The additions — complete

Reading the code before building anything found that **three of the eight were
already there**, which is the same lesson every phase of this project has
taught: the audit describes the code at the time it was written, not now.

| Feature | Status |
|---|---|
| Projection line on goals | **Already existed** — `GoalForecastPanel` charts it |
| Subscription detection | **Already existed** — `detect_recurring` in `intelligence/detect.py`, surfacing as suggestions |
| Saved views in Activity | **Shipped in 5.2** as pinned views, and more general: any URL, not just Activity |
| Same-period comparison everywhere | **Done** (below) |
| Cash-flow confidence bands | **Done** — and it turned out to be a correctness fix, not a feature |
| Financial milestones | **Done** |
| Bill prediction from history | **Done** — and it was a missing bridge, not a missing model |
| AI assistant in ⌘K | **Done** — as a query, never an answer |

### The confidence band was not a nicety — the projection was wrong

`cashflow_calendar` reads recurring templates, bills, and current balances.
All three are **scheduled** money. Nothing in them accounts for groceries,
fuel, or a coffee — which for most people is the largest outflow there is.

So the projection was not merely uncertain, it was **systematically
optimistic**: it drew a flat line across a window in which the user would
certainly spend, and told someone they were fine when they were not. On the
demo workspace it claimed a balance of **KES 42,283.81, unchanged for 90
days**. That user's own history says they will be **~KES 7,300 lower**.

`everyday_spending` measures unscheduled outflow — `source != RECURRING`, minus
transfers between projected accounts, so the band cannot double-count what the
schedule already knows. The scheduled line is unchanged and still drawn; the
band sits **below** it, always, because everyday spending only ever takes money
out. Getting that direction wrong would have made the calendar *more*
reassuring than the version that ignored spending entirely.

**The statistics had to be corrected mid-build.** The first version accumulated
the *median* day and grew the band *linearly*. Both are wrong:

- For a cumulative projection the expected total over k days is `k x mean`. On
  bursty spending — everyone's — the median day is zero, so the "likely" line
  sat exactly on top of the scheduled one and silently reinstated the optimism
  the band exists to correct. The live data showed it: `typical_minor: 0`.
- Spread grows as `sqrt(k)`, not `k`. Independent daily variation partly
  cancels, so summing a p75 day 45 times describes something far more extreme
  than a p75 45-day total.

Both are pinned by tests that state the reasoning rather than the arithmetic.

**"Nothing scheduled" stopped meaning "nothing to project."** The empty state
said *"your balance is flat"* — a claim the product can now disprove from its
own data. With no bills but real history, the outlook renders with a banner
saying the projection is day-to-day spending alone.

### Same-period comparison, generalised

Checked every comparison in the product rather than assuming. Two findings, one
of each kind:

- `_income_changes` in the coach **already guards it** (`days < 20` returns no
  comparison, so a part-month never reads as a pay cut). My suspicion was
  wrong, and the guard is better than what I would have added.
- The **admin MRR delta**, written in Phase 5.6, did not — it rendered
  **-100%** on the third of the month. Fixed there.

The pattern is now recorded explicitly: *every time one figure is compared to
another, the question is what basis each was measured on.* That has produced a
defect on Analytics, Debt, Investments and the admin console.

### A Phase 5 claim that was false

Phase 5 dropped the rail's `Activity N` metric with the justification: *"There
is no review state in the data model — no `needs_review` flag, no triage
queue."*

**`Transaction.needs_review` and `review_reason` have been on the model all
along**, and the list endpoint already filtered on them. I asserted an absence
without grepping for it.

What was genuinely missing was a *count*: the ledger is cursor-paginated —
correctly, it has no natural end — and cursor pagination cannot report a total.
So `transactions/review-count/` is the endpoint that was the real gap, the flag
and its reason are now on the serialised transaction (filterable but never
readable before), and the rail metric is restored.

### A defect that only existed once there was something to draw

Making the outlook render without scheduled items pushed the route audit
**overlap 2 -> 5**. The monthly rollup table had five money columns, and the
mobile table reflow pins **every** `.lf-col-amount` to `grid-column: 2;
grid-row: 1` — a pattern written for a ledger row with *one* amount opposite
its description. All five landed in the same grid cell and drew on top of each
other. It had never been measured because that table had never rendered on a
phone: the page showed an empty state instead.

Fixed in both places — `hideMobile` on the three columns a phone does not need,
and `:first-of-type` on the CSS so further amounts flow onto their own lines
instead of colliding. **The audit then came back at `overlap` 0**: the same
latent bug had been producing the two long-standing admin-table overlaps that
had been sitting in the baseline since Phase 1.

This is the third time in this project that a defect was invisible purely
because the surface had no data behind it — Debt in 4.9, Investments in 4.10,
and now here. Worth stating as a standing caveat on the harness: **every route
the audit visits with an empty state is a route it is barely checking.**

### Bill prediction — the detector was already right; nothing consumed it

`detect_recurring` has always found charges on a cadence, with a careful
three-occurrence minimum and a per-gap check so alternating 1-day and 59-day
gaps cannot average into "monthly". Approving one marked the **merchant
profile** as recurring — which teaches the categoriser and nothing else.

The cash-flow projection reads `RecurringTransaction` and `Bill`. So a user
could approve *"yes, this is a subscription"* and watch their forecast stay
completely flat. The detection was never wrong; it just never reached the one
screen it most belonged on.

**A `Bill`, deliberately, and never a `RecurringTransaction`.** An active
recurring template is executed by a beat task that posts real ledger entries —
creating one from a *guess* would write transactions the user never made, which
is the single thing this codebase refuses to do. A bill is an expectation: it
shapes the forecast and posts nothing until somebody marks it paid. Only the
next occurrence is created, so a wrong prediction is one dismissal away from
over rather than a schedule to dismantle.

### Milestones — a record, not a rewards scheme

The roadmap is explicit that badges, streaks and social comparison are out:
they are borrowed from products whose users are not looking at their debt. What
keeps this on the right side of that line is that **a milestone is a dated fact
reconstructed from the ledger**, and the rules that follow from it:

- **First crossing, not most recent.** Someone who passed 50,000, fell back and
  passed it again did that once. Reporting the later date would quietly rewrite
  their history to look better than it was.
- **A threshold already exceeded when the series starts is not dated at all** —
  the record cannot say when it happened, and using the first month on file
  would be a fabricated anniversary.
- **"Debt free" requires having had debt.** A user who has never borrowed has
  not achieved anything by not borrowing; saying so would be the product
  congratulating itself.
- Nothing is stored, capped at three, and the list is absent entirely when
  empty — an empty "Milestones" heading is a standing reminder that you have
  not achieved anything.

### The ⌘K assistant, and the shape that made it shippable

The obvious design is: send the model some transactions, let it answer in
prose. That puts a language model in the position of **stating figures about
someone's money**, where a plausible wrong number is indistinguishable from a
right one and there is nothing to check it against.

**So the model never produces a figure. It produces a filter.** Dates, a
category, an amount range, a direction — validated server-side, then executed
by the same selectors, under the same tenant scoping, as if the user had built
it in the filter bar. The arithmetic is the product's; the model only decides
what to look at. Asking *"how much did I spend last 30 days"* lands on
`/activity?start=2026-07-04&end=2026-08-03&direction=out` with the filter
spelled out above it, editable.

This is exactly the boundary `llm.py` already documents — *"it cannot reach the
database, cannot write to the ledger, and its output is validated"* — so the
product decision I said this needed turned out to have been made, and written
down, before I got here.

Three properties hold it:

- **An allow-list, not a prompt.** A prompt is a request; an allow-list is a
  guarantee. `{"delete": true, "sql": "DROP TABLE"}` coerces to `{}`.
- **A hallucinated category is dropped**, because filtering by a category the
  workspace does not have returns an empty list that looks exactly like an
  answer.
- **Rules first, model second, neither required.** Most questions are
  "groceries last month" or "over 500" — a regex is faster, more private and
  more reliable than a hosted model. With no provider configured the feature
  degrades to that parser, and with that finding nothing the palette falls back
  to plain search. The assistant is never the reason somebody cannot look
  something up.

### A touch-target trade, taken deliberately

The console's exception-panel links — the first thing an operator reads and the
first thing they click — were **20px tall**, under the 24px WCAG AA floor
(2.5.8), on the highest-consequence control in the product. Giving them a real
box took `target-aa` **32 → 28**.

It also took `target-project` **61 → 63**, because a link with a measurable box
is now measured against the *project's* stricter 44px goal as well. That one is
accepted rather than fixed: the platform console is compact **by design** — the
token block sets 32px rows and calls it the operator default — and forcing 44px
onto inline links inside a dense exception list would fight the identity that
exists to keep an operator aware of which product they are in. WCAG AA is met;
the house rule is not, and that is the right way round.

Stated in the module and worth restating: this understands roughly the
questions the filter bar can express. It is a faster route to a view you could
have built yourself, not a new capability.

---

## Summary

| Phase | Weeks | Risk | Revertable |
|---|---|---|---|
| 0 Truth and bugs ✅ | 1 | very low | per commit |
| 1 Harness ✅ | 2 | none | n/a |
| 2 Components ✅ | 3–5 | none | additive |
| 3 Token swap ✅ | 6 | medium | one file |
| 4 Screens ✅ | 7–12 | low per PR | per screen |  ← 12 of 12 done
| 5 Navigation ✅ | 13–15 | high | feature flag |
| 6 Additions ✅ | 16+ | low | per feature |  ← 5 shipped, 3 pre-existing

**If only one phase ships: Phase 0.** It contains every finding that damages
trust, and trust is the thing a finance product cannot rebuild with visual
design.

**If only two: Phase 0 and Phase 2.** `<Figure>` alone retires 50 selectors and
makes the product's worst class of defect — a confident number the data does
not support — impossible to express.
