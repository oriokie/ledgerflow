# LedgerFlow Design System

Premium financial interface language for LedgerFlow, drawing on the lineages
the brief names — Apple (type discipline, continuous radii, native feel),
Stripe (cool neutrals, layered ink shadows), Linear (keyboard-first app
shell, iris accent), Revolut (money as the hero), Notion (calm surfaces).
Everything lives in `frontend/design-system/`; the intelligent-dashboard
information architecture and insight catalog are documented separately in
`frontend/INTELLIGENT_DASHBOARD.md`:

| File | Role |
|---|---|
| `tokens.css` | Single source of truth: primitives + semantic tokens, light & dark |
| `base.css` | Reset, type rhythm, the ledger-amount signature, accessibility floor |
| `components.css` | App shell, nav, buttons, forms, cards, badges, tables, meters, modal, toast, empty, skeleton |
| `index.html` | Living reference: palette, type, every component |
| `dashboard.html` | **Intelligent dashboard**: safe-to-spend hero, insight cards, tiered progressive disclosure (see `INTELLIGENT_DASHBOARD.md`) |
| `transactions.html` | The ledger table + filters + add-transaction form |
| `app.js` | Theme persistence + the ⌘K command palette (native `<dialog>`) |

Static and framework-agnostic on purpose: the tokens are plain CSS custom
properties a future React app imports unchanged, and the demos run by opening
the files — no build step.

## The signature: the ledger column

The most characteristic artifact of this product's world is the ledger
column, so it is the one place the system spends its boldness:

- **Every monetary amount** renders in a duospace ledger face (Spline Sans
  Mono), tabular by construction — columns align like a ledger.
- **Signs are explicit** (−, +, ⇄). Color reinforces meaning but is never the
  only signal (color-blind safe).
- **Cents are de-emphasized, never hidden** (62% opacity, 0.85em) — honest to
  an engine that stores exact integer minor units.
- Statement tables carry a **running balance** column; in the demo it is real
  arithmetic, and the verification script proves it.

Markup uses the semantic `<data>` element so the machine-readable value rides
along with the display form:

```html
<data class="lf-amount lf-amount--out" value="-86.20">−$86<span class="lf-amount-cents">.20</span></data>
```

## Money color semantics — the one opinion

| Movement | Color | Why |
|---|---|---|
| Money in | Verdant `#0E7A5F` | Earning is the highlighted event |
| Money out | Ink `#151928` | **Spending is normal life, not an error** |
| Transfer | Muted ink | Moving your own money is neutral (mirrors the engine: transfers are excluded from income/expense) |
| Over-budget / errors / destructive | Carmine `#C13A4B` | Reserved for genuinely wrong states |

A grocery run never gets the same color as a failed payment. This mirrors the
backend's own semantics (signed amounts; transfers net to zero and are
excluded from cash flow).

## Palette

Six named colors; everything else is a tint/shade of these. Ink `#151928`
(blue-black text and dark surfaces — never pure black), Fog `#F6F7F9` (light
app background), Iris `#5558D9` (primary action, focus, selection), Verdant,
Carmine, Amber `#A16207` (pending/warnings). Semantic tokens
(`--lf-text-primary`, `--lf-action-primary`, `--lf-money-in`, …) sit on top of
primitives; components reference semantics only, so the dark theme is one
swapped block in `tokens.css` (`[data-theme="dark"]`) with zero component
changes. Dark mode is ink-based, not pure black, and its primary-button hover
*deepens* rather than brightens — the white label must stay ≥4.5:1 in every
state (the verification script checks the hover state explicitly).

## Typography

| Role | Face | Rationale |
|---|---|---|
| Display | Schibsted Grotesk | Characterful grotesk for headings and hero balances |
| Body/UI | System humanist stack | SF Pro on Apple hardware — the literal Apple lineage, zero font cost, native feel |
| Ledger | Spline Sans Mono | The signature — all money, amount inputs, `kbd` |

Modular scale, 1.20 ratio, 16px base: 11.1 / 13.3 / 16 / 19.2 / 23 / 27.6 /
39.8 px — all `rem`, so user font-size preferences hold. Tight tracking
(−0.015em) at display sizes; wide tracking (0.06em) on uppercase eyebrows.

## Spacing, radii, elevation, motion

- **4px base grid** (`--lf-space-1..16`), 8pt-friendly.
- **Radii**: 6 (inputs/badges) → 10 (buttons) → 16 (cards) → 20 (modals) →
  pill. Apple-adjacent continuous feel.
- **Elevation**: two layered low-alpha ink shadows (`raised`, `overlay`) —
  Stripe lineage; borders carry most separation, shadows are quiet.
- **Motion**: 120/200ms, one ease-out curve. `prefers-reduced-motion`
  collapses all animation globally.

## Layout & navigation (mobile-first)

Base styles are the phone layout; `min-width` queries add structure at 640,
768 and 1024px:

- **Mobile**: sticky topbar + content + fixed bottom tab bar (safe-area
  aware, 44px+ targets).
- **≥1024px**: persistent left rail (232px) replaces the tab bar; topbar
  keeps the workspace switcher (multi-tenancy is a first-class product
  concept) and the ⌘K search hint.
- Content max-width 1200px. Card grids collapse 3→2→1.
- **The ledger table reflows on mobile**: header row hides, each row becomes
  a two-column stacked card (payee/meta left, amount right), and
  lower-priority columns (`.lf-col-hide-mobile`) drop — no horizontal
  scrolling for the primary use case.

## Accessibility floor (verified, not asserted)

`scripts/check_design_system.py` (stdlib-only) runs four checks:

1. **WCAG 2.1 contrast** for 32 semantic fg/bg pairs per theme (64 total):
   text ≥4.5:1 (AA normal text — even 11px meta text is held to this),
   non-text focus indicators ≥3:1 (1.4.11). Includes interactive *states*
   (button hover).
2. **Token integrity**: every `var(--lf-*)` in any CSS/HTML file resolves to
   a definition in `tokens.css`.
3. **HTML well-formedness** (tag balance) for all three pages.
4. **Ledger arithmetic**: the transactions demo's running-balance column
   satisfies `balance[i+1] = balance[i] − amount[i]`.
5. **Chart proportionality**: every bar chart's fill widths match
   `value / max(values)` to within 0.25pp — a chart that lies about its
   own numbers fails the build.
6. **Page wiring**: each page carries the no-flash theme snippet in
   `<head>`, includes `app.js`, and contains the command-palette dialog.

First run found **7 real contrast failures** the eye missed: the light
tertiary gray was 2.29:1 on hover rows (used for 11px meta text), dark
tertiary was 3.75:1, and the dark primary button was 4.13:1 — with the
original *hover* state even worse at 3.23:1, which is why the hover pair is
now an explicit check. Fixes: a new `--lf-ink-400` text primitive (decoupled
from `--lf-ink-300`, which remains borders-only and is commented as such),
lightened dark tertiary, darkened dark primary with a deepening hover.
**All 54 pairs now pass.**

