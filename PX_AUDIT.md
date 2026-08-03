# LedgerFlow — Product Experience Audit

A workflow, speed and trust audit of the existing product. The UI foundation was
treated as complete; nothing here changes the design language.

The method was deliberately evidence-first. Rather than walking the app and
collecting impressions, I searched the codebase for the *structural* causes of
friction — mutations without optimistic paths, destructive actions without
guards, keyboard handlers without typing guards. Impressions find symptoms;
structure finds causes, and causes are what recur.

---

## Findings, ranked by severity

### 1. Zero optimistic updates across 53 mutations — **critical**

Every mutation in the product was fire-and-wait. The one that matters most is
inline categorization: choosing a category from the dropdown in the ledger.

The old path was: send request → await server → invalidate **ten** query
families (`accounts`, `transactions`, `net-worth`, `cash-flow`,
`category-breakdown`, `budget-status`, `health-score`, `recommendations`,
`anomalies`, `net-worth-history`) → refetch → repaint.

The dropdown visibly snapped back to its previous value until the refetch
landed. On a page of forty transactions — which is the normal case for the
weekly triage session this feature exists to serve — that is forty visible
stalls. This single interaction did more to make the product feel slow than
anything else in it.

**Fixed.** `useUpdateTransaction` now snapshots every transaction page, patches
the row in place immediately, and reconciles afterwards. Rollback restores the
snapshot exactly on failure.

Two decisions inside that fix are worth stating, because they are the ones that
separate a correct optimistic update from a dangerous one:

- **Only the row's own list is patched optimistically.** Budgets, breakdowns
  and health scores are left to the refetch. Guessing at an aggregate is how a
  finance UI ends up displaying a total that never existed in the ledger.
- **Failure must be visible.** An optimistic update that rolls back silently is
  *worse* than the original slowness: the user's choice reverts for no stated
  reason and they conclude the app ignored them. The categorize handler now
  surfaces a toast on error. Adding the optimism without this would have been a
  net regression in trust.

### 2. Three destructive actions with no confirmation — **critical**

| Action | Before | Stakes |
|---|---|---|
| Remove workspace member | One unguarded click | Revokes a partner's access to shared finances |
| Delete category | One unguarded click | Orphans historical categorization |
| Archive goal | One unguarded click | Hides tracked progress |

Meanwhile *three other* destructive actions — delete budget, cancel bill, cancel
subscription — each hand-rolled their own inline two-step confirm, slightly
differently. So the codebase already knew the right pattern; it just hadn't been
made structural, which is exactly how guarantees decay.

**Fixed.** `ConfirmAction` consolidates the good pattern into one control,
applied to all three unguarded actions.

Design decisions:

- **Inline, not modal.** A dialog for every small delete is heavier than the
  action deserves, and it trains people to dismiss dialogs without reading —
  which is precisely what you cannot afford on the one action that *does*
  warrant a dialog. Closing a workspace correctly keeps its type-the-name gate.
- **Auto-disarms after 6 seconds.** An armed destructive button left sitting on
  screen after the user's attention moved on is a trap.
- **Focus moves to the confirm button**, and the state change is announced via
  `aria-live` — otherwise a screen-reader user has a button silently change
  meaning under them.

### 3. Bare-key shortcuts were absent, and adding them naively breaks typing

The product had `⌘K` only. The obvious implementation of bare-key shortcuts
(`n` for new transaction) introduces the classic bug: you can no longer type
"next month" into a memo field, because `n` opens a dialog.

**Fixed** with a typing guard that covers `input`, `textarea`, `select`,
`contenteditable`, and `role="textbox"` for custom widgets. Chords with a
modifier deliberately bypass the guard, because a modifier means the user is
consciously reaching past whatever they're typing in.

The matcher is a **pure function** in `shortcuts.ts`, separate from the
component. Keyboard handling is exactly the kind of logic that rots silently
when it's only reachable through a rendered tree; now every branch is directly
tested, including the guard.

