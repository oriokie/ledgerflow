# Frontend page review — "the investment page has no button"

A functional audit of every route, triggered by a specific report: the
Investments page allegedly showing no buttons at all.

## The specific claim, checked directly

`InvestmentsPage.tsx`'s source has six buttons (Add security, Update prices,
Record trade, Buy, Sell, plus an empty-state CTA), all wired to real
`onClick` handlers opening real modals. Source review alone can't prove they
*render* though — a component can be correct on the page and still produce
nothing if something in its render tree throws.

So it was rendered for real, through the actual component tree (React
Testing Library, not a static mock), in both states a user can hit:

- **No portfolio yet:** 3 buttons render — Add security, Record trade
  (correctly disabled with no securities), Add your first security.
- **Populated portfolio:** 5 buttons render — Add security, Update prices,
  Record trade, Buy, Sell.

No crash in either state. **The claim doesn't reproduce against the current
code.**

## What the investigation found instead

Checking *why* a correct component might still render nothing led to the
real, systemic issue: **this application had no React error boundary
anywhere.** Confirmed by search — zero matches for `componentDidCatch` or
`getDerivedStateFromError` in the entire codebase.

The consequence: an uncaught render-time exception *anywhere* — a chart
library given a data shape it doesn't expect, a hook throwing on an edge
case — unmounts React's entire tree. Not just the component that threw: the
page header, the navigation, every button on the page, gone, replaced with a
blank screen. To someone looking at the result, a genuine crash and "there
are no buttons" are indistinguishable. This is very likely what was actually
observed, from a since-resolved or transient error rather than a defect in
the Investments page's own code — and it's a real problem independent of that
one report, since it means *any* page's crash looks identical to *every*
page's crash: nothing at all.

### Fix

`src/components/RouteErrorBoundary.tsx` — a route-scoped error boundary
wired into `AppShell` around the router outlet. A crash now degrades to a
card-sized "Something went wrong on this page" message with a retry button,
rather than a blank tab. Mounted with `key={location.pathname}`, so
navigating to a different route gives a fresh mount — and therefore a fresh
attempt — automatically, through React's ordinary remount lifecycle rather
than manual prop-diffing in `componentDidUpdate` (the latter is a
well-documented React footgun that trips lint rules even when correctly
guarded; `key`-based remounting needs no guard and is simply the
React-idiomatic tool for this).

7 tests, including that the rest of the app is unaffected, that retry works
in place without navigating away, and that the boundary doesn't blindly
reset just because a broken route re-renders under the same key.

## The rest of the sweep

**All 30 top-level pages** were checked for interactive completeness via a
static pass (interactivity density, dead/stub `onClick` handlers, forms
missing `onSubmit`) followed by manual verification of anything flagged:

- Four pages initially showed zero matches for `<Button`/`onClick`/`<Link`:
  `AnalyticsPage`, `SettingsPage`, `CashflowPage`, `ReportsPage`. All four
  are false positives from the grep pattern missing `SegmentedControl`'s
  `onChange`, `onSelect` callbacks, and route-composing shells that
  correctly delegate to child panels with their own controls (verified by
  reading each file in full). None are actually broken.
- One genuinely stub handler found (`onClick={() => {}}`) — in
  `ComponentShowcase.tsx`, a deliberate design-system demo page, not a
  product page.
- Every `<form>` in the app has an `onSubmit` handler; none rely on default
  browser submission (which would cause a jarring full-page reload in an
  SPA).

## Chart resilience

Ten components across seven pages use `recharts`, the most likely source of
a render-time throw on malformed data. `CashFlowChart`, `AllocationChart`,
and `PerformanceChart` were probed directly with the edge cases a real API
response can legitimately produce — empty arrays, all-zero values, a single
data point, a negative gain (a real investment loss). All three held up.

One probe initially "failed" with `RangeError: Invalid time value` — traced
to the test itself passing the wrong field name (`month` instead of the real
`SpendingTrendPoint.period_start`), not a bug in the component. Corrected and
kept as `chart_crash_resilience.test.tsx`, a permanent regression test, since
the scenario it exercises (edge-case chart data) is worth pinning regardless
of how it was first written.

## What this does and doesn't cover

Covered: every route's presence of working interactivity, the systemic
crash-resilience gap, and direct rendering verification of the flagged page
in both its states.

Not covered: a full manual click-through of every modal and form's
submission path against a live backend, and the ten chart components'
resilience was sampled (three of ten, chosen for being on the pages closest
to the original report) rather than exhaustively probed. The same
`chart_crash_resilience.test.tsx` pattern extends directly to the remaining
seven if that's wanted next.
