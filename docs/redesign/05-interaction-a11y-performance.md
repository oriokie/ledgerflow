# Interaction, Accessibility, Mobile & Performance

---

## 1. Interaction guidelines

### 1.1 The rule

**Every interaction must make the product feel *faster* or *more certain*.**
Motion that does neither is decoration, and decoration in a finance product
reads as unseriousness. This is the test each item below has to pass.

### 1.2 Feedback timing

| Latency | Response |
|---|---|
| < 100ms | Nothing. Just render the result |
| 100–300ms | Optimistic update; the control shows its new state immediately |
| 300ms–2s | Skeleton matching the final layout |
| > 2s | Skeleton + "Still working…" after 2s |
| Failure | Revert, **and say so** — a silent rollback is worse than the original latency |

The last row is already the product's stated position (`PX_AUDIT.md`) and it is
correct. Generalise it: every optimistic path needs a visible failure path.

### 1.3 The interaction inventory

| Element | Behaviour |
|---|---|
| **Button** | `:active` scales to 0.98 for 80ms. Loading replaces the label with a spinner **at fixed width** so the button never resizes |
| **Card** | Hover lifts 1px + `hover` shadow. Only if the whole card is a link |
| **Row** | Hover tints to `bg-sunken`. Selected gets a 2px `meridian` left rule — never a full-row fill, which fights the amount column |
| **Input** | Focus: 2px `meridian` ring at 2px offset. Error: `vermilion` border + message below, never a tooltip |
| **Toggle** | Knob travels 150ms `ease-settle`; track colour crossfades over the same window |
| **Segmented** | The indicator *slides* between segments (200ms). One implementation replaces the five found in the audit |
| **Modal** | Backdrop fades 150ms; panel rises 12px + fades 200ms `ease-enter`. Focus trapped; `Esc` closes; focus returns to the trigger |
| **Drawer** | Slides from the edge it is anchored to, 200ms. Mobile: swipe-to-dismiss |
| **Toast** | Rises 12px, auto-dismisses at 5s, pauses on hover, stacks to max 3 |
| **Command palette** | Opens instantly (no animation — it is a keyboard tool). Results filter per keystroke with no debounce under 50 items |
| **Number** | Counts up 320ms on first paint only. **Never on refetch** — a number that re-animates on every poll reads as instability |
| **Chart** | Draws left-to-right 320ms, once per mount. Never on data refresh |
| **Confetti** | Goal completion only |

### 1.4 Forms

| Rule | Detail |
|---|---|
| **Validate on blur, re-validate on change** | Never validate on first keystroke — it accuses the user mid-typing |
| **Currency input** | Right-aligned, ledger face, currency prefix fixed outside the editable region, grouping applied on blur |
| **Date input** | Free text accepting "tomorrow", "next friday", "15/3" alongside the picker |
| **Searchable select** | Any list over 8 items. Account and category pickers always |
| **Smart defaults** | Date = today; account = most-used for that category; currency = workspace base |
| **Autosave** | Settings and preferences. Explicit save for anything that posts to the ledger — money movement is always deliberate |
| **Undo** | Toast-level undo for categorise, delete, bulk edit. 10-second window |
| **Destructive confirm** | Type-to-confirm only for workspace deletion; everything else is a confirm dialog naming the object |

### 1.5 Keyboard

| Key | Action |
|---|---|
| `⌘K` | Command palette |
| `⌘⇧K` | Workspace switcher |
| `G` then `T`/`A`/`P`/`I` | Go to Today / Activity / Plan / Insights |
| `N` | New transaction |
| `/` | Focus search in the current list |
| `J` / `K` | Move down / up a list |
| `E` | Edit focused row |
| `X` | Select focused row |
| `?` | Shortcut help |
| `Esc` | Close, deselect, clear |

`ShortcutHelp.tsx` and `shortcuts.ts` already exist — this extends rather than
replaces them.

---

## 2. Accessibility

### 2.1 Fix the five confirmed failures

| # | Failure | Fix | Criterion |
|---|---|---|---|
| 1 | Two inputs share one "Name" label (Settings) | Split with individual `<label for>` | 3.3.2 |
| 2 | Primary content absent from heading outline (Accounts, Goals) | Panel titles → `<h2>`, card titles → `<h3>` | 1.3.1 |
| 3 | 9.44px rendered text | Ban `em` font sizing; token steps only | 1.4.4 |
| 4 | Admin nav links ~26px wide on mobile | Drawer + bottom bar | 2.5.5 |
| 5 | Colour-only meaning in Coach numerals | Label accompanies every coloured figure | 1.4.1 |