Also on the floor: visible `:focus-visible` rings everywhere, skip links,
`aria-current` navigation, semantic tables (`caption`, `scope`), labeled
form fields with `aria-describedby` errors and `aria-invalid`, `role="meter"`
budget bars with value text, 44px minimum touch targets, and real `<button>`
/ `<label>` / `<fieldset>` elements rather than div soup.

## Consuming the system from a future React app

1. Import `tokens.css` (and optionally `base.css`) once, globally.
2. Reference semantic tokens only (`var(--lf-text-secondary)`), never
   primitives — retheming and dark mode stay free.
3. Set `data-theme="dark"` on `<html>` to switch themes; persist the choice.
4. Port components as thin JSX over the existing classes, or restyle a
   headless library (Radix/Ark) with these tokens.
5. Keep the ledger-amount contract: `<data value>` with sign-explicit
   display text and the `lf-amount--{in,out,transfer,danger}` semantic.

## Shipped in the finalization pass

- **Charts**: a five-color categorical ramp (`--lf-chart-1..5`: iris,
  verdant, amber, plum, steel — **carmine deliberately absent**, so a
  spending category can never look like an error) and a CSS-only bar-chart
  component (`.lf-bars`). Amounts always remain visible as ledger text; bars
  only reinforce them. Fill widths are verified proportional to the data.
- **⌘K command palette**: a working `<dialog>` built on the modal primitive
  (`.lf-cmdk`), opened by the topbar Search buttons or ⌘K/Ctrl+K, with
  type-to-filter, an empty state, backdrop-click and native Esc close. This
  also gives `.lf-modal` its live demonstration.
- **Theme persistence + OS auto-switch, no-flash**: a tiny inline `<head>`
  script (runs before first paint) applies the persisted choice from
  `localStorage`, falling back to `prefers-color-scheme`; the toggle in
  `app.js` persists changes. No flash of the wrong theme on load.
- **RTL groundwork**: table headers/ledger columns and the amount input use
  logical `text-align: start/end`; the skip link uses `inset-inline-start`.

## Deliberately deferred

- **Density modes** (comfortable/compact tables).
- **Full RTL audit** (logical-property groundwork is in; a real audit needs
  RTL content and a native reviewer).
- **Richer chart types** (trend lines, donuts) — they need a charting layer
  in the app; the ramp and the amounts-stay-text principle are the seam.

---

## The React component library (`app/src/ui/`)

The CSS above is the portable foundation. On top of it sits a typed React
component library so application pages compose components instead of
hand-writing `.lf-*` class strings and inline styles. This closed a real gap:
before it existed, pages carried 135+ inline `style` objects and ~90 repeated
raw field markups, which is how visual drift creeps in.

Because every component references **semantic tokens only**, dark mode and any
future retheme flow through with zero component edits.

### Import surface

One barrel, `app/src/ui/index.ts`:

```tsx
import { Button, Card, FormField, Input, Stack, Table } from "../ui";
```

### Catalog

| Group | Components |
|---|---|
| Layout | `Stack`, `Inline`, `Grid`, `Divider`, `Spacer` |
| Typography | `Heading` (1–3), `Text` (tone/size/weight), `Eyebrow`, `PageHeader` |
| Actions | `Button` (variant/size/loading/block/icon), `IconButton` (label required) |
| Forms | `FormField`, `Input` (+amount), `Textarea`, `Select`, `Switch`, `Checkbox`, `SegmentedControl` |
| Containers | `Card` (title/eyebrow/action/highlight), `CardHeader`, `Badge`, `Chip` |
| Overlays | `Modal` (footer slot; sizes sm/md/lg) |
| Data | `Table` (config-driven columns, controlled sort), `Meter`, `Money` |
| Feedback | `Banner` (4 tones), `Spinner`, `Skeleton`, `SkeletonCard`, `LoadingBlock`, `EmptyState` |
| Navigation | `Tabs` (ARIA tablist + arrow-key nav) |

`ui.css` holds the small amount of new CSS the React layer needs (spinner,
`Stack`/`Inline` primitives, button size + loading modifiers, table sort
affordance, in-page tabs) — all token-based, no new design decisions.

### Living documentation

`app/src/pages/ComponentShowcase.tsx` renders every component in its states.
It's mounted at **`/_ui`** behind an `import.meta.env.DEV` guard, so it's a
design-QA surface in development and never ships to production. It is
deliberately *not* a feature page.

### Conventions the components enforce

- **Money** always renders through `<Money>` (monospace ledger face; color =
  direction; carmine reserved for errors, never for ordinary spending).
- **Icon buttons must be labeled** — `IconButton` requires `label`.
- **Forms compose `FormField`** — label + error + hint + invalid state in one
  place; pass `error` and the field flips to invalid with `role="alert"`.
- **Tables are config-driven** — declare `Column<Row>[]`; the component owns
  markup + a11y, the parent owns sort order.
- **Spacing uses the scale** — `gap={4}` → `--lf-space-4` (16px); prefer
  `Stack`/`Inline`/`Grid` over raw margins.

### Extending

1. Reuse or add a token in `tokens.css` (never hardcode a hex in a component).
2. Add the CSS pattern to `components.css`, or `ui.css` for React-layer glue.
3. Wrap it as a typed component in `app/src/ui/`, export from `index.ts`, and
   add a demo to `ComponentShowcase.tsx`.

### Backward compatibility

The pre-existing ad-hoc components (`components/Modal.tsx`,
`components/EmptyState.tsx`) now re-export from `ui/`, so the ~16 existing pages
keep working unchanged while new work imports from `../ui`. Pages can be
migrated to the library incrementally.

---

## The authentication experience (`app/src/components/auth/`)

Every auth screen renders through one shared shell and a small set of reusable
auth composites, so spacing, the brand mark, and the flows stay consistent.

**Shared shell** — `AuthLayout` (brand + surface card + optional footer slot;
`maxWidth` for wider screens like the workspace picker) and `AuthDivider` (the
"or" separator). Login, Register, Accept-invite, Workspace-picker, and the OAuth
callback all use it; the shell markup lives in exactly one place.

