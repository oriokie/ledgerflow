# Meridian — Design System Specification

The visual identity for LedgerFlow. Every contrast ratio in this document was
computed, not estimated; the script is in `scripts/verify_palette.py` (see
§9). Colour-vision separation was verified by LMS simulation of deuteranopia,
protanopia and tritanopia.

---

## 1. The identity in one paragraph

**A warm-neutral instrument panel where colour is rationed and certainty is
visible.** Surfaces are warm paper and warm graphite — not the blue-black every
competitor uses. Type is a tight grotesk for structure and a duospace for every
monetary amount. Four hues exist, each with exactly one job: *meridian* for
interaction, *jade* for money in, *vermilion* for things that are wrong, *ochre*
for things that need attention. A fifth, *horizon*, is reserved entirely for
the future — projections, forecasts, anything the product does not know for
certain. Nothing else is coloured. The result reads as an instrument, because
on an instrument every coloured thing means something.

---

## 2. Colour

### 2.1 Why warm

Every product in the category — Monarch, Copilot, Rocket, and LedgerFlow before
this swap (`--lf-ink-900: #151928`) — uses a cool blue-black. Warm graphite
(`#1a1917`) is the cheapest available differentiator that also has a rationale:
money is a paper-and-ledger domain, and warm neutrals read as document rather
than device.

**Naming note.** The dark surfaces are described below as `graphite-*` for
clarity, but ship as direct overrides on `--lf-bg-app` / `--lf-bg-surface` /
`--lf-bg-sunken` inside the `[data-theme="dark"]` block — there is no
`--lf-graphite-*` primitive, because a dark surface has exactly one consumer
and a named primitive would imply otherwise. The light primitives *are* named
(`--lf-paper-*`, `--lf-ink-*`, `--lf-meridian-*`, `--lf-jade-*`,
`--lf-vermilion-*`, `--lf-ochre-*`, `--lf-horizon-*`), and the pre-swap names
remain as aliases so Phase 4 can migrate references file by file.

### 2.2 Light theme — verified

| Token | Hex | on `paper-000` | on `paper-050` | on `paper-100` |
|---|---|---|---|---|
| `ink-900` | `#1A1917` | 17.57 | 16.70 | 15.54 |
| `ink-700` | `#3D3B37` | 11.18 | 10.62 | 9.89 |
| `ink-500` | `#6B6862` | 5.55 | 5.28 | 4.91 |
| `ink-400` | `#5C5A54` | 6.90 | 6.55 | 6.10 |
| `meridian-700` | `#09525F` | 8.81 | 8.37 | 7.79 |
| `meridian-600` | `#0E6C7A` | **6.10** | 5.79 | 5.39 |
| `jade-700` | `#0A5B3D` | 8.15 | 7.75 | 7.21 |
| `jade-600` | `#0D7350` | **5.86** | 5.57 | 5.18 |
| `vermilion-700` | `#9E3520` | 7.04 | 6.69 | 6.23 |
| `vermilion-600` | `#BC4227` | 5.32 | 5.06 | 4.71 |
| `ochre-700` | `#7C4E0A` | 7.12 | 6.76 | 6.30 |
| `ochre-600` | `#9A6209` | 5.09 | 4.84 | 4.50 |
| `horizon-600` | `#514F7D` | 7.60 | 7.22 | 6.72 |

Surfaces: `paper-000 #FFFFFF` · `paper-050 #FAF9F7` (app) · `paper-100 #F2F1ED`
(sunken). **Every value clears WCAG AA (4.5:1) on every surface.** The weakest
is `ochre-600` on `paper-100` at 4.50.

### 2.3 Dark theme — verified

| Token | Hex | on `graphite-app` | on `graphite-surface` | on `graphite-sunken` |
|---|---|---|---|---|
| `ink-050` | `#F2F0EA` | 16.31 | 14.80 | 17.05 |
| `ink-200` | `#B5B1A6` | 8.68 | 7.87 | 9.07 |
| `ink-300` | `#94908A` | 5.86 | 5.31 | 6.12 |
| `meridian-400` | `#3FB3B8` | 7.39 | 6.71 | 7.73 |
| `jade-400` | `#3DBE86` | 7.88 | 7.16 | 8.24 |
| `vermilion-400` | `#E8735A` | 6.22 | 5.65 | 6.51 |
| `ochre-400` | `#D9A343` | 8.21 | 7.45 | 8.58 |
| `horizon-400` | `#9A97D6` | 6.88 | 6.24 | 7.19 |