Shortcuts added: `N`, `A`, `?`, and Linear-style `G then D/T/A/B/G/S`. A `?`
sheet makes them discoverable — shortcuts that exist only in a changelog may as
well not exist. One test asserts the documented sheet still matches the
implementation, because a shortcut list that lies is worse than no list.

### 4. Onboarding vanished exactly when it was needed most

The old checklist had three steps and disappeared the moment a user had one
account and one transaction — which is the precise moment they knew least about
budgets, goals and sharing. Those features were then never suggested again. The
product stopped teaching itself right when it should have started.

**Fixed.** Five steps, a progress indicator, and the checklist now persists
*alongside* the real dashboard rather than replacing it, so guidance and data
coexist. It's dismissible, because a checklist you can't remove stops being
guidance and becomes nagging — and the dismissal is remembered across sessions,
because a dismissal that resets on refresh is arguably worse than none.

Every step deep-links into its create surface. Which exposed the next problem.

### 5. Deep links promised things the pages didn't honour

Adding "Create budget" as a command-palette action and an onboarding CTA is
worthless if it drops the user on `/budgets` and leaves them hunting for a
button. Only `TransactionsPage` read an `?add=1` parameter; the others ignored
it.

**Fixed** with `useOpenOnParam`, applied to accounts, budgets, goals and bills.
It also strips the flag from history on mount — without that, a refresh or a
Back gesture silently reopens a form the user already dismissed.

### 6. Escape didn't close the mobile navigation drawer

Modals get Escape, focus containment and focus restoration free from the native
`<dialog>` element. The drawer is a plain element, so it got none of it. A
keyboard user could open the menu and have no exit except tabbing through every
link, and focus was left stranded on a hidden element after it closed.

**Fixed:** Escape closes it, focus returns to the trigger, and it now carries
`role="dialog"` / `aria-modal` so assistive tech announces it correctly.

### 7. Navigation had no prefetching

**Fixed.** Hovering or focusing a nav link warms that route's data. The user's
own hover latency (100–300ms) is dead time that can be spent on the network.

Capped at once per route per session, so sweeping the cursor down the sidebar
can't fan out into a burst of requests, and failures are swallowed — a
speculative fetch must never surface an error for a page the user never visited.

---

## What the audit found already in good shape

Worth recording, because knowing where *not* to spend effort is half the value:

- **Design token discipline is strong.** Only ~13 inline-style violations
  across the codebase, most of them legitimate (`padding: 0` resets, Google's
  brand colours in the OAuth logo). No systemic hardcoding.
- **All icon-only buttons are labelled.** A precise check (parsing each JSX tag
  rather than grepping lines) found zero unlabelled `lf-iconbtn` elements.
- **No positive `tabIndex` anywhere**, so tab order follows the DOM.
- **Route-level code splitting** was already in place.
- **Contextual actions were more complete than assumed** — transaction CSV
  export, for instance, already existed.

---

## Verification

Two automated checks were added, both because a real defect got through:

- **`npm run design:check`** renders the real stylesheets across six
  theme/viewport combinations and writes screenshots. No API or auth needed.
- **A CSS structure validator** catches unbalanced braces and orphaned
  declarations. This exists because a bad edit of mine left an orphaned
  declaration in `dashboard.css` that neither TypeScript nor the test suite
  could see — CSS is the one layer in this stack with no compiler behind it.

---

## Recommended next

1. **Backend account fields.** `color`, `icon` and `description` don't exist on
   `FinancialAccount`. Note that opening balance should post a real
   double-entry opening transaction, not become a column — otherwise the ledger
   stops reconciling.
2. **Extend optimism to bulk operations.** Bulk categorize/void still block.
   Same pattern applies.
3. **Roughly a dozen secondary empty states** still use the basic form without
   onboarding tips.
4. **Swipe gestures on mobile transaction rows** (categorize / void) — the one
   genuinely mobile-native interaction still missing.
