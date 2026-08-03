# LedgerFlow Redesign — "Meridian"

A complete UX audit, visual identity, and phased implementation plan.

## The documents

| | |
|---|---|
| [`01-audit.md`](01-audit.md) | UX & front-end audit. Every major screen, evidence-backed |
| [`02-strategy-ia.md`](02-strategy-ia.md) | Redesign strategy, information architecture, navigation, admin identity |
| [`03-design-system.md`](03-design-system.md) | The Meridian design system — colour, type, space, motion, components |
| [`04-screens.md`](04-screens.md) | Per-screen redesign specifications |
| [`05-interaction-a11y-performance.md`](05-interaction-a11y-performance.md) | Interaction guidelines, accessibility, mobile, performance |
| [`06-roadmap.md`](06-roadmap.md) | Phased implementation plan with regression controls |
| [`07-illustration-landing.md`](07-illustration-landing.md) | Illustration system, landing page, and the full-page states |
| [`08-typography.md`](08-typography.md) | The Meridian faces, metric-matched fallbacks, and the hosting decision |
| [`09-income.md`](09-income.md) | The income model, the retired label heuristic, and committed income |

## Verification

Three guards, all wired into CI. Each was added after something got past the
previous ones.

| | Checks | Added because |
|---|---|---|
| [`verify_palette.py`](../../scripts/verify_palette.py) | Contrast floors, chart separation, the sequential ramp, CVD simulation | It rejected the first Meridian palette, then caught a shipped ΔE 0.0 collision |
| [`check_style_tokens.py`](../../scripts/check_style_tokens.py) | Ratchet on literal hex/rgb, `em` sizes, inline-style literals, off-scale breakpoints | Baseline-as-ceiling: drift fails, improvement prompts you to lower the bar |
| [`audit_routes.py`](../../scripts/audit_routes.py) | 31 routes × 2 viewports: overlap, touch targets, type scale, heading outline, overflow — plus `--snapshot` computed-style fingerprints | The thresholds catch regressions; the fingerprints catch *silence* — see 4.12, where a valid stylesheet stopped applying a rule and nothing else noticed |

**Status: Phases 0–6 complete.** Phase 5's IA ships
behind a per-user flag (Settings → Preferences), off by default. Snapshots in
[`snapshots/`](snapshots/); `post-phase4.json` is the current baseline.

---

## The short version

**The foundation is good and exactly one component was missing.**
`src/styles/tokens.css` is a genuinely sophisticated system with a real opinion
(money-out is ink, not red) and a verified contrast floor, and the component
library on top of it is well adopted — `Card` 125 usages, `Money` 95, `Stack`
71, `Badge` 57.

But there was no component for **a labelled number**, and it is the single most
repeated idea in a finance product. So thirteen features each built their own:
**71 selectors across 13 stylesheets against 3 in the shared library.** That is
why three figures in one row on the Goals page sat on three different
baselines. `<Figure>` shipped in Phase 2 and closes it.

*(This is a correction. The audit first read the raw selector counts as six
missing components; splitting them by file showed the opposite — see
[`01-audit.md §4.1`](01-audit.md).)*

**Two defects damage trust, and they outrank everything cosmetic:**

1. The Debt page shows a **100/100 "Excellent"** score while also stating it is
   *"based on 45% of the usual inputs"* with *"1 debt missing terms"*.
2. Analytics reports **"expenses ↘ 97%"** in green on 2 August — comparing two
   days against a full month.

A user who catches either of these stops believing the other numbers.

A third — "the flagship Analytics chart renders no data" — was reported here and
has been **retracted**. It was an artefact of auditing through a hidden browser
tab where `requestAnimationFrame` never fires; recharts builds bars via rAF, so
they were missing from the DOM and from every screenshot. The chart works. The
full correction is in [`01-audit.md §4.2`](01-audit.md).

**The concept: Meridian.** Money is a line through time. Left of today is
settled; right of today is projected. **Today is the meridian.** The visual
language encodes certainty as a first-class property — settled figures are
solid, projections are dashed `horizon`, and a *speculative* figure cannot
render as a bare numeral at all. This is the differentiator: every competitor
renders a forecast identically to a fact.

It also fixes the trust defects structurally. Under the `<Figure>` component's
API, a `speculative` certainty makes the confidence statement a required prop —
so the Debt page's score cannot ship without its caveat attached.

**Identity:** a warm-neutral instrument panel — warm graphite and paper rather
than the blue-black everyone else uses — where colour is rationed to four jobs:
`meridian` teal for interaction, `jade` for money in, `vermilion` for things
that are wrong, `ochre` for things needing attention, plus `horizon` for the
future. Every value is contrast-verified in both themes.

**IA:** 21 primary destinations collapse to 8. Four routes answering the same
question (Coach, Analytics, Reports, Insights) merge into **Insights**. Four
views of committed money (Budgets, Bills, Recurring, Cash flow) merge into
**Plan**. Two *actions* currently sitting in the navigation (Quick Add, Scan
Receipt) move to the `+` control where verbs belong.

---

## One finding worth reading in full

The palette in §2.6 of the design system is not the one originally proposed.
The verification script rejected it: the dark-mode categorical ramp fell to
ΔE 18.8 under deuteranopia, below the floor. An exhaustive search over 60,000
candidate trios then found **no** set of three decorative hues that clears the
contrast floor, separates under both deuteranopia and protanopia, *and* stays
distinct from the interactive accent.

That is a property of colour, not of this palette — and most design systems
ship the broken ramp because they never measured. LedgerFlow's answer is to
have **no decorative categorical ramp at all**: chart colour is semantic
(income, expense, projection, alert), and separability is guaranteed by a
required redundant channel — a direct label or dash pattern on every series —
rather than by hue.

The script is in the repo and gates CI. It rejected my first attempt, which is
the entire argument for having it.

---

## Where to start

**Phase 0 is done.** Nine items shipped and verified in the running app,
including both trust defects above. Detail and evidence in
[`06-roadmap.md`](06-roadmap.md).