Surfaces: `graphite-app #14130F` · `graphite-surface #1E1D19` ·
`graphite-sunken #0E0D0A`. **All clear AA.**

Button labels on solid fills: white on `meridian-600` **6.10**, on `jade-600`
5.86, on `vermilion-600` 5.32; `graphite-sunken` on `meridian-400` 7.73. All
pass. Focus ring (`meridian-600` / `meridian-400`) clears 1.4.11's 3:1 on every
surface in both themes (lowest 5.39).

### 2.4 The one job per hue

| Hue | Its only job | Never used for |
|---|---|---|
| **meridian** (teal) | Interaction: primary action, selection, focus, links | Data, status, decoration |
| **jade** (green) | Money *in*. Success confirmations | Chart series (except as one of three), "good" scores |
| **vermilion** (red-orange) | Genuinely wrong: errors, over-budget, destructive, failed payment | Expenses, spending, negative amounts |
| **ochre** (amber) | Needs attention, pending, unreconciled | Errors |
| **horizon** (violet-grey) | **The future only** — projections, forecasts, scheduled-not-yet-posted | Anything settled |
| **ink** | Money *out*, and all body text | — |

**The inherited rule, kept and strengthened:** money out is ink, not red.
Spending is normal life. `vermilion` is reserved for failure. This is the
system's best existing idea and it survives the redesign unchanged.

`meridian` and `jade` are separated by ΔE 31.4 in normal vision, 22.6 under
deuteranopia, 29.3 under protanopia — comfortably distinguishable, which
matters because "the button" and "money in" must never be confused.

### 2.5 Certainty as a visual property

The Meridian concept made concrete. This table is the contract:

| State | Colour | Fill | Stroke | Type |
|---|---|---|---|---|
| **Settled** | `ink` / `jade` | solid | solid | ledger duospace, full weight |
| **Pending** | `ochre` | solid | solid | ledger duospace + dotted underline |
| **Projected** | `horizon` | none | **dashed 4 2** | ledger duospace at 85% opacity |
| **Speculative** | `horizon` | none | dashed + hatch | **must carry a confidence sentence** |

A speculative figure may not render as a bare numeral. This is enforceable in
code (see §7.4) and it makes the audit's Debt-score defect unrepresentable.

### 2.6 Data visualisation — what the measurements actually forced

This section changed during the work, because the verification script rejected
the palette I first proposed. That process is worth recording, since the
conclusion is the most important rule in the system.

**Attempt 1 — a categorical hue ramp.** slate / ochre / jade measured a healthy
min ΔE of 44.0 in normal vision and 32.8 under deuteranopia in *light* mode.
The same trio in dark mode fell to **ΔE 18.8** under deuteranopia — below the
floor. Fixing it by re-picking dark slate failed: an exhaustive search over
60,000 candidate trios found **no** set that simultaneously (a) clears 3:1 on
the dark surface, (b) separates ≥20 ΔE under both deuteranopia and protanopia,
and (c) stays ≥20 ΔE away from the interactive accent. The only survivors were
neon and off-identity (`#65E62E`).

**The conclusion is general, not local.** At realistic contrast constraints,
four decorative categorical hues that survive both common forms of colour
blindness *and* remain distinct from the UI accent do not exist. Any design
system claiming otherwise has not measured it.

**So LedgerFlow has no decorative categorical ramp.** Chart colour is
*semantic* — the same four meanings as the rest of the product:

| Series | Light | Dark | Contrast (light / dark) |
|---|---|---|---|
| Income | `#0D7350` jade | `#3DBE86` | 5.86 / 7.16 |
| Expense | `#3D3B37` ink | `#B5B1A6` | 11.18 / 7.87 |
| Projection | `#514F7D` horizon | `#9A97D6` | 7.60 / 6.24 |
| Alert | `#BC4227` vermilion | `#E8735A` | 5.32 / 5.65 |

Normal-vision separation: **33.0** (light) / **41.6** (dark) — both gated in CI.
Under deuteranopia these fall to 19.8 / 13.2, and that is *accepted*, because:

> **Colour is never the only encoding in a LedgerFlow chart.** Every series
> carries a redundant channel — a direct label, a distinct position, or a dash
> pattern. Separability is guaranteed by that channel, not by hue.

This satisfies WCAG 1.4.1 properly rather than by hoping. It is also why the
`<Chart>` wrapper makes `label` a required prop per series (§7.4).

