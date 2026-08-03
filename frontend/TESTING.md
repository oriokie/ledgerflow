# Frontend testing

Unit and component tests run on **Vitest** + **React Testing Library** (jsdom).

```bash
npm test            # run once
npm run test:watch  # watch mode
npm run test:coverage
npm run typecheck:test   # type-check the test files (separate from the build)
```

## Layout & conventions

- Tests live next to the code they cover: `Foo.tsx` → `Foo.test.tsx`.
- Config is in `vitest.config.ts` (kept separate from `vite.config.ts` so the
  production build never compiles test wiring). Test files are excluded from
  `tsconfig.app.json` and type-checked via `tsconfig.test.json`.
- `src/test/setup.ts` wires jest-dom matchers and auto-cleanup; matcher types
  are augmented in `src/test/vitest.d.ts`.
- Prefer asserting **behavior the user perceives** — roles, labels, visible
  text, `aria-*` — over implementation details.

## What's covered (243 tests)

Focused on the authentication experience and the core design-system primitives:

| Area | File | Notes |
|---|---|---|
| Money conversion/format | `lib/money.test.ts` | integer-minor-unit boundary, color semantics |
| **API client** | `api/client.test.ts` | JWT silent refresh + retry, tenant/auth header injection, error-envelope parsing, session-expiry, refresh coalescing |
| Query hooks | `hooks/useFinance.test.tsx` | tenant-gated queries (no cross-tenant fetch), mutation cache invalidation |
| Auth session funnel | `lib/AuthContext.test.tsx` | `completeLogin` — MFA challenge never persists tokens |
| Password reveal toggle | `ui/PasswordInput.test.tsx` | type switch, `aria-pressed`, error state |
| Button / Banner | `ui/primitives.test.tsx` | loading/disabled, roles, dismiss |
| Data table | `ui/Table.test.tsx` | columns, sort emit, `aria-sort`, row click |
| Auth shell | `components/auth/AuthLayout.test.tsx` | brand, footer, max-width |
| Social login | `components/auth/SocialAuthButtons.test.tsx` | redirect + graceful 400 degrade |
| Password strength | `components/auth/PasswordStrengthMeter.test.tsx` | threshold levels via a11y label |
| **⌘K command palette** | `components/shell/CommandPalette.test.ts` | search matching over nav + quick actions, keyword hits, empty/no-match |
| **Theme switching** | `lib/useTheme.test.ts` | light/dark/system persistence, `data-theme` sync, OS-preference resolve |
| Relative timestamps | `lib/money.test.ts` | `formatRelativeTime` — just-now/m/h/d + invalid-date guard (notification center) |
| **Dashboard metrics** | `pages/dashboard/metrics.test.ts` | period ranges (UTC-deterministic), greeting, percent change, savings rate, category ranking/shares |
| **Progressive disclosure** | `pages/dashboard/SpendingByCategory.test.tsx` | top-6 preview → show all → show less; empty state |
| **Dashboard composition** | `pages/DashboardPage.test.tsx` | full page renders with empty data — period control, primary action, guided empty states |
| **Account summaries** | `pages/accounts/summary.test.ts` | liability detection, per-currency asset/liability/net totals, grouping, statement in/out |
| **Account navigation** | `pages/accounts/AccountList.test.tsx` | asset/liability grouping, selected-row `aria-current`, click-to-select |
| **Accounts composition** | `pages/AccountsPage.test.tsx` | master-detail renders: balance summary, list, and selected account's detail |
| **Transaction filters** | `pages/transactions/filters.test.ts` | URL parse/serialize round-trip, API field/unit/date mapping, active-filter chips, cursor parsing |
| **Bulk messaging** | `pages/transactions/bulk.test.ts` | full/partial/total-failure result summaries and tone |
| **Transaction table** | `pages/transactions/TransactionTable.test.tsx` | row selection, indeterminate select-all, inline categorize, transfer has no picker, row-open |
| **Transactions composition** | `pages/TransactionsPage.test.tsx` | search/filters/list render; selecting a row reveals the bulk action bar |
| **Bulk + receipt hooks** | `hooks/useFinanceReceiptsBulk.test.tsx` | bulk categorize/void call the batch endpoint; receipt upload falls back to direct upload when presign is unavailable, else PUTs + confirms |
| **Budget math** | `pages/budgets/budgetMath.test.ts` | line state (under/near/over), totals, period pacing, over-pace + projection, risk sorting, alert partitioning |
| **Budget line editing** | `pages/budgets/BudgetLineRow.test.tsx` | progressbar value, inline limit edit saving in minor units, remove-with-confirm |
| **Budgets composition** | `pages/BudgetsPage.test.tsx` | summary + over-budget alert + category rows + progress bars render together |
| **Goal math** | `pages/goals/goalMath.test.ts` | milestone marks/amounts, next-milestone + amount-to-next, cross-goal totals, motivating sort order |
| **Goal contributions** | `pages/goals/GoalCard.test.tsx` | progress ring + next-milestone nudge, one-tap and custom contributions in minor units, celebration hides inputs |
| **Goals composition** | `pages/GoalsPage.test.tsx` | summary + a card per goal, achieved goal celebrated |
| **Recurring math** | `pages/recurring/recurringMath.test.ts` | monthly/annual normalization across frequencies + interval, spend vs income totals, cost sort, cadence/label |
| **Subscription actions** | `pages/recurring/SubscriptionRow.test.tsx` | normalized monthly cost render, pause, cancel-with-confirm |
| **Subscriptions composition** | `pages/RecurringPage.test.tsx` | spend summary + review nudge + a row per subscription, priciest first |
| **Bills math** | `pages/bills/billsMath.test.ts` | days-until + urgency label/tone, overdue/this-week/later buckets, inclusive totals |
| **Bills composition** | `pages/BillsPage.test.tsx` | summary + urgency-grouped bills with an overdue pill; pay + cancel-with-confirm each fire a toast |
| **Getting Started onboarding** | `pages/dashboard/GettingStarted.test.tsx` | new-user checklist guides account-first, then advances to the transaction step |
| **Dashboard onboarding gate** | `pages/DashboardPage.test.tsx` | empty workspace shows the checklist; an established one shows the full tiers |
| **Password reset** | `pages/PasswordReset.test.tsx` | request page stays neutral (no enumeration); reset page rejects a missing token and submits the URL token, then routes to login |
| **Plan usage** | `pages/billing/PlanUsage.test.tsx` | accounts/members shown against plan limits; hidden for a non-metered subscription |
| **AI insights gating** | `pages/InsightsPage.test.tsx` | plans without AI insights see an upgrade prompt linking to billing |
| **Dunning recovery** | `pages/BillingPage.test.tsx` | a past-due subscription prompts recovery and retries payment; a healthy one shows no prompt |
| **Workspace data & privacy** | `pages/settings/panels/WorkspacePanel.test.tsx` | export downloads the workspace JSON; closure is gated behind typing the exact workspace name |
| **Auth experience** | `components/auth/authExperience.test.tsx` | quote catalog is well-formed and wraps; the rotator advances quotes on a timer; logged-out page offers one clear way back in |
| **Appearance** | `lib/appearance.test.tsx` | accent catalog well-formed; attributes apply/clear (iris/comfortable = none); persisted values init at boot; unknown values fall back; the Preferences panel selects + persists accent, density, font family, and text size |
| **Cashflow statement** | `pages/analytics/CashflowLiquidity.test.tsx` | liquidity today + average net summary; monthly rows with signed nets and ending balances |
| **Cash runway** | `pages/analytics/CashflowLiquidity.test.tsx` | critical state names the projected run-out date and near-term bills; positive trend reassures; thin history says so honestly |
| **Currency & FX** | `pages/CurrencyFx.test.tsx` | catalog covers major + emerging currencies with correct minor units (JPY 0, KWD 3); net-worth card rolls up to base across currencies, flags incomplete rates, stays quiet for one currency |
| **Analytics math** | `pages/analytics/analyticsMath.test.ts` | trailing-month range, deltas, savings rate, month-over-month comparison, trend totals, breakdown shares |
| **Category drill-down** | `pages/analytics/CategoryBreakdown.test.tsx` | ranked shares render, click drills in, selected + empty states |
| **Analytics composition** | `pages/AnalyticsPage.test.tsx` | comparison + breakdown render, clicking a category opens its trend |
| **Insights copy** | `pages/insights/insightsCopy.test.ts` | band tones, health strength/watch, greeting variants, per-recommendation CTA + basis, plain anomaly headlines, confidence-to-words |
| **Guidance card** | `pages/insights/GuidanceCard.test.tsx` | actionable next step routes to the right screen; good-news guidance carries no action |
| **Insights composition** | `pages/InsightsPage.test.tsx` | conversational check-in + guidance + human health + worth-a-look + categorization |
| **Settings nav** | `pages/settings/nav.test.ts` | grouped sections, unique flat slug list |
| **Settings components** | `pages/settings/components.test.tsx` | labelled row association, advanced disclosure stays collapsed until opened, active grouped nav links |
| **Settings composition** | `pages/SettingsPage.test.tsx` | grouped nav + routed panels (profile default, workspace from its path) |
| **Tab bar config** | `components/shell/tabBarConfig.test.ts` | tab destinations are a subset of the primary nav (parity, not a fork), five ordered items resolve |
| **Mobile tab bar** | `components/shell/MobileTabBar.test.tsx` | five shortcut links with correct hrefs, aria-current marks the active destination |
| **Toast system** | `ui/Toast.test.tsx` | polite live-region announcement, auto-dismiss, three-toast cap, safe no-op without a provider |
| **Toast wiring** | `pages/BillsPage.test.tsx` | paying a bill fires a named confirmation toast |

