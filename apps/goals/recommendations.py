"""Goal recommendations — what this user should be saving for, given their data.

Every recommendation is derived from the workspace's own figures (observed
expenses, liquid balances, existing debt), never from generic advice. A
suggestion the user cannot act on, or that ignores what they already have, is
noise — and financial software that nags about an emergency fund the user
already holds loses trust immediately.

Two rules govern this module:

1. **Never recommend what already exists.** Kinds already covered by an active
   goal are filtered out before anything else runs.
2. **Never invent a number.** Every suggested target is computed from the user's
   own history. Where the history isn't there, the recommendation is skipped
   rather than defaulted — a "3 months of expenses" target for someone whose
   expenses we cannot measure is a guess wearing a suit.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.finance.models import AccountType, FinancialAccount
from apps.finance.selectors import cashflow_statement

from .models import GoalKind, GoalStatus, SavingsGoal

#: Months of expenses a starter emergency fund should cover. Deliberately the
#: conservative end of the common 3–6 month guidance: a reachable target that
#: gets funded beats an intimidating one that doesn't.
EMERGENCY_FUND_MONTHS = 3

#: Minimum months of cash-flow history before expense-derived targets are
#: trustworthy enough to suggest.
MIN_HISTORY_MONTHS = 2


@dataclass(frozen=True, slots=True)
class GoalRecommendation:
    kind: str
    title: str
    rationale: str
    suggested_target_minor: int
    currency: str
    priority: int
    #: Suggested monthly contribution, when a sensible pace can be derived.
    suggested_monthly_minor: int | None = None


def _existing_kinds() -> set[str]:
    return set(
        SavingsGoal.objects.filter(status__in=[GoalStatus.ACTIVE, GoalStatus.PAUSED]).values_list(
            "kind", flat=True
        )
    )


def _average_monthly_expense_minor() -> tuple[int, str] | None:
    """Mean monthly outflow and its currency, from the cash-flow statement.

    `None` when there isn't enough history to be honest about. The statement
    selector already refuses to mix currencies, so this inherits that
    discipline.
    """
    statement = cashflow_statement(months=6)
    if statement is None or len(statement.rows) < MIN_HISTORY_MONTHS:
        return None
    outflows = [abs(r.outflow_minor) for r in statement.rows if r.outflow_minor]
    if len(outflows) < MIN_HISTORY_MONTHS:
        return None
    return sum(outflows) // len(outflows), statement.currency


def _emergency_fund(existing: set[str]) -> GoalRecommendation | None:
    """Size a safety net from the user's actual spending, net of cash they hold.

    Subtracting existing liquid savings matters: telling someone with £8,000 in
    savings to save £6,000 is obviously wrong to them, and being obviously wrong
    once costs the credibility of every later suggestion.
    """
    if GoalKind.EMERGENCY_FUND in existing:
        return None
    measured = _average_monthly_expense_minor()
    if measured is None:
        return None
    monthly_expense, currency = measured
    if monthly_expense <= 0:
        return None

    target = monthly_expense * EMERGENCY_FUND_MONTHS
    held = _liquid_savings_minor(currency)
    if held >= target:
        return None  # already covered; saying otherwise would be noise

    return GoalRecommendation(
        kind=GoalKind.EMERGENCY_FUND,
        title="Build an emergency fund",
        rationale=(
            f"Your spending averages about {monthly_expense / 100:,.0f} {currency} a month. "
            f"{EMERGENCY_FUND_MONTHS} months of cover would be {target / 100:,.0f} {currency}."
        ),
        suggested_target_minor=target,
        currency=currency,
        priority=1,
        # A year is a realistic runway for a first safety net.
        suggested_monthly_minor=-(-(target - held) // 12),
    )


def _liquid_savings_minor(currency: str) -> int:
    """Cash held in savings accounts, which an emergency fund already covers."""
    total = 0
    accounts = FinancialAccount.objects.filter(
        account_type=AccountType.SAVINGS,
        currency=currency,
        archived_at__isnull=True,
        include_in_net_worth=True,
    ).select_related("ledger_account__balance")
    from apps.finance.selectors import account_current_balance_minor

    for account in accounts:
        total += max(0, account_current_balance_minor(account))
    return total


def _debt_payoff(existing: set[str]) -> GoalRecommendation | None:
    """Recommend clearing revolving debt, sized to what is actually owed.

    Placed above discretionary saving because carried card balances almost
    always cost more in interest than savings earn — the one piece of ordering
    advice that holds regardless of the user's circumstances.
    """
    if GoalKind.DEBT_PAYOFF in existing:
        return None
    cards = FinancialAccount.objects.filter(
        account_type=AccountType.CREDIT_CARD, archived_at__isnull=True
    ).select_related("ledger_account__balance")

    from apps.finance.selectors import account_current_balance_minor

    by_currency: dict[str, int] = {}
    for card in cards:
        owed = account_current_balance_minor(card)
        if owed > 0:
            by_currency[card.currency] = by_currency.get(card.currency, 0) + owed
    if not by_currency:
        return None

    currency, owed = max(by_currency.items(), key=lambda kv: kv[1])
    return GoalRecommendation(
        kind=GoalKind.DEBT_PAYOFF,
        title="Clear your credit card balance",
        rationale=(
            f"You're carrying about {owed / 100:,.0f} {currency} on cards. "
            "Card interest usually outpaces savings interest, so clearing this first "
            "is generally worth more than saving the same amount."
        ),
        suggested_target_minor=owed,
        currency=currency,
        priority=2,
        suggested_monthly_minor=-(-owed // 12),
    )


def _retirement(existing: set[str]) -> GoalRecommendation | None:
    """Suggest starting retirement saving, sized as a year of contributions.

    Deliberately *not* a projected retirement number. Producing one requires
    assumptions about returns, inflation, retirement age and state provision
    that this product does not hold and should not silently invent — that is
    regulated advice territory, not a default.
    """
    if GoalKind.RETIREMENT in existing:
        return None
    measured = _average_monthly_expense_minor()
    if measured is None:
        return None
    monthly_expense, currency = measured
    if monthly_expense <= 0:
        return None

    monthly = monthly_expense // 10  # a starting 10% of outgoings
    if monthly <= 0:
        return None
    return GoalRecommendation(
        kind=GoalKind.RETIREMENT,
        title="Start putting something aside for later",
        rationale=(
            "Setting aside around 10% of what you spend each month builds a habit early, "
            "when time does most of the work."
        ),
        suggested_target_minor=monthly * 12,
        currency=currency,
        priority=2,
        suggested_monthly_minor=monthly,
    )


#: Order matters: the list is returned as-is and the UI shows the first few.
_BUILDERS = (_emergency_fund, _debt_payoff, _retirement)


def recommend_goals(*, limit: int = 3) -> list[GoalRecommendation]:
    """Recommendations for this workspace, most important first.

    Returns an empty list — not a filler suggestion — when the user's data
    doesn't support any honest recommendation. An empty state is a better
    experience than a fabricated one.
    """
    existing = _existing_kinds()
    out: list[GoalRecommendation] = []
    for build in _BUILDERS:
        rec = build(existing)
        if rec is not None:
            out.append(rec)
        if len(out) >= limit:
            break
    return out