**For breakdowns with more than four parts: sequential, ordered by magnitude.**

Light: `#1E3D52` (11.38) → `#2F5A75` (7.39) → `#3D6E8C` (5.52) → `#6E97AE` (3.13)
Dark: `#A9CBE0` (9.88) → `#7FAECB` (7.08) → `#5A90B0` (4.86) → `#3E6F8E` (3.11)

**Four steps maximum.** A fifth step (`#A4C0D0` light, `#2A5169` dark) measures
1.90 and 1.99 against its surface — below the 3:1 non-text floor. Category
breakdowns therefore render **top 4 + "Other"**, which is better information
design regardless: nobody reads a twelve-slice donut.

### 2.7 Chart rules

1. **Direct labels over legends, always.** A legend forces a colour→name
   lookup; labelling the series at its terminus removes it — and it is the
   redundant channel §2.6 depends on. Legends only when marks are too dense to
   label, and then series must differ by dash pattern too.
2. **Expenses are never vermilion.** They are `ink`. The current
   `CashFlowChart.tsx:32` violation — which fills Expenses with
   `--lf-status-danger` — is a P0 fix.
3. **Projections are dashed `horizon`**, always, in every chart.
4. **Y axes start at zero for magnitude**, may be trimmed for trend — and must
   say which.
5. **No chart renders without a "what this shows" one-liner** in `ink-500`.

---

## 3. Typography

| Role | Face | Rationale |
|---|---|---|
| **Display** | Schibsted Grotesk | Kept. Tight, high x-height, characterful without being fashionable |
| **Body** | system-ui stack | Kept. Fastest possible, native-feeling |
| **Ledger** | Spline Sans Mono | **Kept and elevated.** Every monetary amount, everywhere, no exceptions |

The existing ledger-column idea is the product's signature and is functionally
correct (tabular figures align by place value). It is amplified, not replaced.

### 3.1 The scale — eight steps, uniformly 1.20

```
xs    0.694rem   11.1px   eyebrows, table meta        tracking +0.06em, uppercase
sm    0.833rem   13.3px   secondary UI, labels
base  1rem       16px     body
md    1.2rem     19.2px   card titles
lg    1.44rem    23.0px   section headings
xl    1.728rem   27.6px   page titles
2xl   2.0736rem  33.2px   large figures
3xl   2.488rem   39.8px   hero figures                 tracking −0.015em
```

**The scale used to have a hole.** `2xl` was 2.488rem, making the xl→2xl step
1.44 in an otherwise uniform 1.2 progression. Three stylesheets had already
noticed something was missing and reached for `var(--lf-text-3xl, 2rem)` — a
token that did not exist — so all three silently rendered at the 32px fallback,
off the scale entirely. Closing the gap resolved both: the hero step keeps its
exact size under its correct name (`3xl`), and every step is now 1.2 from its
neighbours.

**`font-size` may only be set from a token.** Bare `em` sizing is banned — it is
what produced 9.44px, 11.33px, 13.60px, 19.58px and 33.84px on live screens.

**One sanctioned exception: the ledger cents.**

```css
.lf-amount-cents { font-size: max(var(--lf-text-xs), 0.8333em); }
```

Cents must be one step below whatever amount they sit inside, and an amount
inherits its size from a dozen different containers — so enumerating them is a
list that goes stale. This earns the exception on three counts:

1. **It cannot compound.** Cents contain no nested sized text.
2. **It lands on the scale by construction.** `1 / 1.2 = 0.8333`, so now that
   every step is exactly 1.2, any token parent maps exactly onto the token
   below it. Measured across twelve routes: `xs→xs`, `sm→xs`, `base→sm`,
   `lg→md`, `xl→lg`, `3xl→2xl` — every one on a step.
3. **It has a floor.** `max()` means cents can never render below `xs`, however
   small the parent. The 9.44px that this rule used to produce was the only
   sub-legible text in the product.

Enforced by the token lint (§9) and by the route audit asserting that no screen
renders more than eight distinct computed font sizes.

### 3.2 The ledger column

```
KES  42,283.81        ← currency in ink-500 sm, amount in ledger 2xl
     ─────────
     tabular-nums, no ligatures, cents at sm
```

- Currency code always precedes, in `ink-500`, never the same size as the amount
- Cents at one token step down — legible, subordinate, never opacity-dimmed
  (opacity broke contrast in the previous system; the note survives in
  `tokens.css:90`)