## Not covered (yet)

- **Passkey ceremony** (`PasskeyButton`, `PasskeyManager`): WebAuthn needs
  `navigator.credentials`, which jsdom doesn't implement — these belong in a
  browser-based e2e layer (Playwright), not unit tests.
- The 18 feature pages: this suite deliberately targets the shared primitives
  and auth flows first, where a regression would ripple widest.

## Visual smoke check (Playwright)

`frontend/app/ui-check.mjs` drives the real stack (Django API + built frontend served via `vite preview`) with the system Chromium and walks the core journeys end-to-end: login (split panel + rotating quote), register → workspace → Getting-Started dashboard, account creation, `?add=1` transaction form with seeded categories, insights check-in, settings Data & privacy, the logout → `/logged-out` farewell, and mobile (390px) login + bottom tab bar — 22 assertions, one screenshot per screen in `/tmp/ui-shots` — now also covering the appearance journey (accent applies instantly, compact density applies, both persist across reload), dark mode (system preference resolves to `data-theme="dark"` on login and dashboard), a tablet viewport (820px), and live quote rotation (the login quote changes after one ~8s interval).

Run: start Postgres/Redis/Django (`runserver 8000`) and `npx vite preview --port 4173`, then `node ui-check.mjs` (uses `executablePath: /opt/google/chrome/chrome`; swap for `npx playwright install chromium` where the CDN is reachable).
