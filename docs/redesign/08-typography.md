# Meridian typography

Three roles, and — as of this change — three real faces.

| Role | Face | Used for |
|---|---|---|
| `--lf-font-display` | Spline Sans Mono | Headings, eyebrows, labels — `md` (19.2px) and up |
| `--lf-font-body` | Schibsted Grotesk | Running text and controls — `base` (16px) and down |
| `--lf-font-ledger` | Spline Sans Mono | **Every** monetary amount, without exception |

**The split is by size, not by role.** `md` and above take the display face;
`base` and below take the body face. That single rule is what keeps the two
apart on a screen where both appear in the same card.

## 0. Why the headings are duospace

The display face was Schibsted Grotesk — a grotesk sitting above a duospace
ledger column. It read as two unrelated typographic decisions stacked on top of
each other, and it did not match the design language specimen, where every
heading, eyebrow, table head and tag is set in the same monospaced face as the
figures.

The argument for changing it is not stylistic. The ledger column **has** to be
duospace so digits align by place value; that is load-bearing and cannot move.
Once one face on the page is duospace, setting the headings above it in an
unrelated grotesk makes the alignment read as an inherited quirk of the amounts
rather than as the product's central claim. Sharing the face makes it look
chosen.

Prose stays humanist because duospace is measurably slower to read at paragraph
length — which is exactly why the split is drawn at `base` rather than applied
to everything.

Three things moved with the face:

* **Weight 600 → 500.** A duospace face carries more ink per character at the
  same nominal weight, because its stems are drawn to fill a fixed advance. At
  600 the new headings read as the 700 they replaced.
* **Tracking became size-dependent.** One `tight` value cannot be correct for
  both a 27.6px page title and a 19.2px card title. Three steps now:
  `--lf-tracking-display` (3xl only), `--lf-tracking-tight` (2xl/xl/lg, and
  every ledger amount), `--lf-tracking-snug` (md/base).
* **Eyebrows joined the display face** at `--lf-tracking-wider` (0.14em). An
  eyebrow sits directly above a heading; a different face there puts a seam
  through the middle of the block the pair is meant to read as.

The `Grotesk` option in Preferences is now `Meridian`, since "grotesk" stopped
describing the default. `System` overrides display *and* body — never
`--lf-font-ledger`, because column alignment is not a preference.

## 1. The body face was missing

Display and ledger have always loaded real webfonts. `--lf-font-body` was a bare
system stack:

```css
--lf-font-body: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI",
  Roboto, "Helvetica Neue", sans-serif;
```

So the largest surface in the product — every label, every button, every
sentence — rendered in SF on a Mac, Segoe UI on Windows and Roboto on Android.
Three different products wearing the same logo. **A design system that names a
body face and then does not ship one has specified nothing**, and the identity
work in Phases 3–6 was resting on the two roles that happened to have faces.

Body now uses Schibsted Grotesk at 400/500, requested alongside the display
weights that were already being fetched.

## 2. What that cost, measured

Schibsted Grotesk is **9.5% wider than SF** on the same string. Switching body
text to it is not a cosmetic change — it re-flows the whole product. The route
audit is what says whether that broke anything:

```
overlap  0 -> 2      both on /admin/analytics
```

Every collision was on `/admin/analytics`, between recharts axis ticks — and
the harness needed fixing before they could even be identified. It reported
them as `[object SVGAnimatedString]`, because `className` on an SVG element is
an `SVGAnimatedString`, not a string. Chart internals are exactly where
overlaps happen, and they were the one place the audit could not name. It now
prints `tspan("2025-09-01") | tspan("0")`.

With that, the fix took three passes, each one measured rather than assumed:

1. **Thin the ticks.** The console's charts drew all twelve month labels
   regardless of room. `interval="preserveStartEnd"` + `minTickGap`, the same
   treatment the customer-app charts already had. 3 → 3.