- Negative amounts use a true minus `−` (U+2212), not a hyphen
- Amounts never wrap

---

## 4. Space, radius, elevation

### 4.1 Spacing — 4px grid, four semantic steps

The existing rhythm contract is good and is kept verbatim:

```
rhythm-title    24px   page title  → first block
rhythm-section  32px   block       → next block
rhythm-card     24px   card        → sibling card
rhythm-field    20px   field       → next field
```

**New:** page-level spacing may *only* use these four. Raw `space-N` is for
component internals. This is what stops each feature inventing its own vertical
rhythm.

### 4.2 Radius

```
sm   6px    inputs, badges, chips
md   10px   buttons, menu items
lg   14px   cards            ← down from 16px: squarer reads more instrument
xl   20px   modals, sheets
full 999px  pills, avatars
```

### 4.3 Elevation — four steps, and a rule

The existing layered low-alpha approach is correct and is kept. The addition is
a **usage rule**, because the audit found shadows applied decoratively:

| Step | Use |
|---|---|
| `flat` | Default. Cards on the app canvas use a **border**, not a shadow |
| `raised` | Only for elements that will move or be dragged |
| `hover` | Only on interactive surfaces, only on `:hover` |
| `overlay` | Modals, popovers, toasts, command palette |

A static card does not get a shadow. Depth is spent only where it means
"this thing is above the page."

### 4.4 Breakpoints — six, tokenised

Replacing the fourteen found in the audit:

```
--bp-xs   480px    large phone
--bp-sm   640px    phone → tablet
--bp-md   768px    tablet portrait
--bp-lg   1024px   tablet landscape / laptop   ← rail appears here
--bp-xl   1280px   desktop
--bp-2xl  1600px   ultrawide                   ← rail stays open, content widens
```

Always `min-width` (mobile-first). No `max-width` queries; they are what
produced the off-by-one pairs. Ultrawide: at `2xl` the content column grows to
1440px and the rail stays expanded — the app must never be a 1200px strip in a
2560px void.

---

## 5. Motion

**Principle: things settle. Nothing bounces.**

```
duration-instant  80ms    admin console, repeated operator actions
duration-fast     120ms   hover, focus, toggle
duration-base     200ms   panels, disclosure, page transition
duration-slow     320ms   hero number reveal, chart draw

ease-settle    cubic-bezier(0.22, 1, 0.36, 1)   default; decelerating, no overshoot
ease-enter     cubic-bezier(0.16, 1, 0.30, 1)   arriving overlays
```

| Interaction | Motion |
|---|---|
| Page transition | 200ms cross-fade + 8px rise. No horizontal slide |
| Card hover | `translateY(-1px)` + `hover` shadow, 120ms. **1px, not 4px** |
| Number reveal | Count-up 320ms, **first paint only** — never on refetch |
| Chart draw | Left-to-right reveal 320ms, once per mount |
| Skeleton | Shimmer 1.2s, only after 200ms of actual latency |
| Toast | Rise 12px + fade, 200ms `ease-enter` |
| Goal completed | Confetti. The **only** place in the product |

`prefers-reduced-motion: reduce` collapses every duration to 0.01ms, disables
count-up (final value paints immediately), disables shimmer (static block), and
disables confetti. Already partially implemented; extend to all of the above.

---

## 6. Iconography

Lucide, already in use, kept. `1.5px` stroke, 20px in nav and buttons, 16px
inline. Icons are `ink-500` unless the element is selected. **An icon never
carries meaning alone** — it always accompanies a label, except in the
compressed 64px rail where the label appears in a tooltip and `aria-label`.

---

## 7. Component library

### 7.1 The missing layer

The audit's core finding is that the system has primitives and features but no
**composite layer**. That layer is the deliverable:

| Component | Replaces | Selectors retired |
|---|---|---|
| **`<Figure>`** | every stat tile | **~50** |
| **`<Stack>` / `<Row>` / `<Grid>`** | hand-rolled flex (and the `<span>` bug) | ~11 |
| **`<PageHeader>`** | per-feature headers | ~10 |
| **`<Meter>`** | per-feature progress bars | ~18 |
| **`<Empty>`** | per-feature empty states | ~14 |
| **`<Badge>`** | per-feature chips | ~13 |
| **`<SegmentedControl>`** | 5 separate implementations | — |
| **`<DataTable>`** | bespoke tables | — |
| **Total** | | **~116 selectors → ~8 components** |

