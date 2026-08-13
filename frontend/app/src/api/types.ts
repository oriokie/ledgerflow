// Mirrors the DRF serializer output exactly — field names, nullability, and
// the minor-unit (integer cents) money convention used throughout the API.
// Amounts are always integers in the currency's smallest unit; never floats.

export interface User {
  /** True when this account operates the platform rather than using it.
   * Such accounts cannot own or join a customer workspace — see
   * apps/platform_admin/separation.py for why. */
  is_platform_staff?: boolean;
  id: string;
  email: string;
  first_name?: string;
  last_name?: string;
  mfa_enabled?: boolean;
  /** Whether the sidebar offers receipt scanning. Opt-in, per user, and it
   * follows them across workspaces — see UserProfile.show_receipt_scanner. */
  show_receipt_scanner?: boolean;
}

export interface AuthTokens {
  access: string;
  refresh: string;
  user: User;
}

export interface WebAuthnCredential {
  id: string;
  device_name: string;
  transports: string[] | null;
  backup_state: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface MfaRequired {
  mfa_required: true;
  mfa_token: string;
  methods: string[];
}

export interface Tenant {
  id: string;
  name: string;
  type: string;
  base_currency: string;
  /**
   * When an owner actually chose the base currency, as against inheriting the
   * "USD" default. Null means nobody has been asked yet — which is what lets
   * first-run setup ask exactly once instead of every time.
   */
  base_currency_chosen_at: string | null;
  /** ISO-3166 alpha-2. Blank when the workspace has not stated a country. */
  country?: string;
  /** Whether a manual posting that would overdraw an asset account is refused. */
  block_overdrafts: boolean;
  default_locale: string;
  default_timezone: string;
}

export interface Workspace {
  id: string;
  tenant: Tenant;
  role: string;
  created_at: string;
}

export interface FinancialAccount {
  id: string;
  name: string;
  account_type: string;
  currency: string;
  balance_minor: number;
  mask?: string;
  color?: string;
  icon?: string;
  notes?: string;
  /** Collapsed out of the default UI, but still counted in every total. */
  is_hidden?: boolean;
  /** Closed. Keeps all its history; leaves pickers and net worth. */
  is_archived?: boolean;
  include_in_net_worth?: boolean;
  include_in_budgets?: boolean;
}

/** Fields a client may change after creation. Currency and account_type are
 * deliberately absent — both are baked into every posted ledger line. */
export interface AccountUpdate {
  name?: string;
  mask?: string;
  color?: string;
  icon?: string;
  notes?: string;
  is_hidden?: boolean;
  include_in_net_worth?: boolean;
  include_in_budgets?: boolean;
}

export interface Category {
  id: string;
  name: string;
  kind: "income" | "expense" | "transfer";
  path: string;
  depth: number;
  parent_id: string | null;
}

export interface Payee {
  id: string;
  name: string;
}

export interface TransactionMetadata {
  mpesa_receipt?: string;
}

export interface Transaction {
  id: string;
  financial_account_id: string;
  amount_minor: number;
  currency: string;
  occurred_at: string;
  status: string;
  source: string;
  category_id: string | null;
  payee_id: string | null;
  counter_account_id: string | null;
  transfer_group: string | null;
  split_group: string | null;
  reconciled_at: string | null;
  memo: string;
  metadata?: TransactionMetadata;
}

export interface Paginated<T> {
  next: string | null;
  previous: string | null;
  results: T[];
}

/** Book value from the ledger, plus the market-value overlay.
 *
 * `assets_minor` / `net_minor` carry investments at **cost** — that's what keeps
 * the ledger free of unposted gains. `market_*` adds the unrealised gain on top.
 * The two are deliberately separate: one is what the books say, the other what
 * the market says. */
export interface NetWorthByCurrency {
  currency: string;
  assets_minor: number;
  liabilities_minor: number;
  net_minor: number;
  /** Market value less cost, across priced holdings. 0 when nothing is held. */
  unrealized_gain_minor?: number;
  market_assets_minor?: number;
  market_net_minor?: number;
}

export interface CashFlowByCurrency {
  currency: string;
  income_minor: number;
  expense_minor: number;
  net_minor: number;
}

export interface CategoryBreakdownRow {
  category_id: string;
  category_name: string;
  amount_minor: number;
}

export interface NetWorthHistoryPoint {
  as_of: string;
  assets_minor: number;
  liabilities_minor: number;
  net_minor: number;
}

export interface CategoryTrendPoint {
  period_start: string;
  amount_minor: number;
}
export interface SpendingTrendPoint {
  period_start: string;
  income_minor: number;
  expense_minor: number;
  net_minor: number;
}

export interface ForecastPoint {
  period_start: string;
  projected_expense_minor: number;
  low_minor: number;
  high_minor: number;
}

export interface Forecast {
  points: ForecastPoint[];
  provider: string;
  version: string;
}

export interface HealthScoreComponent {
  name: string;
  /** Null when there was no basis to measure it. `detail` says what's missing. */
  score: number | null;
  weight: number;
  detail: string;
}

export interface HealthScore {
  /**
   * Null when too little of the picture is measurable to state one number.
   * Render the absence — a zero here would be a claim nobody made.
   */
  score: number | null;
  band: string;
  /** Share of the score's total weight that was measurable, 0..1. */
  coverage: number;
  components: HealthScoreComponent[];
  provider: string;
  version: string;
}

export interface RecommendationAction {
  action?: string;
  [key: string]: unknown;
}
export interface Recommendation {
  kind: string;
  title: string;
  body: string;
  severity: string;
  action?: RecommendationAction | null;
}

export interface Anomaly {
  transaction_id: string | null;
  kind: string;
  severity: number;
  explanation: string;
}

export interface Budget {
  id: string;
  name: string;
  currency: string;
  starts_on: string;
  period: string;
}

export interface BudgetLineStatus {
  line_id: string;
  category_id: string;
  category_name: string;
  limit_minor: number;
  carried_minor: number;
  effective_limit_minor: number;
  actual_minor: number;
  remaining_minor: number;
  percent_used: number;
  over_budget: boolean;
}

export interface BudgetStatus {
  budget_id: string;
  as_of: string;
  period_start: string;
  period_end: string;
  lines: BudgetLineStatus[];
}

export type GoalKind =
  | "emergency_fund"
  | "vacation"
  | "house_deposit"
  | "education"
  | "retirement"
  | "vehicle"
  | "debt_payoff"
  | "custom";

/** 1 = Critical … 5 = Someday. Lower sorts first, so ascending order is also
 * funding order. */
export type GoalPriority = 1 | 2 | 3 | 4 | 5;

export interface SavingsGoal {
  id: string;
  name: string;
  kind: GoalKind;
  currency: string;
  target_minor: number;
  target_date: string | null;
  priority: GoalPriority;
  tracking: "manual" | "account_balance";
  linked_account_id: string | null;
  status: "active" | "paused" | "achieved" | "archived";
  notes: string;
  saved_minor: number;
  remaining_minor: number;
  percent: number;
  is_met: boolean;
  required_monthly_minor: number | null;
  planned_monthly_minor: number | null;
  auto_contribute_enabled: boolean;
  auto_contribute_minor: number | null;
  auto_contribute_day: number | null;
}

export interface GoalProjectionPoint {
  month: string;
  projected_minor: number;
  target_minor: number;
}

export interface GoalForecast {
  goal_id: string;
  currency: string;
  saved_minor: number;
  target_minor: number;
  remaining_minor: number;
  percent: number;
  /** What you must contribute monthly to hit the target date. */
  required_monthly_minor: number | null;
  /** What the user said they'd contribute. */
  planned_monthly_minor: number | null;
  /** What they actually have been contributing. */
  observed_monthly_minor: number | null;
  monthly_shortfall_minor: number | null;
  projected_completion: string | null;
  target_date: string | null;
  on_track: boolean | null;
  /**
   * Calibrated heuristic, 0–1. **Null when there isn't enough history to
   * estimate one** — render the absence, never substitute a zero.
   */
  success_probability: number | null;
  /** Share of recent months that received a contribution, 0–1. */
  consistency: number;
  projection?: GoalProjectionPoint[];
  history?: { month: string; amount_minor: number }[];
}

export interface GoalRecommendation {
  kind: GoalKind;
  title: string;
  rationale: string;
  suggested_target_minor: number;
  suggested_monthly_minor: number | null;
  currency: string;
  priority: GoalPriority;
}

export interface GoalContribution {
  id: string;
  amount_minor: number;
  occurred_on: string;
  memo: string;
}

export interface Bill {
  id: string;
  name: string;
  amount_minor: number;
  currency: string;
  due_on: string;
  status: "upcoming" | "paid" | "overdue" | "cancelled";
  payee_id: string | null;
  category_id: string | null;
  recurrence_frequency: string;
  autopay_account_id: string | null;
  paid_at: string | null;
  notes: string;
  days_until_due?: number;
}

export interface Notification {
  id: string;
  type: string;
  severity: "info" | "warning" | "critical";
  title: string;
  body: string;
  subject_type: string;
  subject_id: string | null;
  data: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

// ---------------------------------------------------------------- wallets
export interface WalletBalance {
  currency: string;
  balance_minor: number;
}

export interface Wallet {
  id: string;
  name: string;
  icon: string;
  color: string;
  is_default: boolean;
  balances: WalletBalance[];
}

// ---------------------------------------------------------------- statement
export interface StatementLine extends Transaction {
  running_balance_minor: number;
}

export interface Statement {
  opening_balance_minor: number;
  lines: StatementLine[];
}

// ---------------------------------------------------------------- recurring
export interface RecurringTransaction {
  id: string;
  txn_type: "income" | "expense" | "transfer";
  amount_minor: number;
  currency: string;
  frequency: string;
  interval: number;
  next_run_on: string;
  starts_on: string;
  ends_on: string | null;
  occurrences_created: number;
  is_active: boolean;
  memo: string;
  category_id: string | null;
  financial_account_id: string | null;
  counter_account_id?: string | null;
  payee_id: string | null;
}

// ---------------------------------------------------------------- tags
export interface Tag {
  id: string;
  name: string;
  color: string;
}

// ---------------------------------------------------------------- suggestions
export interface CategorizationSuggestion {
  id: string;
  transaction_id: string;
  suggested_category_id: string;
  confidence: number;
  status: string;
  provider: string;
  provider_kind: string;
  provider_version: string;
  rationale: string;
  decided_at: string | null;
  created_at: string;
}

// ---------------------------------------------------------------- automation
export interface AutomationClause {
  field: string;
  op: string;
  value: string | number;
}

export interface AutomationRule {
  id: string;
  name: string;
  is_active: boolean;
  priority: number;
  conditions: { all?: AutomationClause[]; any?: AutomationClause[] };
  actions: { type: string; [key: string]: unknown }[];
  stop_processing: boolean;
  match_count: number;
  last_matched_at: string | null;
}

// ---------------------------------------------------------------- members
export interface Member {
  id: string;
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  created_at: string;
}

export interface Invitation {
  id: string;
  email: string;
  role: string;
  status: string;
  workspace_name: string;
  invited_by_email: string | null;
  created_at?: string;
  expires_at?: string;
}

/** What an invitee sees before accepting — enough to inform the decision,
 * nothing about the workspace's data. */
export interface InvitationPreview {
  workspace_name: string;
  role: string;
  invited_by_display: string | null;
}

// ---------------------------------------------------------------- ledger
export interface LedgerAccount {
  id: string;
  name: string;
  kind: string;
  currency: string;
  is_system: boolean;
  balance_minor: number;
  created_at: string;
}

// ---------------------------------------------------------------- mfa
export interface TotpEnrollment {
  secret: string;
  provisioning_uri: string;
}

// ---------------------------------------------------------------- billing
export interface Plan {
  id: string;
  tier: "free" | "plus" | "family" | "business";
  name: string;
  description: string;
  price_minor: number;
  currency: string;
  interval: "monthly" | "yearly";
  max_members: number;
  max_accounts: number;
  ai_insights: boolean;
  features: string[];
  /** Tier defaults ∪ this row's overrides, labelled server-side — the one list
   * every pricing surface renders, so they cannot disagree about what a plan
   * includes. */
  resolved_features: { key: string; label: string }[];
}

export interface Subscription {
  id: string;
  plan: Plan;
  status: "trialing" | "active" | "past_due" | "canceled" | "incomplete";
  is_current: boolean;
  current_period_start: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  canceled_at: string | null;
  trial_end: string | null;
  provider: string;
}

export interface PaymentMethod {
  id: string;
  kind: "card" | "mpesa";
  is_default: boolean;
  brand: string;
  last4: string;
  exp_month: number | null;
  exp_year: number | null;
  phone_masked: string;
  provider: string;
  created_at: string;
}

export interface Payment {
  id: string;
  amount_minor: number;
  currency: string;
  status: "pending" | "succeeded" | "failed" | "refunded";
  provider: string;
  description: string;
  failure_reason: string;
  created_at: string;
}

export interface CashflowStatementRow {
  period_start: string;
  inflow_minor: number;
  outflow_minor: number;
  net_minor: number;
  ending_balance_minor: number;
}

export interface CashflowStatementData {
  currency: string | null;
  liquid_balance_minor: number;
  rows: CashflowStatementRow[];
}

export interface CashRunway {
  status: "healthy" | "watch" | "warning" | "critical" | "insufficient_data";
  reason?: string;
  currency?: string;
  liquid_balance_minor?: number;
  avg_monthly_net_minor?: number;
  months_analyzed?: number;
  upcoming_bills_minor?: number;
  upcoming_bills_count?: number;
  months_of_runway?: number | null;
  projected_runout_date?: string | null;
}

export interface NetWorthBase {
  base_currency: string;
  total_minor: number;
  /** False when a currency lacked an FX rate — show "≈" or omit rather than mislead. */
  converted: boolean;
  currency_count: number;
}


/** Where a projected movement came from. Drives colour and icon in the calendar. */
export type CashflowEventSource =
  | "salary"
  | "income"
  | "bill"
  | "subscription"
  | "recurring_expense"
  | "transfer_in"
  | "transfer_out";

export interface CashflowEvent {
  occurs_on: string;
  /** Signed: positive is money in. Colour derives from the sign, icon from
   * `source`, so neither has to be re-derived client-side. */
  amount_minor: number;
  description: string;
  source: CashflowEventSource;
  currency: string;
  account_id: string | null;
  account_name: string;
  category_name: string;
  is_overdue: boolean;
  bill_id: string | null;
  recurring_id: string | null;
}

export interface CashflowCalendarDay {
  day: string;
  opening_minor: number;
  closing_minor: number;
  inflow_minor: number;
  outflow_minor: number;
  net_minor: number;
  /** Projected to close below zero — a predicted overdraft. */
  is_negative: boolean;
  /** Where the balance lands once ordinary unscheduled spending is included.
   * Null — never equal to `closing_minor` — when there is too little history
   * to measure it. Always <= `closing_minor`: everyday spending only takes
   * money out, so the scheduled line is the optimistic edge of the range. */
  expected_minor: number | null;
  expected_low_minor: number | null;
  expected_high_minor: number | null;
  events: CashflowEvent[];
}

/** How the everyday-spending band was measured.
 *
 * Mean and standard deviation, not median and quartiles: the expected total
 * over k days is `k × mean`, and on bursty spending the median day is often
 * zero — which would put the "likely" line straight back on top of the
 * scheduled one. */
export interface EverydaySpending {
  mean_minor: number;
  stdev_minor: number;
  /** The more intuitive "typical day". Description only — never projection. */
  median_minor: number;
  observed_days: number;
  active_days: number;
}

export interface CashflowCalendar {
  currency: string;
  start: string;
  end: string;
  opening_balance_minor: number;
  closing_balance_minor: number;
  /** The trough. This, not the closing balance, says whether the user survives
   * the window. */
  lowest_balance_minor: number;
  lowest_balance_on: string | null;
  first_negative_on: string | null;
  negative_day_count: number;
  /** The projected trough floored at zero: what could be spent today with
   * every scheduled bill still covered. Money spent today lowers every later
   * day by the same amount, so the trough — not today's balance — binds. */
  safe_to_spend_minor: number;
  /** "everyday" when normal unscheduled spending is already accounted for;
   * "scheduled" when only bills and templates could be projected. */
  safe_to_spend_basis: "everyday" | "scheduled";
  /** Basis for the band on every day. Null when there was too little history. */
  everyday: EverydaySpending | null;
  days: CashflowCalendarDay[];
}


/** A validated ledger filter derived from a natural-language question.
 *
 * Never an answer. The model chooses what to look at; the figures are computed
 * by the same selectors as every other view, so there is nothing to take on
 * trust. See `apps/intelligence/ask.py`. */
export interface AskResult {
  query: {
    start?: string;
    end?: string;
    category?: string;
    search?: string;
    min_amount_minor?: number;
    max_amount_minor?: number;
    direction?: "in" | "out";
  } | null;
  explanation: string;
  from_rules?: boolean;
}

/** A dated fact reconstructed from the ledger — never a reward, never a tier.
 * See `apps/intelligence/milestones.py` for why the distinction is load-bearing. */
export interface Milestone {
  key: string;
  title: string;
  detail: string;
  achieved_on: string;
  amount_minor: number | null;
  currency: string;
}


// --------------------------------------------------------------- AI coach
export type InsightKind =
  | "spending_anomaly"
  | "overspending"
  | "budget_recommendation"
  | "savings_opportunity"
  | "duplicate_transaction"
  | "large_purchase"
  | "merchant_change"
  | "salary_change"
  | "cashflow_risk"
  | "subscription_review"
  | "goal_recommendation"
  | "debt_recommendation"
  | "health_improvement";

/** Ordered by urgency. `critical` is reserved for things with a deadline. */
export type InsightSeverity = "critical" | "warning" | "opportunity" | "info";

export type InsightStatus = "new" | "seen" | "bookmarked" | "dismissed" | "acted";

export interface Insight {
  id: string;
  kind: InsightKind;
  severity: InsightSeverity;
  status: InsightStatus;
  title: string;
  body: string;
  /** Why this insight exists, in the user's own figures. Never empty — an
   * insight you can't check is one you can't trust. */
  rationale: string;
  /** The numbers the claim was computed from. */
  evidence: Record<string, unknown>;
  /** Machine-actionable follow-up mapping to a real engine capability. */
  action: Record<string, unknown>;
  /** 0–100. See the scoring module for the breakdown. */
  priority_score: number;
  period_start: string | null;
  period_end: string | null;
  expires_on: string | null;
  provider: string;
  provider_kind: string;
  provider_version: string;
  related_transaction_id: string | null;
  related_category_id: string | null;
  related_account_id: string | null;
  created_at: string;
}

export type BriefingPeriod = "daily" | "weekly" | "monthly";

export interface Briefing {
  id: string;
  period: BriefingPeriod;
  period_start: string;
  period_end: string;
  headline: string;
  summary: string;
  /** The figures the prose was written from, so it can be checked. */
  metrics: Record<string, unknown>;
  provider: string;
  insights: Insight[];
}


export interface LLMPreset {
  id: string;
  label: string;
  default_model: string;
  requires_key: boolean;
  /** Usable without payment details. */
  free_tier: boolean;
  /** Runs on the operator's own machine, so nothing leaves it. */
  is_local: boolean;
  docs_url: string;
}

export interface LLMSettings {
  enabled: boolean;
  /** Whether THIS workspace has opted in to AI-touched insights and
   * narration — the one field on this endpoint a workspace admin actually
   * controls. Everything else here is deployment-level and read-only. */
  tenant_ai_enabled: boolean;
  /** Whether a call can actually be made right now. */
  available: boolean;
  /** Why not, when `available` is false. */
  reason: string;
  provider: string;
  provider_label: string;
  model: string;
  base_url: string;
  /** Presence only — the key itself never crosses the API boundary. */
  api_key_present: boolean;
  is_local: boolean;
  share_financial_context: boolean;
  insight_provider: string;
  narrative_provider: string;
  presets: LLMPreset[];
}


// --------------------------------------------------------- investments
export type AssetClass =
  | "stock"
  | "etf"
  | "mutual_fund"
  | "bond"
  | "crypto"
  | "cash_equivalent"
  | "real_estate"
  | "commodity"
  | "other";

export interface Security {
  id: string;
  symbol: string;
  name: string;
  asset_class: AssetClass;
  sector: string;
  currency: string;
  exchange: string;
}

export interface HoldingValuation {
  holding_id: string;
  account_id: string;
  account_name: string;
  security_id: string;
  symbol: string;
  security_name: string;
  asset_class: AssetClass;
  sector: string;
  currency: string;
  /** Decimal string — crypto and some funds trade in fractions. */
  quantity: string;
  /** What you paid. From the ledger, always exact. */
  cost_basis_minor: number;
  /** Null when the security has never been priced — never zero, which would
   * read as a wipeout. */
  price_minor: number | null;
  /** ISO date the price was taken. Quotes are entered by hand, so this is how
   * fresh the valuation is. Null alongside `price_minor`. */
  priced_as_of: string | null;
  market_value_minor: number | null;
  unrealized_gain_minor: number | null;
  unrealized_gain_pct: number | null;
  is_priced: boolean;
}

export interface AllocationSlice {
  label: string;
  market_value_minor: number;
  percent: number;
}

export interface PortfolioSummary {
  currency: string;
  cost_basis_minor: number;
  market_value_minor: number;
  /** Paper gains — reported, never posted to the ledger. */
  unrealized_gain_minor: number;
  unrealized_gain_pct: number;
  /** Booked on disposal. Real income. */
  realized_gain_minor: number;
  dividend_income_minor: number;
  total_return_minor: number;
  holding_count: number;
  /** Positions with no quote, so the UI can say the total is partial. */
  unpriced_count: number;
  /** ISO date of the *oldest* quote behind the total — a sum is only as
   * current as its stalest input. Null when nothing is priced. */
  priced_as_of: string | null;
  /** Holdings priced, but not priced today. */
  stale_count: number;
  asset_allocation: AllocationSlice[];
  sector_allocation: AllocationSlice[];
  account_allocation: AllocationSlice[];
}

export interface PortfolioHistoryPoint {
  as_of: string;
  market_value_minor: number;
  cost_basis_minor: number;
  unrealized_gain_minor: number;
}


// --------------------------------------------------------------- debt
export type DebtKind =
  | "credit_card"
  | "mortgage"
  | "personal_loan"
  | "student_loan"
  | "vehicle loan"
  | "bnpl"
  | "other";

export type PayoffStrategy = "avalanche" | "snowball" | "custom";

export interface DebtView {
  account_id: string;
  name: string;
  currency: string;
  debt_kind: DebtKind;
  balance_minor: number;
  apr: number;
  minimum_payment_minor: number;
  payment_day: number | null;
  monthly_interest_minor: number;
  /** False means the balance grows even when payments are made on time — the
   * most serious thing that can be true of a debt. */
  minimum_covers_interest: boolean;
  original_principal_minor: number | null;
  /** Null when the original principal isn't known: a balance alone can't say
   * how far through you are. */
  percent_repaid: number | null;
  include_in_payoff: boolean;
  has_terms: boolean;
  compounding?: Compounding;
  offset_minor?: number;
  /** Countdown so the UI can warn before a promotional rate expires. */
  promo_days_remaining?: number | null;
  promo_ends_on?: string | null;
  next_rate_change_on?: string | null;
  next_rate_apr?: number | null;
  rate_schedule?: RatePeriod[];
  fees?: { monthly_minor: number; annual_minor: number; origination_minor: number } | null;
}

export interface DebtAlert {
  severity: "critical" | "warning" | "info";
  title: string;
  body: string;
  account_id: string | null;
}

export interface DebtRecommendation {
  strategy: PayoffStrategy;
  title: string;
  rationale: string;
  interest_saved_minor: number;
  months_saved: number | null;
  alternative: PayoffStrategy;
}

export interface DebtSummary {
  currency: string;
  total_balance_minor: number;
  total_minimum_minor: number;
  total_monthly_interest_minor: number;
  /** Monthly interest is easy to shrug off; the annual figure much less so. */
  annual_interest_minor: number;
  debt_count: number;
  /** Weighted by balance, so a small expensive card can't out-shout a large
   * cheap loan. */
  weighted_apr: number;
  highest_apr_name: string | null;
  highest_apr: number | null;
  unplannable_count: number;
  growing_count: number;
  /** Debts with terms recorded — the only ones `weighted_apr` and the interest
   * figures come from. Zero means those figures are zero because nothing was
   * entered, which is not the same claim as "this debt costs nothing". */
  priced_count: number;
  alerts: DebtAlert[];
  recommendation: DebtRecommendation | null;
}

export interface PayoffPerDebt {
  debt_id: string;
  name: string;
  starting_balance_minor: number;
  interest_paid_minor: number;
  total_paid_minor: number;
  months_to_clear: number | null;
  cleared_on: string | null;
  never_clears: boolean;
}

export interface PayoffCalendarMonth {
  as_of: string;
  total_paid_minor: number;
  total_interest_minor: number;
  remaining_balance_minor: number;
  payments: {
    debt_id: string;
    name: string;
    payment_minor: number;
    interest_minor: number;
    principal_minor: number;
    balance_after_minor: number;
    clears_here: boolean;
  }[];
}

export interface StrategyComparison {
  strategy: PayoffStrategy;
  months_to_debt_free: number | null;
  debt_free_on: string | null;
  total_interest_minor: number;
  interest_saved_minor: number;
  months_saved: number | null;
  first_cleared_name: string | null;
  first_cleared_months: number | null;
}

export interface PayoffPlan {
  strategy: PayoffStrategy;
  currency: string;
  monthly_budget_minor: number;
  extra_monthly_minor: number;
  months_to_debt_free: number | null;
  debt_free_on: string | null;
  total_interest_minor: number;
  total_paid_minor: number;
  is_complete: boolean;
  /** Non-empty means the plan can't finish: some payment doesn't cover its
   * interest. */
  stuck_debt_ids: string[];
  per_debt: PayoffPerDebt[];
  calendar: PayoffCalendarMonth[];
  comparison: StrategyComparison[];
}


// ------------------------------------------------- debt intelligence
export type Compounding =
  | "monthly" | "daily" | "weekly" | "quarterly" | "annual" | "continuous";

export interface RatePeriod {
  effective_from: string;
  apr: number;
}

export interface DebtStressComponent {
  key: string;
  label: string;
  /** 0–100, higher is better — matching the financial health score. */
  score: number;
  weight: number;
  value: number | null;
  detail: string;
}

export interface DebtStress {
  score: number;
  band: "excellent" | "good" | "moderate" | "high" | "critical";
  /** Share of the weighting that had data behind it. */
  coverage: number;
  /** True when too little was measurable for the headline to mean much. */
  is_provisional: boolean;
  missed_payment_penalty: number;
  weakest: string | null;
  components: DebtStressComponent[];
  method: string;
  currency: string;
}

export interface BorrowingCost {
  currency: string;
  annual_interest_minor: number;
  annual_fees_minor: number;
  annual_total_minor: number;
  monthly_interest_minor: number;
  monthly_fees_minor: number;
  /** Share of the annual cost that is fees rather than interest. */
  fee_share: number;
  /** Debts these figures could be computed from, against the number in scope. */
  priced_count: number;
  debt_count: number;
}

export interface RefinanceResult {
  current_total_cost_minor: number;
  new_total_cost_minor: number;
  lifetime_saving_minor: number;
  current_months: number | null;
  new_months: number | null;
  months_saved: number | null;
  current_monthly_minor: number;
  new_monthly_minor: number;
  /** A saving arriving after the user expects to have repaid never arrives. */
  breakeven_month: number | null;
  closing_costs_minor: number;
  is_worthwhile: boolean;
}

export interface ConsolidationResult {
  debt_count: number;
  combined_balance_minor: number;
  current_total_cost_minor: number;
  new_total_cost_minor: number;
  lifetime_saving_minor: number;
  current_months: number | null;
  new_months: number | null;
  months_saved: number | null;
  current_monthly_minor: number;
  new_monthly_minor: number;
  current_weighted_apr: number;
  new_apr: number;
  /** Judged on lifetime cost, never the monthly payment. */
  is_worthwhile: boolean;
}

export interface ScenarioResult {
  label: string;
  strategy: PayoffStrategy;
  months_to_debt_free: number | null;
  debt_free_on: string | null;
  total_interest_minor: number;
  total_fees_minor: number;
  total_paid_minor: number;
  interest_saved_minor: number;
  months_saved: number | null;
  is_complete: boolean;
}


export interface DebtAnalyticsPoint {
  as_of: string;
  interest_minor: number;
  fees_minor: number;
  principal_minor: number;
  cumulative_interest_minor: number;
  cumulative_principal_minor: number;
  remaining_balance_minor: number;
}

export interface DebtAnalytics {
  currency: string;
  strategy: PayoffStrategy;
  opening_balance_minor: number;
  series: DebtAnalyticsPoint[];
  composition: { kind: DebtKind; balance_minor: number; percent: number }[];
  /** The first month's principal — the honest current rate. Averaging over the
   * whole plan would flatter it, since the rollover accelerates later. */
  monthly_velocity_minor: number;
  total_interest_minor: number;
  total_fees_minor: number;
  months_to_debt_free: number | null;
  debt_free_on: string | null;
}


// ------------------------------------------------- reporting platform
export type ReportChart = "area" | "line" | "bar" | "composed" | "donut" | "table" | "score";
export type ReportGroup = "position" | "flow" | "spending" | "compare";

export interface ReportMeta {
  slug: string;
  title: string;
  /** How the client should draw it. Rendering is driven by this rather than by
   * a per-report component, so adding a report is a backend change alone. */
  chart: ReportChart;
  group: ReportGroup;
}

export interface ReportResult {
  slug: string;
  title: string;
  currency: string;
  start: string;
  end: string;
  /** Headline figures. */
  totals: Record<string, number | string | null>;
  /** Anything plotted over time. */
  series: Record<string, number | string | null>[];
  /** Anything tabular. */
  rows: Record<string, number | string | null>[];
  /** Report-specific context — comparison windows, thresholds, caveats. */
  meta: Record<string, unknown>;
}

export type ReportPeriod =
  | "last_30_days"
  | "last_90_days"
  | "last_12_months"
  | "this_month"
  | "last_month"
  | "this_year"
  | "last_year"
  | "all_time"
  | "custom";

export interface ReportFilters {
  period?: ReportPeriod;
  start?: string;
  end?: string;
  account_ids?: string[];
  category_ids?: string[];
  currency?: string;
  compare_previous?: boolean;
}


// ------------------------------------------------- automation engine
export type AutomationKind =
  | "category" | "transfer" | "duplicate" | "refund" | "recurring" | "split" | "income";

export type AutomationStatus = "pending" | "approved" | "rejected" | "auto_applied";

export interface AutomationSuggestion {
  id: string;
  kind: AutomationKind;
  status: AutomationStatus;
  /** 0–1, from the detector. Never rounded up for presentation. */
  confidence: number;
  /** Why, in the user's own figures. Never empty — a suggestion nobody can
   * check is one nobody should act on. */
  reason: string;
  payload: Record<string, unknown>;
  merchant_key: string;
  primary_transaction_id: string | null;
  transaction_ids: string[];
  /** Nested evidence so a duplicate can be judged without opening the ledger. */
  transactions?: {
    id: string;
    occurred_at: string;
    amount_minor: number;
    currency: string;
    payee: string;
    account_name: string;
  }[];
  created_at: string;
  decided_at: string | null;
}

export interface AutomationQueue {
  pending: number;
  by_kind: Record<string, number>;
  auto_applied: number;
  /** Null until something has been decided — an accuracy figure from no data
   * is not an accuracy figure. */
  approval_rate: number | null;
  suggestions: AutomationSuggestion[];
}


// ------------------------------------------------------------- receipts
export type ReceiptStatus =
  | "pending_upload" | "uploaded" | "processing" | "parsed" | "unreadable"
  | "failed" | "linked" | "discarded";

export interface Receipt {
  id: string;
  status: ReceiptStatus;
  content_type: string;
  byte_size: number;
  raw_text: string;
  parsed_fields: { merchant: string | null; amount_minor: number | null; occurred_on: string | null };
  /** The OCR provider's own estimate — the UI hedges a low-confidence guess
   * rather than presenting it as fact. */
  confidence: number;
  provider: string;
  error: string;
  confirmed_merchant: string;
  confirmed_amount_minor: number | null;
  confirmed_occurred_on: string | null;
  confirmed_category_id: string | null;
  linked_transaction_id: string | null;
  financial_account_id: string | null;
  download_url: string | null;
  created_at: string;
}

export interface ReceiptUploadTicket extends Receipt {
  /** Null when the storage backend can't presign (local dev) — the caller
   * falls back to sending bytes directly on confirm. */
  upload_url: string | null;
}

// ------------------------------------------------------------- quick add
export interface QuickAddResult {
  transaction_id: string;
  amount_minor: number;
  financial_account_id: string;
  financial_account_name: string;
  category_id: string | null;
  category_name: string | null;
  payee_name: string | null;
  occurred_at: string;
  /** Never silent — a user who typed one word and an amount deserves to see
   * what was guessed on their behalf before it settles into their history. */
  account_was_inferred: boolean;
  category_was_inferred: boolean;
  category_confidence: number | null;
}

// ------------------------------------------------------------- push
export interface PushSubscriptionKeys {
  p256dh: string;
  auth: string;
}

/** A workspace's own model choice. Blank fields mean "inherit" — the
 *  deployment's configuration applies. The API key is write-only, so only
 *  whether one is set ever comes back. */
export interface WorkspaceAISettings {
  provider: string;
  model: string;
  base_url: string;
  api_key_set: boolean;
}

export interface WorkspaceAISettingsInput {
  provider?: string;
  model?: string;
  base_url?: string;
  /** Omit to leave the stored key untouched; "" removes it. */
  api_key?: string;
}

/** One proposed budget line, with the reasoning that produced it. */
export interface SmartBudgetLine {
  category_id: string;
  category_name: string;
  limit_minor: number;
  floor_minor: number;
  history_minor: number;
  observed_months: number[];
  rationale: string;
}

/** A budget assembled from history, commitments, income and goals — a first
 * draft the user applies and then owns, never a rule imposed on them. */
export interface SmartBudgetProposal {
  currency: string;
  as_of: string;
  months_considered: number;
  income_minor: number;
  income_known: boolean;
  debt_minimums_minor: number;
  savings_target_minor: number;
  envelope_minor: number;
  total_minor: number;
  left_over_minor: number;
  trim_factor: number;
  deficit: boolean;
  lines: SmartBudgetLine[];
}

/** "When does work become optional?" — the projection an advisor charges a
 * consultation for. Spending-derived, banded, and honest about "never". */
export interface FIBandPoint {
  real_return: number;
  years: number | null;
  around_year: number | null;
}

export interface FIProjection {
  currency: string;
  as_of: string;
  months_measured: number;
  monthly_spending_minor: number;
  monthly_savings_minor: number;
  net_worth_minor: number;
  fi_number_minor: number;
  swr: number;
  progress_pct: number;
  band: FIBandPoint[];
  never_at_current_pace: boolean;
  required_monthly_for_horizon_minor: number | null;
  horizon_years: number;
  caveats: string[];
}