**Reusable pieces:**
- `PasswordInput` (in `ui/`) — password field with an accessible show/hide
  toggle (`aria-pressed`, labelled, doesn't steal focus on click).
- `PasswordStrengthMeter` — live, dependency-free strength feedback on register.
  Guidance only; Django's validators remain the source of truth.
- `SocialAuthButtons` — Google/Apple via the real OAuth PKCE endpoints. If a
  provider isn't configured the authorize call 400s and the buttons show a calm
  inline note instead of a broken redirect.
- `PasskeyButton` — passwordless WebAuthn sign-in; hides itself where the
  browser lacks WebAuthn. A verified passkey satisfies MFA on its own.
- `PasskeyManager` — list / add / remove passkeys in Settings (runs the
  registration ceremony via `@simplewebauthn/browser`).

**Flows wired to real backend contracts:**
- Password login → optional TOTP second-factor step (backup codes accepted).
- Social login → provider redirect → `/auth/callback` (`OAuthCallbackPage`)
  exchanges `code`+`state`, then routes on (new accounts land in workspace setup
  via `ProtectedRoute`). The exchange is guarded against React's double-effect
  because the PKCE state is single-use.
- Passkey login → challenge → platform authenticator → verify → session.
- Settings security: TOTP enrol/disable, **backup-code regeneration**, and
  passkey management.

All session establishment (password, MFA, OAuth, passkey) funnels through one
`applySession` path in `AuthContext`, exposed to external flows as
`completeLogin(res)` — so no sign-in method can drift from the others.

Not built: password reset / email verification — there is no backend endpoint
for either, so no dead-end UI was added.

## Application shell

`AppShell` (`src/components/AppShell.tsx`) is the persistent chrome around every authenticated route. It composes small, independently testable pieces under `src/components/shell/`:

| Piece | Responsibility |
|---|---|
| `navConfig.ts` | Single source of truth for primary nav (sections + flattened list). Config, not markup — reused by the rail, drawer, and ⌘K palette. |
| `SidebarNav` / `BrandMark` | Grouped `NavLink`s (active style via `aria-current`) + brand lockup. |
| `WorkspaceSwitcher` | Tenant switcher dropdown (`menuitemradio` + `aria-checked`). |
| `NotificationCenter` | Bell + inline panel; unread dot, per-row severity, mark-read / mark-all-read. |
| `ProfileMenu` | Avatar dropdown: identity, light/dark/auto theme toggle, settings, log out. |
| `CommandPalette` | ⌘K global search over nav + quick actions; native `<dialog>` for focus-trap + Esc. |

**Responsive behaviour** is CSS-driven (`src/styles/shell.css`) so there's no flash on resize:

- **≥1024px** — fixed left rail (`.lf-rail`) + topbar.
- **<1024px** — rail hidden; a hamburger opens an off-canvas drawer (`.lf-drawer` + backdrop) that reuses `SidebarNav` and closes on navigation, backdrop click, or Esc.
- The topbar collapses progressively: the search box becomes icon-only below 768px, and the workspace name / avatar label hide below 640px.

**Shared behaviour** lives in two hooks: `useDismiss` (outside-click + Esc for every dropdown) and `useTheme` (light/dark/system, synced to the `data-theme` attribute the no-flash boot script in `index.html` reads).

Accessibility throughout: skip link, `aria-current`, `aria-haspopup`/`aria-expanded`, menu roles, `aria-pressed` on the theme toggle, `aria-selected` on palette rows, labelled icon buttons, and full keyboard nav (⌘K, arrows, Enter, Esc). Animations respect `prefers-reduced-motion`.

## Dashboard (Overview)

The Overview page (`src/pages/DashboardPage.tsx`) is the product's home. It orchestrates every data hook and passes plain props into presentational, independently testable section components under `src/pages/dashboard/`. Pure logic (period ranges, deltas, savings rate, category ranking) lives in `metrics.ts` with full unit tests; recharts theming is shared via `chart.tsx` (tokenized tooltip) and `chartTheme.ts` (axis/grid props, compact formatter).

**Information hierarchy** — most important first, detail on demand:

| Tier | Surface | Progressive disclosure |
|---|---|---|
| 1 | Net worth hero (figure + delta chip + inline sparkline) · Health score | Health "How this is scored" expands to component meters |
| 2 | Cash flow — income / spending / net tiles + savings-rate meter | Period control re-scopes all period data |
| 3 | **Trends** — one card, tabbed: cash-flow bars · net-worth area · spending forecast | Three views share one uncluttered card |
| 4 | Where money goes (ranked proportion bars) · Upcoming bills | Category list previews top 6, "Show all N" expands |
| 5 | Budget progress · Savings goals (meters) | Previews top lines; deep links to full pages |
| 6 | Insights (recommendation cards) | Hidden entirely when empty |
| 7 | Recent activity (compact list) | Deep links to full transactions |

**Period control** — a `SegmentedControl` (This month / Last month / 30 days / Year) drives cash flow and category breakdown via `periodRange()`.

**Data viz** — area/sparkline with gradient fills, grouped income-vs-spending bars with a net line, a forecast band, and CSS proportion bars for categories. Charts plot major currency units and format back to minor in the tooltip; every chart parent has an explicit height so recharts' `ResponsiveContainer` measures correctly. Colors come from `--lf-chart-1..5`.

**Responsive** — mobile-first: hero/planning grids collapse to one column, the where-money-goes split is `3fr 2fr` above 900px and stacked below, and chart heights step down on small screens. Empty states are guiding CTAs (add account, create a budget/goal), never blank cards.

## Accounts & wallets

The Accounts page (`src/pages/AccountsPage.tsx`) is a deep-linkable **master/detail** surface. Pure logic (liability detection, per-currency totals, grouping, statement in/out) lives in `pages/accounts/summary.ts` with full unit tests; the rest is small presentational components under `pages/accounts/`.

| Piece | Responsibility |
|---|---|
| `summary.ts` | `summarizeByCurrency`, `groupAccounts`, `statementSummary`, `isLiability`, `accountTypeLabel` — all pure. |
| `AccountTypeIcon` | Tinted glyph per type (iris for assets, carmine for liabilities). |
| `AccountList` | Master picker: assets/liabilities groups with subtotals, `aria-current` selection. |
| `AccountDetail` | Balance, this-month in/out/net summary, recent transactions with running balance, wallet assignment, prev/next stepping. |
| `WalletsSection` | Rolled-up per-currency wallet balances. |
| `StatementModal` | Full month statement with an in/out footer. |

**Clear balances** — a summary bar rolls every account into assets / liabilities / net for the primary currency (with a "+N more currencies" hint), each account row shows its own balance, and each group carries a subtotal.

**Transaction summaries** — the detail panel derives money-in / money-out / net for the month from the account statement (reusing the dashboard's stat-tile + `.lf-row-list` patterns), and lists recent transactions with their running balance.

**Intuitive navigation** — selection lives in the URL (`?account=<id>`) so it's shareable and survives reload; the list stays beside the detail on desktop, and prev/next arrows step through accounts. Below 900px the columns swap (list ⇄ detail) with a back affordance, driven by a `data-mobile-view` attribute — no JS breakpoint math.

## Transaction management

The Transactions page (`src/pages/TransactionsPage.tsx`) is a data-management surface built for speed: fast search, deep filtering, inline + bulk categorization, and receipt handling. Pure logic lives in `pages/transactions/filters.ts` and `bulk.ts` (fully unit-tested); everything else is small presentational components under `pages/transactions/`.

| Piece | Responsibility |
|---|---|
| `filters.ts` | `parseFilters`/`filtersToParams` (URL sync), `toApiFilters` (name/unit/date mapping), `activeFilterChips`, `countActiveFilters`, `parseCursor` — all pure. |
| `bulk.ts` | `bulkMessage` — turns a partial-success result into tone + copy. |
| `FilterBar` | Search box (debounced upstream), collapsible filter panel, removable active-filter chips. |
| `BulkActionBar` | Sticky bar shown on selection: bulk categorize, bulk void, clear. |
| `TransactionTable` | Selectable rows, select-all (indeterminate), inline category `<select>`, row-open. |
| `TransactionDetail` | Edit category/memo, tags, split, void, and receipts. |
| `ReceiptManager` | Lists attachments and uploads via drag/drop or click (presigned flow). |
| `AddTransactionForm` / `ImportModal` | Create and CSV import. |

**Fast searching** — a dedicated search box feeds `useDebouncedValue` (300 ms) so typing doesn't refetch or spam history; the debounced value is written to the URL as `?q=`.

**Filtering** — account, type, category, status, date range, amount range, and needs-review, all serialized to the URL (shareable, reload-safe) and surfaced as removable chips with a filter-count badge and "Clear all".

**Categorization** — every non-transfer row has an inline category `<select>` for one-click categorizing without opening anything; the detail drawer offers full editing and splitting.

**Bulk editing** — checkbox selection with an indeterminate select-all drives a sticky action bar. `useBulkUpdateTransactions` / `useBulkVoidTransactions` hit a single server batch endpoint (`POST /finance/transactions/bulk/`) that categorizes/voids in one request and reports per-row failures; the UI surfaces partial success via `bulkMessage`.

**Receipt management** — `useUploadReceipt` prefers the presigned direct-to-storage PUT (`request-upload` → PUT → `confirm`) and transparently falls back to streaming the bytes through the API (`POST /finance/attachments/{id}/upload/`) when the backend can't presign, so uploads work in every environment. Stored receipts are viewable via `GET /finance/attachments/{id}/download/` (presigned-GET redirect on S3, direct stream otherwise); `ReceiptManager` fetches the blob with auth and opens it.

**Pagination** — cursor-based Prev/Next parsed from the API's `next`/`previous` URLs via `parseCursor`; changing any filter resets the cursor and selection.

## Budgeting

The Budgets page (`src/pages/BudgetsPage.tsx`) visualizes spending against limits with a three-state progress bar, a period **pace marker**, clear alerts, and in-place editing. Pure logic lives in `pages/budgets/budgetMath.ts` (fully unit-tested); the rest is small presentational components under `pages/budgets/`.

| Piece | Responsibility |
|---|---|
| `budgetMath.ts` | `lineState`, `budgetTotals`, `periodProgress`, `overPace`, `projectedSpendMinor`, `sortLinesByRisk`, `budgetAlerts` — all pure. |
| `BudgetProgressBar` | Track + fill coloured by state, with an optional pace marker at the period-elapsed position. |
| `BudgetSummary` | Spent / budgeted / remaining, one large bar, and a plain-language pacing verdict. |
| `BudgetAlerts` | Over-budget and nearing-limit callouts (`.lf-insight` cards). |
| `BudgetLineRow` | Per-category bar with inline limit editing and remove-with-confirm. |
| `AddLineForm` / `CreateBudgetForm` | Add a category to a budget; create a budget. |

**Intuitive progress indicators** — a purpose-built bar (`.lf-budget-track`/`.lf-budget-fill`) coloured by state: under (verdant), nearing limit ≥85% (amber), over (carmine). Unlike the generic `Meter` (under/over only), it also renders a **pace marker** — a vertical line at the share of the period elapsed — so the reader sees whether spending is outrunning the clock.

**Clear alerts** — `budgetAlerts` splits lines into over-budget and nearing-limit; the summary states the pacing verdict, and `sortLinesByRisk` floats the most-at-risk categories to the top of the list.

**Fast editing** — each line edits in place (pencil → number input → save, in minor units) via `useUpdateBudgetLine`, and removes with a one-tap confirm via `useRemoveBudgetLine`; both are backed by real endpoints (`PATCH`/`DELETE /budgeting/budgets/{id}/lines/{lineId}/`). Deleting a budget archives it (`is_active=false`) so history is retained.

**Pacing** — the status endpoint returns `period_start`, `period_end`, and `as_of`; `periodProgress` turns them into elapsed days/fraction, and `overPace` / `projectedSpendMinor` drive the "ahead of pace / on track to spend $X" messaging.

## Savings goals

The Goals page (`src/pages/GoalsPage.tsx`) is built to motivate: a circular progress ring, a milestone checkpoint track, one-tap contributions, and a celebratory reached state. Pure logic lives in `pages/goals/goalMath.ts` (fully unit-tested); the rest is small components under `pages/goals/`.

| Piece | Responsibility |
|---|---|
| `goalMath.ts` | `milestones`, `nextMilestone`, `amountToNextMilestone`, `goalTotals`, `sortGoals` — all pure. |
| `GoalProgressRing` | SVG ring filling clockwise from the top, with 25/50/75% ticks; turns green when met. |
| `MilestoneTrack` | The four checkpoints as a track — each lights up as reached, the last shows the target amount. |
| `GoalCard` | Ring + figures + milestone track + one-tap contributions + next-milestone nudge + celebration + history toggle. |
| `ContributionHistory` | The momentum timeline (recent contributions, most recent first). |
| `GoalsSummary` | Saved-across-goals headline with an overall meter and achieved count. |
| `CreateGoalForm` | Create a goal. |

**Visual progress** — the `GoalProgressRing` is a self-contained SVG (arc via `stroke-dasharray`/`dashoffset`, rotated so it starts at 12 o'clock) with milestone ticks; the centre shows the percent and amount saved. It reads at a glance and turns `--lf-status-success` on completion.

**Milestone tracking** — `milestones` derives the 25/50/75/100% checkpoints (with the amount each represents and whether it's reached) client-side, so no backend milestone model is needed; `nextMilestone` + `amountToNextMilestone` drive the "$X to 75%" nudge that keeps the next win in view.

**Simple contributions** — `GoalCard` offers one-tap quick-add chips plus a custom amount, both posting via `useContributeToGoal`; achieved goals swap the inputs for a celebration. Contribution history comes from a new endpoint (`GET /goals/goals/{id}/contributions/`, most-recent-first) surfaced by `useGoalContributions`.

**Motivating order** — `sortGoals` floats in-progress goals (nearest completion first) above achieved ones, and `GoalsSummary` frames overall momentum across every live goal.

## Bills & subscriptions

Two related screens help users see money leaving on a schedule. `BillsPage` is the upcoming-payments view; `RecurringPage` is the subscription/recurring-spend view. (`BillingPage` is the app's own plan billing and is unrelated.) Pure logic lives in `pages/bills/billsMath.ts` and `pages/recurring/recurringMath.ts` (both unit-tested); components sit under those folders. Shared styles are in `styles/billing.css`.

| Piece | Responsibility |
|---|---|
| `billsMath.ts` | `daysUntil`, `dueLabel`, `billBuckets` (overdue/this-week/later/paid), `billTotals` — all pure. |
| `bills/BillComponents.tsx` | `DuePill`, `BillRow`, `BillGroup`, `BillsSummary`. |
| `bills/CreateBillForm.tsx` | Add a bill. |
| `recurringMath.ts` | `monthlyMinor`/`annualMinor` normalization, `recurringTotals`, `sortByMonthlyCost`, `cadenceLabel`, `recurringLabel` — all pure. |
| `recurring/SubscriptionRow.tsx` | One charge by normalized monthly cost, with pause/resume + cancel. |
| `recurring/SubscriptionSummary.tsx` | `SubscriptionSummary` stat band + `SubscriptionInsight` review nudge. |
| `recurring/CreateRecurringModal.tsx` | Add a recurring charge. |

**Identify upcoming payments** — `BillsPage` fetches `useBills({ upcoming: 45 })` (which includes overdue), then `billBuckets` splits into Overdue / Due this week / Later. Each `BillRow` carries a `DuePill` whose tone escalates (neutral → amber within 7 days → carmine overdue), and `BillsSummary` leads with overdue / due-this-week / due-in-30 totals.

**Identify recurring expenses** — the recurring serializer now exposes `memo`/`category_id`/`financial_account_id` so each schedule is nameable (`recurringLabel`). `recurringMath` normalizes any frequency × interval into a **monthly and annual** figure (365-day year, 52.14 weeks), so a weekly coffee and a yearly membership compare on equal footing.

**Reduce unnecessary spending** — `SubscriptionSummary`/`SubscriptionInsight` surface total annual recurring cost and the priciest few (`sortByMonthlyCost` puts them first), and every `SubscriptionRow` offers **pause/resume** (`PATCH is_active`) and **cancel** (`DELETE`, soft-delete) — the fastest levers to trim spend. Cancel keeps posted history; it only removes the template.

## Analytics

The Analytics page (`src/pages/AnalyticsPage.tsx`) presents financial trends with interactive charts, month-over-month comparisons, and category drill-down. Pure logic lives in `pages/analytics/analyticsMath.ts` (unit-tested); charts use Recharts inside `.lf-chart-container`. Styles are in `styles/analytics.css`.

| Piece | Responsibility |
|---|---|
| `analyticsMath.ts` | `rangeForMonths`, `delta`, `savingsRate`, `comparisonFromTrend`, `trendTotals`, `breakdownWithShare`, `topN` — all pure. |
| `ComparisonCards` / `DeltaBadge` | This-month-vs-last cards with tone-aware change chips (income up = good, expenses up = bad). |
| `CashFlowChart` | Income/expense bars + a net line over the selected range (Recharts `ComposedChart`). |
| `CategoryBreakdown` | Ranked, clickable spending-by-category bars scaled to the largest. |
| `CategoryDrilldown` | The selected category's month-by-month trend (area chart) + a jump to its transactions. |

**Interactive charts** — a time-range control (3/6/12 months) drives every panel. The cash-flow chart layers income and expense bars with a net line; tooltips format money in the display currency.

**Comparisons** — `comparisonFromTrend` diffs the latest month against the prior one; `DeltaBadge` colours each change by whether that direction is favourable for the metric, and a savings-rate card shows the point change.

**Drill-down** — clicking a category in `CategoryBreakdown` selects it; `CategoryDrilldown` then fetches that category's monthly series from a new endpoint (`GET /finance/category-trend/?category_id=&months=&type=`, dense zero-filled months) and can hand off to the transactions list filtered to that category (`/transactions?category=<id>`).

The range window is computed by `rangeForMonths` (trailing N calendar months incl. the current), shared by the cash-flow and breakdown queries so the panels always agree. Display currency uses the most relevant account currency; multi-currency aggregation across the backend series is a documented simplification, consistent with the other screens.

## AI insights

The Insights page (`src/pages/InsightsPage.tsx`) reframes the intelligence engine's raw outputs as warm, actionable guidance. All the wording/tone/routing logic is a pure, tested layer (`pages/insights/insightsCopy.ts`); components under `pages/insights/` render it. Styles are in `styles/insights.css`.

| Piece | Responsibility |
|---|---|
| `insightsCopy.ts` | `greeting`, `healthSummary`, `bandTone`, `recommendationTone`/`recommendationCta`/`recommendationBasis`, `anomalyView`, `confidenceLabel` — all pure. |
| `InsightsGreeting` | A plain-language check-in reflecting the health band and whether anything needs doing. |
| `GuidanceCard` | A recommendation as guidance: title, conversational body, one clear next step, and a quiet "based on…" note. |
| `HealthSummary` | The health score as a band + one strength + (only if lagging) one watch-out, with the full 5-part breakdown one tap away. |
| `AnomalyList` | Anomalies as "worth a look" notes with human headlines. |
| `SuggestionCard` | Categorization phrased as a question with a sureness cue, not a raw confidence %. |

**Actionable, not technical** — `recommendationCta` maps each recommendation's real `action` payload (`budget_rebalance`, `schedule_transfer`, …) to a concrete next step and destination (`/budgets`, `/bills`, `/recurring`); positive "good news" recommendations deliberately carry no action so guidance never nags.

**Conversational** — the page opens with a `greeting` ("Your money check-in — you're in good shape overall…"), anomaly `kind`s become sentences ("A charge that's higher than usual"), and confidence scores become words (`confidenceLabel`: "Fairly sure" / "Very sure").

**Trustworthy** — every guidance card shows an honest basis line (`recommendationBasis`), the greeting notes the data it's drawn from and that it isn't financial advice, and the health score is always decomposable via the full breakdown rather than presented as a black-box number. Tone accents map through the shared `.lf-tone-*` classes so severity reads at a glance without alarming colours everywhere.

## Settings

The settings area (`src/pages/SettingsPage.tsx`) is a grouped, two-pane shell: a sticky section nav beside routed panels. Each section is its own path (`/settings/<slug>`) so it's linkable and the surface never shows everything at once. Reusable primitives live in `pages/settings/components.tsx`; the nav config in `pages/settings/nav.ts`; styles in `styles/settings.css`.

| Piece | Responsibility |
|---|---|
| `nav.ts` | `SETTINGS_NAV` (grouped sections) + `SETTINGS_SLUGS` — the single source of truth for the sub-nav. |
| `SettingsNav` | Grouped, active-aware section links (shared by sidebar and mobile row). |
| `SettingsSection` | A titled block (title + description + optional action) — the container every panel builds from. |
| `SettingsRow` | One labelled setting: title/description left, control right; stacks on narrow screens; associates its `<label>` via `htmlFor`. |
| `SettingsAdvanced` | A collapsible disclosure for power-user options — labelled and one click away, collapsed by default. |
| Panels | `ProfilePanel`, `SecurityPanel`, `PreferencesPanel`, `WorkspacePanel`, `TaxonomyPanel` under `panels/`. |

**Grouped navigation** — `SETTINGS_NAV` splits sections into *Account* (Profile, Security, Preferences) and *Workspace* (General, Categories & tags). The shell uses a nested `<Routes>` so `/settings` redirects to `/settings/profile` and every section deep-links. The main app nav's "Settings" entry points at `/settings`.

**Reusable components** — panels are assembled from `SettingsSection` + `SettingsRow`, so spacing, labels, and control alignment are consistent everywhere and new settings are a few lines to add.

**Advanced without overwhelming** — the default view shows only the common controls. `SettingsAdvanced` tucks power-user actions (e.g. regenerate backup codes, turn off two-factor) behind a clearly labelled, keyboard-accessible disclosure (`aria-expanded`), so they're discoverable but never clutter the page. The heavier Members and Billing areas are surfaced as link cards from the Workspace panel rather than duplicated inline.

## Mobile usability pass

A cross-screen responsive review, applied as one cascade-final stylesheet (`styles/responsive.css`, imported last) plus a mobile bottom nav — desktop is untouched and feature parity is preserved (nothing is removed on small screens; dense tables already reflow via `Table`'s responsive card-stack and `hideMobile` columns).

**Navigation** — new `MobileTabBar` (`components/shell/MobileTabBar.tsx`) renders the five most-used destinations (Overview, Transactions, Budgets, Bills, Insights) as a fixed, thumb-reachable bottom bar under 1024px, using the pre-existing `.lf-tabbar` primitives; items derive from `tabBarConfig.ts` → `NAV_ITEMS`, so labels/icons/paths have one source of truth and the hamburger drawer still carries the full nav. `.lf-content` gains bottom padding below 1024px so pages clear the bar.

**Touch targets** — buttons, inputs, selects, and nav items already sit on `--lf-touch-target` (44px); the pass extends that to the gaps: interactive chips (`button.lf-chip`) get a ≥40px hit area on touch/narrow contexts, clickable analytics category rows get `min-height: 44px`, tab-bar items get 44px + tap-highlight suppression, and the icon-only Add-transaction link keeps an `aria-label` when its text hides on xs.

**Responsive layouts** — the feature styles that shipped without media queries now reflow: subscription rows wrap to name-line + cost/actions-line (<520px); bill rows stack to name / pill+amount / full-width pay controls (<640px); stat bands tighten and drop orphaned dividers; goal rings scale to 108px (<480px); budget line heads wrap; the analytics two-panel area uses `.lf-analytics-split` (1 column <900px) instead of a hard-coded inline grid; profile name inputs and taxonomy rows wrap.

**Typography & spacing** — hero amounts, the insights greeting, and goal-ring percentages step down one size under 640px so figures never force horizontal scroll; guidance cards and comparison values tighten. Form controls hold 16px on phones so iOS never zoom-jumps on focus.

**Overlays & safe areas** — modals cap at `90dvh` with internal scroll and become full-width bottom sheets under 640px (with safe-area padding); the drawer and topbar respect `env(safe-area-inset-*)` on notched devices; the tab bar already did.

## UX polish pass

A full-app audit of consistency, feedback, motion, and accessibility, applied as a feedback layer (`ui/Toast.tsx` + `ui/toastContext.ts`), targeted page fixes, and a cascade-final `styles/polish.css`.

**Feedback (the biggest gap)** — mutations previously succeeded silently. A minimal toast system now confirms actions: `ToastProvider` hosts a fixed viewport (`role="status"`, `aria-live="polite"`, capped at three, auto-dismissing) and `useToast()` fires from anywhere; the default context is a safe no-op so components work without a provider. Wired where money moves or settings change: "«Bill» marked as paid", pause/resume/cancel confirmations on subscriptions, "Profile saved" (replacing an inline note). The viewport clears the mobile tab bar and safe-area insets.

**Loading states** — the four screens that flashed blank on first load (Bills, Subscriptions, Insights, Analytics) now show `SkeletonCard` while their primary query loads, and their empty states no longer flicker in before data arrives.

**Empty states** — the last plain `lf-empty` paragraph (Notifications) became a proper `EmptyState` with an icon and a line about what will appear there, matching every other screen.

**Motion & micro-interactions** (`polish.css`, all neutralized by the global `prefers-reduced-motion` rule) — toasts and modals enter with a short fade-up (plus backdrop fade); each page announces itself with a single quick header fade rather than staggered cards; buttons and interactive chips acknowledge presses (`scale(0.98)`); only genuinely interactive cards lift on hover (link cards), and tappable list rows (subscriptions, bills, worth-a-look) gain a hover wash under `(hover: hover)` so touch devices skip it.

**Accessibility posture (verified during the audit)** — native `<dialog>` modals (focus containment + Esc for free), `aria-invalid` inputs with field-level errors, `aria-busy` loading buttons, `alert`/`status` banners, the skip link, 44px targets, and the global reduced-motion kill-switch were already in place; the pass added the polite toast live region and kept all motion opt-out.

### Bill cancellation

Each `BillRow` carries a trash affordance that reveals an inline confirm before calling `DELETE /finance/bills/<id>/` via `useCancelBill` (surfaced through `BillGroup`'s optional `onCancel`). Cancelling is a soft state change — the bill leaves the upcoming/overdue list and reads as `cancelled`, history retained — and confirms with an info toast. This closes the one real gap from the API-usage audit, where the cancel endpoint existed but had no UI.

## User-journey validation (Getting Started)

Rather than checking pages in isolation, the app is validated against end-to-end journeys. The **Getting Started** journey (Sign up → set currency → create first account → add first transaction) exposed a real continuity break that a page-by-page review missed: after creating a workspace, a brand-new user landed on a dashboard of empty $0 cards, and the Add-transaction form showed empty account/category dropdowns with no way forward. Three fixes close it:

1. **Default categories seeded on workspace creation** (`apps/tenancy/services.py` → `_seed_default_categories`). A new workspace arrives with a starter taxonomy (Housing, Groceries, Salary, …) so the owner can categorize their first transaction immediately. It runs under the new tenant's context (`use_tenant` + `bind_db_tenant`) inside its own savepoint — a failure is logged and rolled back, never allowed to break signup.
2. **Dashboard first-run checklist** (`pages/dashboard/GettingStarted.tsx`). When a workspace has no accounts or no transactions, the dashboard replaces the tier stack with a three-step checklist — create workspace ✓ → add first account → log first transaction — surfacing exactly one next action at a time. It disappears once both are done.
3. **Add-transaction account guard** (`AddTransactionForm`). With no accounts yet, the form shows a friendly "You'll need an account first" with a link to create one, instead of empty dropdowns.

The other journeys were validated as sound: **Daily Use** (dashboard "Add transaction" deep-links `/transactions?add=1`, which the page reads to open the form; cards link onward to budgets/goals/accounts) and **Monthly Review** (analytics category drill-down → transactions, budget edit, bill pay/cancel, and insight CTAs all connect across pages).

## Recovery journey (forgot password)

Journey validation of account recovery found the biggest gap so far: there was **no password reset at all** — no endpoint, page, or link — while MFA recovery (backup codes accepted at the login MFA step) already worked. A complete, secure reset flow was added.

**Backend** (`apps/users`): a `PasswordResetToken` model stores only the SHA-256 hash of a random, single-use, one-hour token (mirroring invitation tokens). `services/password_reset.py` exposes `request_password_reset` (finds an active user, invalidates prior tokens, issues a new one) and `reset_password` (validates the token under `select_for_update`, enforces the same password validators as registration, sets the password, marks the token used). Two `AllowAny`, `auth`-throttled endpoints: `POST /auth/password/reset/` and `POST /auth/password/reset/confirm/`.

**Security posture**: the request endpoint always returns the same 200 regardless of whether the email exists (no account enumeration); tokens are hashed at rest, single-use, and short-lived; requesting again supersedes the previous token. There's no email backend in this build, so delivery is a logged hook (where a mail/notification worker would send the link) and the raw token is surfaced in the response **only under DEBUG** for local testing — never in production.

**Frontend**: `ForgotPasswordPage` (`/forgot-password`) sends the request and shows neutral confirmation copy; `ResetPasswordPage` (`/reset-password?token=…`) validates presence of the token, enforces the 12-char policy with the strength meter, and on success routes to login with a success banner. A "Forgot password?" link sits under the login password field.

## Import-first onboarding

For users who'd rather import a bank CSV than key in a first transaction, `TransactionsPage` now honors `?import=1` to deep-open the existing `ImportModal` (matching the `?add=1` pattern), and the Getting Started checklist's transaction step offers "or import from your bank" alongside the manual add. (Couples/Family — invite → accept → roles — validated as already wired end to end via `MembersPage`/`AcceptInvitePage` and backend RBAC.)

## Subscription lifecycle (plan limits)

Journey validation of upgrade → plan-limits → downgrade found that plans carried entitlement columns (`max_accounts`, `max_members`, `ai_insights`) that **nothing enforced** — a paid feature that didn't exist in practice. Enforcement was added at the service layer.

**Model** (`apps/billing/entitlements.py`): `resolve_entitlements(tenant_id)` reads the tenant's active subscription. Limits apply only for `active`/`trialing` subscriptions; a tenant with **no active subscription is unmetered** (the pre-billing/grandfathered state — this is also what keeps the platform's own fixtures unconstrained). `ensure_can_add_account` / `ensure_can_add_member` raise `PlanLimitExceeded`, mapped by the global handler to **HTTP 402 Payment Required** with an upgrade-oriented message.

**Enforcement points**: `finance.create_financial_account` (counts active accounts vs `max_accounts`) and `tenancy.add_member` (counts memberships vs `max_members`), with a pre-check at `create_invitation` (members + pending invitations) so an owner is told before an invite is sent, not only at acceptance. The frontend already surfaces the 402 message via each form's error banner (`ApiError` normalizes the envelope to `.detail`).

**Proactive visibility** (`pages/billing/PlanUsage.tsx`): the Billing page shows accounts/members used against the active plan's caps with meters, flagging the at-limit state, so people see they're approaching a limit before an action is blocked. Downgrade/cancel already existed (`cancel_at_period_end`); the new usage panel makes the consequences of a plan change legible.

## AI-feature gating (closing the entitlements loop)

The `ai_insights` plan entitlement was resolved but ungated; this gates it, mirroring the account/member limits. The AI surfaces (health score, recommendations, anomaly detection, categorization suggestions) are premium; deterministic analytics (net-worth history, spending trend) stay available on every plan.

**Backend**: `entitlements.ensure_ai_insights(tenant_id)` raises `PlanLimitExceeded` (→ 402) unless the tenant is unmetered or on a plan with `ai_insights`. A `HasAIInsights` DRF permission (running after `IsTenantMember`) applies it to the five AI endpoints; the analytics endpoints are deliberately left open.

**Frontend**: `useAiEnabled()` mirrors the rule client-side (no subscription or non-active subscription → unmetered → enabled; otherwise the plan's `ai_insights`). The intelligence hooks take an `enabled` flag so gated tenants never fire dead 402 calls. `InsightsPage` shows an upgrade prompt (→ Billing) instead of the AI content, and the dashboard hides its health card and insights section when AI isn't included — degrading cleanly rather than erroring.

## Failed-payment / past-due dunning

When a renewal charge fails, the subscription needs a recovery path rather than a dead-end. The `payment.failed` webhook now flips an `active`/`incomplete` subscription to `past_due`, and `billing.retry_payment` re-charges the default method — reactivating on success, staying `past_due` with a clear reason on failure. `POST /billing/subscription/retry/` exposes it (owner/admin). On the Billing page a tone-appropriate banner appears for `past_due` (danger) and `incomplete` (warning) with a **Retry payment** action; the copy nudges updating the card first. Renewal *scheduling* (what moves a live subscription into `past_due` each period) is a Celery-beat concern left out of scope — this covers the webhook + user-initiated recovery.

## Data export & account closure (GDPR)

Two owner-only capabilities that were entirely missing despite a `WORKSPACE_DELETE` capability already existing in RBAC.

**Export** — `GET /tenancy/workspaces/<id>/export/` returns a portable JSON snapshot of the workspace's accounts, transactions, categories, payees, tags, bills, budgets, and goals (`data_export.export_workspace_data`, run under the tenant's context so RLS applies). The Settings → Workspace "Data & privacy" section downloads it as a file.

**Closure** — `DELETE /tenancy/workspaces/<id>/` performs an owner-only **soft close**: `Tenant.is_active` flips to false, the workspace immediately leaves every member's switcher (`memberships_for_user` filters inactive tenants), and a `tenancy.workspace.closed` outbox event is emitted for an async purge worker to carry out hard erasure after any grace period. This is deliberate — irreversible cross-table deletion (tenant data is UUID-linked, not FK-cascaded) is an asynchronous, auditable step, not a synchronous button press. The UI guards it behind the advanced disclosure with a type-the-exact-name confirmation, then hard-reloads so the closed workspace drops out of context.

## Auth experience & premium visual layer

The sign-in/out surfaces were rebuilt as a premium split screen, and a final cascade layer adds material depth app-wide.

**Split auth shell** (`components/auth/AuthLayout.tsx` + `styles/auth.css`) — every auth screen (login, register, reset, invite, workspace picker, logged-out) renders through one shell: a dark ink brand panel on the left with an ambient verdant glow, a faint ledger-grid texture, the brand mark, a tagline, and a **rotating famous quote on financial management**; the form sits on a clean card on the right. Under 900px the panel yields to a focused single column with a centered brand row.

**Rotating quotes** (`components/auth/financeQuotes.ts` + `QuoteRotator.tsx`) — a curated, attributed catalog (Buffett, Franklin, Jefferson, Epictetus, …) crossfading every 8s. The start index derives from the clock so refreshes don't always open on quote #1; rotation logic is pure and tested; the figure is `aria-hidden` (ambience — announcing a new quote every 8s would spam screen readers) and the fade is CSS-driven so `prefers-reduced-motion` disables motion globally.

**Logout journey** (`pages/LoggedOutPage.tsx`, route `/logged-out`) — the profile-menu Log out now awaits the token revocation and hard-navigates to a calm goodbye page in the same split shell ("You're signed out… your workspaces will be right where you left them") with one clear action: Sign back in. The hard navigation also guarantees all in-memory query caches die with the session.

**Premium layer** (`styles/premium.css`, imported last) — a faint verdant bloom at the top of the canvas so the app never reads as a flat gray sheet; a glassy blurred sticky topbar; refined two-layer card shadows; a subtle top-lit gradient + inner highlight on primary buttons; and a verdant indicator bar on the active nav item. No layout changes — pure material.

## Appearance customization (accent + density)

Settings → Preferences now offers three appearance controls, all device-local:

- **Theme** — light / dark / system (pre-existing).
- **Accent color** — Iris (default), Verdant, Ocean, Plum, Ember. `lib/appearance.ts` persists to `lf-accent` and sets `data-accent` on `<html>`; `styles/appearance.css` re-points the semantic tokens (`--lf-action-primary(+hover)`, `--lf-focus-ring`, `--lf-selection-bg`, `--lf-text-link`) per accent, with lighter link/selection variants under `[data-theme="dark"]`. Because every button, link, active-nav indicator, meter, and the premium gradient is built on those tokens, one attribute recolors the whole app.
- **Density** — comfortable / compact. Compact tightens the spacing scale (`--lf-space-3…6`) and the topbar height; the 44px touch-target token is deliberately untouched so tap ergonomics survive.

The `index.html` no-flash boot script applies stored theme, accent, and density before first paint, and `initAppearance()` keeps React state in sync. Defaults store nothing (choosing Iris/Comfortable removes the keys), so a fresh device is byte-identical to today's look. The accent picker renders as a `radiogroup` of color swatches with `aria-checked` and visible focus rings.

## Typography customization (font family + text size)

Preferences gained two more appearance controls on the same architecture as accent/density: **Font** (Grotesk — the product's own voice — plus System and Serif; `data-font` re-points `--lf-font-display`/`--lf-font-body`) and **Text size** (S/M/L/XL; `data-fontsize` scales the root font-size 93.75–112.5%, and because every token is rem-based, text and rhythm scale together — the standard accessibility approach). Both persist to localStorage (`lf-font`, `lf-fontsize`), are applied by the no-flash boot script, and store nothing at their defaults.

## Cashflow statement (liquidity)

Analytics now ends with a proper monthly **cash flow statement** — the liquidity tool a balance list can't be: for each of the last six months, money in, money out, net, and the **ending liquid balance** (checking + savings + cash in the dominant currency), with "liquid today" and average monthly net summarized above. Ending balances are walked backwards from today's *actual* liquid balance using each month's true liquid movement — transfer legs included, so moving cash into an investment correctly shows liquidity leaving even though it isn't "spending." Inflow/outflow columns exclude transfers, matching the existing cash-flow semantics. `GET /finance/cashflow-statement/?months=N` (deterministic accounting — not AI-gated).

## Cash runway ("will I run out of cash?")

The Insights page now leads with the question every budget app dodges, answered plainly. `GET /intelligence/cash-runway/` combines **today's liquid balance**, the **average net flow over the last three full months** (the in-progress month is excluded — partial data skews burn), and **bills due within 30 days**. If the trend is negative: runway = balance ÷ burn, with a projected run-out date ("At this pace you could run out of cash around 19 October 2026") and status tiers — critical (<3 months), warning (<6), watch (<12), healthy. A positive trend reports healthy — unless the next 30 days of bills exceed the balance, which is critical regardless of trend. Under two full months of history returns `insufficient_data` — an honest "not enough history yet" rather than a guess. Gated behind the `ai_insights` entitlement like the other forward-looking features; the card's left border, icon, and copy all carry the status tone.

## Multi-currency: lookup, FX, and editable base currency

Five related fixes turned currency from a free-text field into a modelled concern.

**Currency is now a lookup.** A 37-entry ISO 4217 catalog (`apps/fx/currencies.py` + mirrored `lib/currencies.ts`) carries code, name, symbol, and minor-unit digits (JPY 0, KWD/BHD 3). Account creation uses a dropdown defaulting to the workspace base currency, and `GET /fx/currencies/` exposes the catalog.

**FX conversion** (`apps/fx/services.py`): `latest_rate` resolves a pair directly, by inverse, or by triangulating through USD; `convert` returns `None` when no rate exists so callers degrade honestly instead of fabricating a number. Reference rates ship via a seed migration; `refresh_rates` is the hook for live provider ingestion. Endpoints: `/fx/rates/`, `/fx/convert/`.

**Base currency is editable** — owner-only `PATCH /tenancy/workspaces/<id>/` validates against the catalog. Changing it affects reporting defaults and consolidation only; existing transactions keep their own currency.

**Consolidated net worth**: `GET /finance/net-worth/base/` rolls mixed-currency holdings into the base via FX, returning a `converted` flag. The dashboard shows "≈ $X total across N currencies" only when more than one currency is held, and says "(some rates unavailable)" rather than implying false precision.

**Transactions post in the account's currency.** Previously a category's ledger account was pinned to one currency, so spending from a differently-denominated account raised a cross-currency error. `_category_ledger_for` now finds-or-creates a per-currency sibling ledger account, so one "Groceries" category serves USD and EUR accounts alike while every journal entry stays single-currency and balanced.

**Modal centering**: the global `* { margin: 0 }` reset defeated the UA stylesheet's `margin: auto` on `<dialog>`; `.lf-modal[open]` now centers explicitly (`position: fixed; inset: 0; margin: auto`) with a max height and scroll for tall content.

**Entitlement checks are defensive**: `resolve_entitlements` catches `ProgrammingError`/`OperationalError` (e.g. billing tables not yet migrated) and falls back to unmetered — a billing-layer problem must never 500 core finance operations like account creation.