### 7.2 `<Figure>` — the most important component in the system

Every labelled number in the product. One implementation, four sizes, and
certainty is a required prop.

```tsx
<Figure
  label="Net worth"
  amountMinor={3914931}
  currency="KES"
  size="hero"                    // hero | primary | secondary | inline
  certainty="settled"            // settled | pending | projected | speculative
  delta={{ pct: 154, months: 6 }}
  confidence="Based on 45% of the usual inputs"   // REQUIRED when speculative
/>
```

- `certainty` drives colour, stroke and opacity per §2.5
- TypeScript makes `confidence` required when `certainty="speculative"`, so the
  Debt page's "100 / Excellent" cannot ship without its caveat attached
- `label` renders `xs` uppercase `ink-500`; amount renders in the ledger face at
  the token step for `size`; nothing else is configurable

### 7.3 `<Empty>` — with a zero-state guard

```tsx
<Empty
  icon={Wallet}
  title="No debts tracked"
  body="Add a card or loan to see payoff plans and interest costs."
  action={{ label: "Add a debt", to: "/debt/new" }}
/>
```

**The rule the Debt page violates:** when a section's inputs are absent, it
renders `<Empty>` — never a grid of `0.00`. A dashboard of zeros is a lie of
omission; it implies measurement where there was none.

### 7.4 Enforcement

Three lint/test rules keep the system from re-fragmenting:

1. **stylelint** — `declaration-property-value-allowed-list` restricting
   `color`, `background-color`, `font-size`, `border-radius` and `box-shadow`
   to `var(--lf-*)`. Blocks the 53 hardcoded hexes and all `em` font sizes.
2. **A "no new stat tile" test** — fails CI if a new selector matching
   `stat|metric|figure|kpi|value|tile` is added outside `Figure.tsx`.
3. **A type-scale test** — mounts each route and asserts ≤7 distinct computed
   `font-size` values.
4. **A chart-redundancy rule** — the `<Chart>` wrapper types every series as
   `{ key, label, ... }` with `label` required, and a test asserts each rendered
   series has either a direct label or a dash pattern. This is what makes §2.6's
   acceptance of low CVD separation legitimate rather than negligent.

---

## 8. Two products, one system

The admin console is the same tokens under a different semantic assignment
(rationale in [`02-strategy-ia.md §4`](02-strategy-ia.md)):

```css
[data-product="platform"] {
  --lf-bg-app:       #0F1418;   /* cool slate, not warm graphite */
  --lf-bg-surface:   #161D23;
  --lf-action-primary: var(--ochre-400);   /* signal amber, not meridian */
  --lf-radius-lg:    8px;                  /* squarer */
  --lf-duration-base: 80ms;                /* instant */
  --lf-row-height:   32px;                 /* compact */
  --lf-font-display: var(--lf-font-ledger);/* duospace headings */
}
```

One block. No component changes. An operator can never mistake one for the other.

---

## 9. Verification

**This palette shipped in Phase 3.** It is no longer a proposal: the values
below are what `frontend/app/src/styles/tokens.css` contains, and
[`scripts/verify_palette.py`](../../scripts/verify_palette.py) now parses that
file rather than carrying its own copy — so the document and the product cannot
drift apart without CI failing.

Every figure in this document was produced by:

```bash
python scripts/verify_palette.py
```

It computes WCAG 2.1 contrast for every token against every surface in both
themes, simulates deuteranopia, protanopia and tritanopia via LMS transform,
and reports minimum pairwise ΔE for the chart set.

**What it gates** (exit 1): AA 4.5:1 for all text tokens; 4.5:1 for button
labels on fills; 3:1 for every chart colour and sequential step; ΔE ≥ 20 for
chart series in normal vision.

**What it reports but does not gate**: CVD separation — for the reason argued
in §2.6, with redundant encoding as the actual guarantee.

This script rejected the first palette proposed for this document (§2.6), and
then — once pointed at the real `tokens.css` — caught a shipped defect the
proposal had introduced: dark-mode `chart-expense` and `certainty-projected`
had become the same colour, ΔE 0.0, making a projection indistinguishable from
settled spend. That is the entire argument for having it. Run it in CI. The previous system's claim
— *"accessibility floor (verified, not asserted)"* — is the right standard, and
this keeps it.

---

*Continues in [`04-screens.md`](04-screens.md).*