### 2.2 Keep what already works

`tokens.css` ships a verified AA floor, a `prefers-contrast: more` block,
`prefers-reduced-motion` handling, a skip link, and `--lf-touch-target: 44px`.
This is above category average and none of it changes.

### 2.3 Standing rules

- **Focus is never invisible.** `:focus-visible` on every interactive element,
  2px `meridian` at 2px offset, verified ≥3:1 on all six surfaces (§2.3 of the
  design system)
- **Colour is never the only channel** — the chart rule (§2.6) generalised
- **Every icon-only control** carries `aria-label`
- **Live regions**: balance updates and toast messages announce via
  `aria-live="polite"`; nothing announces `assertive` except a failed payment
- **Reduced motion** collapses all durations to 0.01ms, disables count-up,
  shimmer and confetti
- **Zoom to 200%** without horizontal scroll at every breakpoint

### 2.4 Verification

Three layers, because manual audits do not hold:

1. `scripts/verify_palette.py` in CI — contrast and CVD
2. `axe-core` in the existing Vitest suite, per route
3. A rendered-DOM assertion per route: heading outline is well-formed, no text
   under 11px, no interactive target under 44px, no horizontal overflow at
   375px. This is the harness that would have caught all five failures above —
   it is the same measurement approach used to *find* them in this audit.

---

## 3. Mobile

### 3.1 The contract

> On a 375×812 viewport, the primary figure of any screen renders within the
> first 480px.

Measured today on Today: **y = 1233px**. This is the single most important
mobile change and it is testable.

### 3.2 Rules

| Rule | Detail |
|---|---|
| **Mobile-first CSS** | All queries `min-width`. The 14 breakpoints collapse to 6 tokens |
| **Tables become cards** below `md` | A financial table cannot shrink; it must restructure |
| **Bottom bar, 5 slots**, centre is the `+` action | [`02-strategy-ia.md §3.3`](02-strategy-ia.md) |
| **Thumb zone** | Primary actions in the bottom third. Destructive actions never there |
| **Sheets, not modals** | Bottom sheets with swipe-to-dismiss |
| **44px minimum**, 8px between targets | — |
| **No hover-only affordances** | Row actions are visible or in a `⋯` menu |

### 3.3 Ultrawide

At `2xl` (1600px+) the rail stays expanded and the content column widens to
1440px. Above 1920px the dashboard moves to a three-column layout rather than
adding margin. The app must never be a 1200px strip in a 2560px void
[A§1.2].

---

## 4. Performance

### 4.1 What is already right

Route-level code splitting across all 42 routes; the admin console in its own
chunk so customers never download it; optimistic mutations; React Query with
tenant-scoped keys. This is a well-built front end.

### 4.2 What to fix

| Issue | Fix |
|---|---|
| **27 stylesheets (~250KB) load globally** | A `/login` visit downloads `debt.css`, `cashflow-calendar.css` and `admin.css`. Co-locate styles with their route chunk. The composite-component work (§7 of the design system) deletes ~116 selectors on its own |
| **Service worker fails to register** | `sw.js` served as `text/html` in dev. Verify against a production build before assuming it is dev-only |
| **Recharts on the dashboard** | Already split. Keep it out of the initial chunk; the sparkline can be a hand-rolled SVG path — it is 20 lines and removes a heavy dependency from the most-visited route |
| **No route-level prefetch** | Prefetch the Activity chunk on rail hover; it is the second destination in nearly every session |

### 4.3 Budgets

| Metric | Target |
|---|---|
| Initial JS (login route) | < 120KB gzipped |
| Initial CSS | < 40KB gzipped |
| LCP on Today, 4G | < 1.8s |
| INP | < 200ms |
| CLS | < 0.05 — skeletons must match final layout exactly |

The count-up animation is a CLS risk: reserve the final width with
`font-variant-numeric: tabular-nums` and a fixed `min-width` so the hero figure
never reflows mid-animation.

---

*Continues in [`06-roadmap.md`](06-roadmap.md).*
