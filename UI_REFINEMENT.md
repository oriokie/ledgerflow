# LedgerFlow UI refinement

A refinement pass over the existing interface — not a redesign. The palette,
typography, navigation, and layout philosophy are unchanged; what changed is
hierarchy, material, spacing discipline, and interaction feel.

Everything below is driven by the existing semantic token system, so custom
accents, dark mode, density, and font-size preferences all continue to work
without per-component handling.

## Design system

**Vertical rhythm is now a contract, not a habit.** Four semantic tokens
(`--lf-rhythm-title` 24px, `-section` 32px, `-card` 24px, `-field` 20px)
replace ad-hoc spacing picks. Bigger gaps between things that differ in kind,
smaller gaps between things of the same kind — hierarchy carried by whitespace
rather than heavier rules or louder color.

**Elevation is a four-step ramp** (`sm` / `raised` / `hover` / `overlay`), each
a hairline contact shadow plus one diffuse ambient layer. Depth comes from
blur, never opacity: heavy shadows read as consumer software, diffuse ones read
as instrument panels.

**Cards get their own border token** (`--lf-border-card`), one step above
dividers, so a surface reads as a distinct object even where the shadow is
invisible — dark mode, forced contrast, low-quality displays.

**High contrast is supported** via `prefers-contrast: more`: borders become
real lines, tertiary text is promoted, and every decorative finish (gradients,
blur, washes) is dropped, since they all reduce edge definition.

## Hierarchy

Page titles previously rendered at the same size and weight as section titles,
which made every page read as a flat list of equals. Page titles now sit a full
scale step above, with heavier weight and tighter tracking.

This required moving `Heading` sizing out of inline styles into CSS classes —
inline styles are unbeatable by contextual rules, so no amount of CSS could
have fixed it otherwise.

Card prominence is expressed through material: `primary` cards take more
padding and a deeper shadow, `quiet` cards drop elevation entirely.

## Components

| Area | Change |
|---|---|
| **Sidebar** | 232px → 216px. Wash-style hover, animated active indicator (compositor-only `scaleY`), icon color transitions, tighter section grouping. |
| **Cards** | Stronger border, softer elevation, `primary`/`quiet`/`interactive` variants. Only actionable cards lift. A clickable card renders as a real `<button>`. |
| **Forms** | Roomier padding, radius bump, focus ring drawn with `box-shadow` so nothing reflows. Full state coverage: hover, focus, disabled, readonly, invalid, valid, busy. Leading/trailing adornments. Custom select chevron with a dark-mode variant. |
| **Buttons** | Unified focus rings across variants. Secondary gained real material — defined edge, hairline elevation, hover that firms the border. Added `danger-quiet` for destructive actions that aren't the primary action. |
| **Tables** | Sticky headers, lighter zebra hover, true selection state (tinted fill + accent edge marker + indeterminate select-all), row actions that fade in on hover but stay visible on touch. |
| **Modal** | Header / scrolling body / pinned footer. New `xl` (600px) size. Split footer: `footerStart` for Cancel, `footer` for the primary action. |
| **Empty states** | Token-built illustration plate — concentric rings behind the section's own icon. No stock art, recolors with theme and accent. Optional onboarding `tips` and `secondaryAction`. |
| **Danger zone** | Workspace closure separated into its own outlined region with a tinted header. |

## Command palette

Rebuilt from nav-only into a real ⌘K surface:

- **7 quick actions** — new transaction, new account, transfer, budget, goal,
  bill, import.
- **Live record search** across transactions (server-side `search` filter,
  debounced), plus accounts, categories and bills matched against caches the
  app already holds, so they cost nothing.
- **Grouped results** with one flat keyboard ring, so ↑/↓/Enter behave
  identically whether the highlighted row is an action or a transaction.
- The shortcut hint reads ⌘K or Ctrl K depending on the actual platform.

Quick actions had to be made honest: navigating to a page and leaving the user
to find the button is a broken promise. `useOpenOnParam` opens the destination's
create surface from `?add=1` and strips the flag from history, so a refresh or
Back never reopens a dismissed form.

## Motion

Three rules govern every animation:

1. **Motion means meaning.** Something moves because it arrived, departed,
   changed state, or can be acted on. Nothing moves for decoration.
2. **Motion is fast.** 120–200ms. Slower is felt as lag by the tenth
   repetition, and this is daily-use software.
3. **Motion is compositor-only.** Transform and opacity exclusively — never
   width/top/margin — so everything holds 60fps at zero layout cost.

Modals rise 98% → 100%, dropdowns fade with a short slide hinged to their
trigger, the primary button grows 1.5% under the cursor, cards lift 2px at
150ms. All of it is opt-out via `prefers-reduced-motion`, including the cases
where the resting state itself has to be corrected.

## Verification

`npm run design:check` renders `design-check.html` — which loads the real
stylesheets in the real import order — across six theme/viewport combinations
and writes screenshots. No API or auth needed, so a CSS change can be reviewed
in seconds.

Status: typecheck clean, lint clean (1 pre-existing warning in `AuthContext`),
**268 tests passing across 59 files**, production build green.

## Known gap: account fields

The brief's account creation modal specifies Opening Balance, Icon, Color and
Description. None of these exist on the backend — `FinancialAccount` has
`name`, `account_type`, `currency`, `mask`, `institution`, `wallet`, and the
serializer exposes fewer still.

The modal was built to the specified layout and width using fields that
actually persist, with a live preview row standing in for the icon/color
identity. Shipping inputs that silently discard what a user types would be
worse than not shipping them.

To close the gap properly:

1. Add `color`, `icon`, `description` to `FinancialAccount` (`Wallet` already
   has `icon`/`color` — mirror those definitions) plus a migration.
2. Expose them on `FinancialAccountSerializer` and the create endpoint.
3. Opening balance is not a field but an *opening entry* — it should post a
   real double-entry transaction against the account at creation, not sit as a
   column, or the ledger stops reconciling.
4. Add the fields to the modal and the `AccountTypeIcon` badge.