2. **Shorten the labels.** They were plotting raw ISO dates — `2025-09-01`,
   ten characters where three convey the same thing. A `monthTick` formatter
   renders `Sep 25`. 3 → 2. Better, still colliding.
3. **Pad the axis.** The remaining collision was the *first* X tick sitting
   flush against the Y axis and landing on its own "0" label — positional, not
   textual, which is why shortening the text could never have fixed it.
   `padding={{ left: 18 }}`. **2 → 0.**

The console's ticks moved onto `CHART_TICK_FONT_PX` along the way, so they are
no longer the last hardcoded font size in the product.

Nothing else moved: `target-aa` 28 and `target-project` 67 both unchanged
across all 32 routes.

## 3. Metric-matched fallbacks

With `display=swap` and no correction, every heading reflowed ~9.5% the moment
the webfont landed. A `size-adjust` fallback closes that: the fallback renders
at near the webfont's proportions from first paint, so the swap changes the
letterforms and little else.

**Two mistakes were made getting there, both caught by measuring rather than
reasoning:**

- **109.53% overshot by 7% the other way.** The number was taken from a
  measurement against SF — but the `local()` list resolves to Helvetica Neue on
  macOS long before it reaches SF. The correction has to be measured against
  the face that will actually be picked, not the one named in the variable.
  Corrected to 102.5%, which splits Helvetica Neue (mac) and Arial (Windows) to
  within ~1% either way. Drift: **-7.50% → 0.43%**.
- **Ascent/descent overrides were invented, so they were removed.** A wrong
  ascent moves every line box in the product, and there was no measurement
  behind the numbers.

**There is deliberately no mono fallback face.** One was written for symmetry
and made things actively worse: when a `local()` list matches nothing, the
`@font-face` resolves to the browser's default *proportional* face, so the
ledger column fell through to Times and measured **25.7% narrow**.
`local("Menlo")` does not match by that name. It was never needed — Spline Sans
Mono and the platform monospace agree to 0.34% — so the ledger stack points
straight at `ui-monospace`. Symmetry in a stylesheet is not a reason to add a
failure mode.

## 4. Self-hosted

The faces used to load from **Google Fonts**: a third-party request on every
page view, carrying the visitor's IP and user-agent, on a product whose own FAQ
says

> *"there is no third party holding your banking credentials"*

and whose landing page argues at length that it can be trusted with money.
Serving a typeface from an advertising company sat badly next to that, and in
the EU it has been litigated directly.

It was also a hard dependency on someone else's uptime — **and that stopped
being hypothetical during this work.** The host became unreachable and the
request *hung* rather than failing, which stalled page load until Playwright
timed out at 30s and took the route audit down with it. A stylesheet in `<head>`
is a synchronous dependency; a slow third party is a slow product.

Both families are OFL-licensed, so they now ship with the app:

- **14 `woff2` files, 432 KB total**, in `frontend/app/public/fonts/`.
- **Google's own `unicode-range` split is preserved**, not flattened. A page of
  Latin text fetches six files (~256 KB) and never touches the extended set —
  verified in the browser.
- **Two preloads only**, for the body weight and the ledger weight that paint
  above the fold. Preloading all fourteen would compete with the app bundle to
  render text nobody is looking at. `crossorigin` is required even same-origin,
  or the preload is discarded and the font fetched twice.
- **`OFL.txt` ships in the same directory.** The licence requires the notice to
  travel with the fonts, so it lives next to them rather than only in the repo.
- **`scripts/fetch_fonts.py`** regenerates everything. Adding a weight means
  editing the `FAMILIES` dict and re-running — the `@font-face` block in
  `typography.css` is bracketed by markers and rewritten in place, so nobody
  hand-edits fourteen rules.

Third-party font requests on first load: **0**, confirmed from the browser's
own resource timings.

The metric-matched fallback is still worth keeping: a cold cache still paints
one frame before the local file is parsed.
