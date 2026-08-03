"""Debt read side — balances from the ledger, terms from the profile.

The split this module maintains: a debt's **balance** is a ledger fact, posted
by real transactions, and its **terms** are contract metadata. Neither is
derived from the other, and neither is stored twice.

Nothing here writes. Payoff plans are projections, computed on demand, exactly
like the cash-flow calendar — a stored plan is a plan that silently goes stale
the moment a payment posts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.finance.models import FinancialAccount
from apps.finance.selectors import account_current_balance_minor

from . import payoff, stress
from .models import DebtKind, DebtProfile, PayoffStrategy


@dataclass(frozen=True, slots=True)
class DebtView:
    """One debt, combining its ledger balance with its terms."""

    account_id: str
    profile_id: str | None
    name: str
    currency: str
    debt_kind: str
    balance_minor: int
    apr: Decimal
    minimum_payment_minor: int
    payment_day: int | None
    original_principal_minor: int | None
    include_in_payoff: bool
    custom_priority: int
    #: Monthly interest at the current balance and rate — the number that makes
    #: a rate feel real. "24% APR" is abstract; "£104 a month" is not.
    monthly_interest_minor: int
    #: True when the minimum doesn't cover the interest, so the balance grows
    #: even when payments are made on time.
    minimum_covers_interest: bool
    compounding: str = "monthly"
    rate_schedule: tuple = ()
    fees: object | None = None
    offset_minor: int = 0
    #: Days until a promotional rate ends. `None` when there isn't one.
    promo_days_remaining: int | None = None
    promo_ends_on: date | None = None
    #: Rate changes already notified but not yet in force.
    next_rate_change_on: date | None = None
    next_rate_apr: Decimal | None = None

    @property
    def percent_repaid(self) -> float | None:
        """How far through, when the original principal is known.

        `None` rather than 0 when it isn't: a balance alone cannot say how far
        through you are, and guessing would be a claim about a figure nobody
        supplied.
        """
        if not self.original_principal_minor or self.original_principal_minor <= 0:
            return None
        repaid = self.original_principal_minor - self.balance_minor
        return round(max(0.0, min(100.0, repaid / self.original_principal_minor * 100)), 1)


def _liability_accounts():
    from apps.finance.models import AccountType

    return (
        FinancialAccount.objects.filter(
            account_type__in=[AccountType.CREDIT_CARD, AccountType.LOAN],
            archived_at__isnull=True,
        )
        .select_related("ledger_account__balance", "debt_profile")
        # Rate history and offsets are read for every debt, so prefetching them
        # keeps the dashboard to a fixed number of queries rather than growing
        # with the number of debts.
        .prefetch_related(
            "debt_profile__rate_history",
            "debt_profile__offset_accounts__ledger_account__balance",
        )
    )


def tracked_liabilities(*, as_of: date | None = None) -> list[dict]:
    """Every liability account the workspace has, including ones owing nothing.

    Separate from `debt_views` on purpose. `debt_views` answers "what is owed",
    and correctly drops accounts with a zero balance — a paid-off card is not
    debt, and including it would put a meaningless row in the payoff plan and
    inflate `debt_count`.

    But that left the planner with no way to say "this card exists, you just
    don't owe anything on it". A user who followed the empty state's advice and
    added a credit card saw the *same* empty state afterwards, because their new
    account had no transactions yet and so no balance. Nothing acknowledged the
    thing they had just done, which reads as a broken page rather than an
    accurate one.

    This selector is what the UI uses to confirm the setup landed. It never
    feeds planning arithmetic.
    """
    as_of = as_of or timezone.localdate()
    out: list[dict] = []

    for account in _liability_accounts():
        profile = getattr(account, "debt_profile", None)
        if profile is not None and profile.deleted_at is not None:
            profile = None
        out.append(
            {
                "account_id": str(account.id),
                "name": account.name,
                "account_type": account.account_type,
                "currency": account.currency,
                "balance_minor": account_current_balance_minor(account),
                "has_terms": profile is not None,
                "apr": float(profile.effective_apr(as_of)) if profile else None,
                "minimum_payment_minor": profile.minimum_payment_minor if profile else 0,
            }
        )
    return sorted(out, key=lambda row: (-row["balance_minor"], row["name"]))


def debt_views(*, as_of: date | None = None) -> list[DebtView]:
    """Every outstanding liability, with terms where they've been recorded.

    Accounts without a profile are still returned — a debt you haven't entered
    terms for is still a debt, and hiding it would understate what's owed. It
    simply can't be planned around until an APR and minimum exist.
    """
    as_of = as_of or timezone.localdate()
    out: list[DebtView] = []

    for account in _liability_accounts():
        balance = account_current_balance_minor(account)
        if balance <= 0:
            continue
        # `select_related` pulls the row regardless of soft-deletion, and the
        # reverse accessor doesn't apply the alive-only manager. Cleared terms
        # must read as absent, or "stop planning" silently wouldn't.
        profile = getattr(account, "debt_profile", None)
        if profile is not None and profile.deleted_at is not None:
            profile = None
        apr = profile.effective_apr(as_of) if profile else Decimal("0")
        minimum = profile.minimum_payment_minor if profile else 0
        schedule = rate_schedule_for(profile)
        compounding = profile.compounding if profile else "monthly"
        offset = offset_balance_minor(profile)
        fees = _fees_for(profile)

        # A rate timeline supersedes the flat field once one exists.
        if schedule:
            applicable = [p for p in schedule if p.effective_from <= as_of]
            if applicable:
                apr = max(applicable, key=lambda p: p.effective_from).apr

        interest = payoff._monthly_interest_minor(
            balance, apr, compounding=compounding, offset_minor=offset
        )

        upcoming = [p for p in schedule if p.effective_from > as_of]
        next_change = min(upcoming, key=lambda p: p.effective_from) if upcoming else None

        promo_ends = profile.promotional_apr_until if profile else None
        promo_days = (
            (promo_ends - as_of).days
            if promo_ends is not None and promo_ends >= as_of
            else None
        )

        out.append(
            DebtView(
                account_id=str(account.id),
                profile_id=str(profile.id) if profile else None,
                name=account.name,
                currency=account.currency,
                debt_kind=profile.debt_kind if profile else DebtKind.OTHER,
                balance_minor=balance,
                apr=apr,
                minimum_payment_minor=minimum,
                payment_day=profile.payment_day if profile else None,
                original_principal_minor=profile.original_principal_minor if profile else None,
                include_in_payoff=profile.include_in_payoff if profile else True,
                custom_priority=profile.custom_priority if profile else 100,
                monthly_interest_minor=interest,
                # No minimum recorded means we can't judge it either way, so
                # this reports True rather than raising a false alarm.
                minimum_covers_interest=(minimum > interest) if minimum else True,
                compounding=compounding,
                rate_schedule=schedule,
                fees=fees,
                offset_minor=offset,
                promo_days_remaining=promo_days,
                promo_ends_on=promo_ends,
                next_rate_change_on=next_change.effective_from if next_change else None,
                next_rate_apr=next_change.apr if next_change else None,
            )
        )
    return sorted(out, key=lambda d: -d.balance_minor)


def _dominant_currency(views: list[DebtView]) -> str | None:
    """The currency most of the debt is in.

    Payoff plans are single-currency for the same reason net worth is: summing
    a dollar balance and a euro balance without a rate is a correctness bug,
    not a convenience.
    """
    if not views:
        return None
    totals: dict[str, int] = {}
    for v in views:
        totals[v.currency] = totals.get(v.currency, 0) + v.balance_minor
    return max(totals.items(), key=lambda kv: kv[1])[0]


def rate_schedule_for(profile: DebtProfile | None) -> tuple[payoff.RatePeriod, ...]:
    """Build the engine's rate timeline from stored terms.

    Two sources merge into one schedule, which is the whole reason the engine
    models rates as a timeline rather than a value plus a special case:

      * recorded rate history, including future-dated changes a lender has
        already notified;
      * the legacy promotional fields, expressed as an intro period followed by
        the standard rate.

    Existing fixed-rate debts have neither and get an empty schedule, which the
    engine reads as "use `apr` throughout" — so nothing about their behaviour
    changes.
    """
    if profile is None:
        return ()

    periods: list[payoff.RatePeriod] = [
        payoff.RatePeriod(effective_from=entry.effective_from, apr=entry.apr)
        for entry in profile.rate_history.all()
    ]

    # The promotional fields predate rate history; translating them here means
    # one code path downstream and no migration of existing data.
    if profile.promotional_apr is not None and profile.promotional_apr_until is not None:
        start = profile.opened_on or date(1970, 1, 1)
        periods.append(payoff.RatePeriod(effective_from=start, apr=profile.promotional_apr))
        periods.append(
            payoff.RatePeriod(
                effective_from=profile.promotional_apr_until + timedelta(days=1),
                apr=profile.apr,
            )
        )

    return tuple(sorted(periods, key=lambda p: p.effective_from))


def _fees_for(profile: DebtProfile | None) -> payoff.DebtFees | None:
    if profile is None:
        return None
    if not (profile.monthly_fee_minor or profile.annual_fee_minor or profile.origination_fee_minor):
        return None
    return payoff.DebtFees(
        monthly_minor=profile.monthly_fee_minor,
        annual_minor=profile.annual_fee_minor,
        annual_month=profile.annual_fee_month,
        origination_minor=profile.origination_fee_minor,
    )


def offset_balance_minor(profile: DebtProfile | None) -> int:
    """Total in the accounts linked as offsets.

    Only positive balances count: an overdrawn current account doesn't offset
    a mortgage, and letting it contribute a negative would *increase* the
    interest charged — a silent and very wrong result.
    """
    if profile is None:
        return 0
    total = 0
    for account in profile.offset_accounts.all():
        total += max(0, account_current_balance_minor(account))
    return total


def to_debt_inputs(views: list[DebtView]) -> list[payoff.DebtInput]:
    """Convert to the engine's input shape, keeping only plannable debts."""
    return [
        payoff.DebtInput(
            debt_id=v.account_id,
            name=v.name,
            balance_minor=v.balance_minor,
            apr=v.apr,
            minimum_payment_minor=v.minimum_payment_minor,
            kind=v.debt_kind,
            custom_priority=v.custom_priority,
            rate_schedule=v.rate_schedule,
            compounding=v.compounding,
            fees=v.fees,
            offset_minor=v.offset_minor,
        )
        for v in views
        if v.include_in_payoff and v.minimum_payment_minor > 0
    ]


@dataclass(frozen=True, slots=True)
class DebtSummary:
    currency: str
    total_balance_minor: int
    total_minimum_minor: int
    total_monthly_interest_minor: int
    debt_count: int
    #: Weighted by balance, so a large cheap loan doesn't get out-shouted by a
    #: tiny expensive card. A plain average would be misleading here.
    weighted_apr: float
    highest_apr_name: str | None
    highest_apr: float | None
    #: Debts with no terms recorded, so they can't be planned around yet.
    unplannable_count: int
    #: Debts whose minimum doesn't cover their interest.
    growing_count: int
    #: Debts with terms recorded, and so the only ones the rate and interest
    #: figures are derived from. Zero means those figures are zero because
    #: nothing was ever entered, not because the debt is free — a distinction
    #: the UI has to be able to make. See `weighted_apr` below.
    priced_count: int = 0

    @property
    def annual_interest_minor(self) -> int:
        """What this debt costs a year at the current balance.

        The single most persuasive number in the module: monthly interest is
        easy to shrug off, the annual figure much less so.
        """
        return self.total_monthly_interest_minor * 12


def debt_summary(*, as_of: date | None = None) -> DebtSummary | None:
    """Headline debt figures. `None` when nothing is owed — which is a real
    answer, and a better one than a row of zeroes."""
    views = debt_views(as_of=as_of)
    if not views:
        return None

    currency = _dominant_currency(views)
    scoped = [v for v in views if v.currency == currency]
    total = sum(v.balance_minor for v in scoped)

    # Averaged over the debts whose rate is actually known, not over all of
    # them. A debt with no terms recorded carries `apr = 0`, and including it
    # dragged the weighted average toward zero — so adding a card you hadn't
    # entered terms for made your borrowing look cheaper. The reported rate
    # now describes exactly the debts it was computed from, and
    # `priced_count` tells the caller how many that was.
    priced = [v for v in scoped if v.profile_id is not None]
    priced_balance = sum(v.balance_minor for v in priced)

    weighted = 0.0
    if priced_balance > 0:
        weighted = round(
            sum(float(v.apr) * v.balance_minor for v in priced) / priced_balance, 2
        )

    rated = [v for v in scoped if v.apr > 0]
    highest = max(rated, key=lambda v: v.apr) if rated else None

    return DebtSummary(
        currency=currency,
        total_balance_minor=total,
        total_minimum_minor=sum(v.minimum_payment_minor for v in scoped),
        total_monthly_interest_minor=sum(v.monthly_interest_minor for v in scoped),
        debt_count=len(scoped),
        weighted_apr=weighted,
        highest_apr_name=highest.name if highest else None,
        highest_apr=float(highest.apr) if highest else None,
        unplannable_count=sum(1 for v in scoped if v.minimum_payment_minor <= 0),
        growing_count=sum(1 for v in scoped if not v.minimum_covers_interest),
        priced_count=len(priced),
    )


def payoff_plan(
    *,
    strategy: str = PayoffStrategy.AVALANCHE,
    extra_monthly_minor: int = 0,
    as_of: date | None = None,
) -> payoff.PayoffPlan | None:
    """Run a payoff simulation over the current debts."""
    views = debt_views(as_of=as_of)
    currency = _dominant_currency(views)
    if currency is None:
        return None
    inputs = to_debt_inputs([v for v in views if v.currency == currency])
    if not inputs:
        return None
    return payoff.simulate(
        inputs,
        strategy=strategy,
        extra_monthly_minor=extra_monthly_minor,
        start=as_of or timezone.localdate(),
        currency=currency,
    )


def strategy_comparison(
    *, extra_monthly_minor: int = 0, as_of: date | None = None
) -> list[payoff.StrategyComparison]:
    views = debt_views(as_of=as_of)
    currency = _dominant_currency(views)
    if currency is None:
        return []
    inputs = to_debt_inputs([v for v in views if v.currency == currency])
    if not inputs:
        return []
    return payoff.compare_strategies(
        inputs,
        extra_monthly_minor=extra_monthly_minor,
        start=as_of or timezone.localdate(),
        currency=currency,
    )


def extra_payment_curve(*, strategy: str = PayoffStrategy.AVALANCHE, as_of: date | None = None):
    views = debt_views(as_of=as_of)
    currency = _dominant_currency(views)
    if currency is None:
        return []
    inputs = to_debt_inputs([v for v in views if v.currency == currency])
    if not inputs:
        return []
    return payoff.extra_payment_curve(inputs, strategy=strategy, start=as_of or timezone.localdate())


@dataclass(frozen=True, slots=True)
class PayoffCalendarEntry:
    """One debt's payment in one month, for the payoff calendar."""

    as_of: date
    debt_id: str
    name: str
    payment_minor: int
    interest_minor: int
    principal_minor: int
    balance_after_minor: int
    clears_here: bool


def payoff_calendar(
    *,
    strategy: str = PayoffStrategy.AVALANCHE,
    extra_monthly_minor: int = 0,
    months: int = 12,
    as_of: date | None = None,
) -> list[dict]:
    """Month-by-month payment schedule.

    Grouped by month rather than by debt, because that's how the money actually
    leaves: a user wants to know what March costs, not what the car loan costs
    across three years.
    """
    plan = payoff_plan(
        strategy=strategy, extra_monthly_minor=extra_monthly_minor, as_of=as_of
    )
    if plan is None:
        return []

    out: list[dict] = []
    for month in plan.months[:months]:
        out.append(
            {
                "as_of": month.as_of,
                "total_paid_minor": month.total_paid_minor,
                "total_interest_minor": month.total_interest_minor,
                "remaining_balance_minor": month.remaining_balance_minor,
                "payments": [
                    {
                        "debt_id": p.debt_id,
                        "name": p.name,
                        "payment_minor": p.payment_minor,
                        "interest_minor": p.interest_minor,
                        "principal_minor": p.principal_minor,
                        "balance_after_minor": p.balance_after_minor,
                        "clears_here": p.cleared,
                    }
                    for p in month.payments
                ],
            }
        )
    return out


#: Avalanche is recommended over snowball once it saves more than this share
#: of the total interest. See `debt_recommendation` for the reasoning.
MATERIAL_SAVING_FRACTION = 0.05


@dataclass(frozen=True, slots=True)
class DebtAlert:
    """Something about this debt that needs saying."""

    severity: str  # critical | warning | info
    title: str
    body: str
    account_id: str | None = None


def debt_alerts(*, as_of: date | None = None) -> list[DebtAlert]:
    """Conditions worth raising, most serious first.

    Deliberately few. A debt dashboard that flags everything gets closed; these
    are the situations where doing nothing has a real and compounding cost.
    """
    views = debt_views(as_of=as_of)
    if not views:
        return []

    alerts: list[DebtAlert] = []

    # The most serious thing that can be true of a debt: paying the minimum on
    # time and still owing more each month.
    for view in views:
        if not view.minimum_covers_interest and view.minimum_payment_minor > 0:
            alerts.append(
                DebtAlert(
                    severity="critical",
                    title=f"{view.name} is growing despite payments",
                    body=(
                        f"Interest is about {view.monthly_interest_minor / 100:,.0f} "
                        f"{view.currency} a month but the minimum is only "
                        f"{view.minimum_payment_minor / 100:,.0f}. The balance rises even when "
                        "you pay on time."
                    ),
                    account_id=view.account_id,
                )
            )

    # `apr <= 0` was calling a recorded 0% promotional card "missing terms" —
    # the same conflation of unmeasured with zero this module is being cleaned
    # of. What actually blocks a payoff plan is no profile at all, or no
    # minimum payment to simulate against; a rate of zero is a rate.
    missing = [
        v for v in views if v.profile_id is None or v.minimum_payment_minor <= 0
    ]
    if missing:
        alerts.append(
            DebtAlert(
                severity="info",
                title=f"{len(missing)} debt{'s' if len(missing) > 1 else ''} missing terms",
                body=(
                    "Add the interest rate and minimum payment to include "
                    f"{'them' if len(missing) > 1 else 'it'} in your payoff plan."
                ),
                account_id=missing[0].account_id if len(missing) == 1 else None,
            )
        )

    summary = debt_summary(as_of=as_of)
    if summary and summary.total_monthly_interest_minor > 0:
        alerts.append(
            DebtAlert(
                severity="warning",
                title=f"Interest is costing about {summary.annual_interest_minor / 100:,.0f} {summary.currency} a year",
                body=(
                    f"At your current balances, that's {summary.total_monthly_interest_minor / 100:,.0f} "
                    "a month before any of it reduces what you owe."
                ),
            )
        )

    # The signal engine covers promo expiries, rate rises, fee-heavy products,
    # offset opportunities and milestones. Folding them in here means the debt
    # dashboard and the coach are reading the same analysis rather than two.
    for signal in debt_signals(as_of=as_of):
        alerts.append(
            DebtAlert(
                severity=signal.severity,
                title=signal.title,
                body=signal.body,
                account_id=signal.account_id,
            )
        )

    order = {"critical": 0, "warning": 1, "opportunity": 2, "info": 3}
    return sorted(alerts, key=lambda a: order.get(a.severity, 4))


def debt_recommendation(*, extra_monthly_minor: int = 0, as_of: date | None = None) -> dict | None:
    """A single suggested next step, with the reasoning behind it.

    Recommends avalanche when it saves a material amount and snowball when the
    difference is small enough that finishing a debt sooner is worth more than
    the interest. Presenting the trade-off honestly beats asserting one method
    is correct — which one suits someone is a judgement about them, not a
    calculation.
    """
    comparisons = strategy_comparison(extra_monthly_minor=extra_monthly_minor, as_of=as_of)
    if not comparisons:
        return None

    by_strategy = {c.strategy: c for c in comparisons}
    avalanche = by_strategy.get("avalanche")
    snowball = by_strategy.get("snowball")
    if avalanche is None or snowball is None:
        return None

    difference = snowball.total_interest_minor - avalanche.total_interest_minor
    summary = debt_summary(as_of=as_of)
    currency = summary.currency if summary else "USD"

    # Judged as a *share* of the interest bill rather than an absolute amount.
    # A flat threshold is wrong at both ends: it dismisses a real saving on a
    # small debt and over-weights a trivial one on a mortgage. Five percent is
    # the point at which the money is worth more than the easier plan — below
    # it, sticking with a plan matters more than optimising it, and a plan
    # abandoned in month four saves nothing at all.
    material = (
        snowball.total_interest_minor > 0
        and difference / snowball.total_interest_minor > MATERIAL_SAVING_FRACTION
    )

    if material:
        return {
            "strategy": "avalanche",
            "title": f"Target {'your highest-rate debt' if not avalanche.first_cleared_name else avalanche.first_cleared_name} first",
            "rationale": (
                f"Paying highest-rate first would cost about {difference / 100:,.0f} {currency} "
                "less in interest than smallest-balance first."
            ),
            "interest_saved_minor": avalanche.interest_saved_minor,
            "months_saved": avalanche.months_saved,
            "alternative": "snowball",
        }

    return {
        "strategy": "snowball",
        "title": f"Clear {snowball.first_cleared_name or 'your smallest debt'} first",
        "rationale": (
            f"Smallest-balance first costs only about {max(0, difference) / 100:,.0f} {currency} more "
            "in interest here, and clearing a debt sooner makes a plan much easier to stick to."
        ),
        "interest_saved_minor": snowball.interest_saved_minor,
        "months_saved": snowball.months_saved,
        "alternative": "avalanche",
    }


def committed_monthly_minor(*, as_of: date | None = None) -> int:
    """Total minimum payments — the debt service the cash-flow view must know
    about.

    Exposed for the cash-flow calendar and budgeting: minimums are committed
    outflow, not discretionary, and a plan that treats them as optional is not
    a plan.
    """
    return sum(v.minimum_payment_minor for v in debt_views(as_of=as_of))


# =============================================================================
# Borrowing cost and stress score
# =============================================================================
@dataclass(frozen=True, slots=True)
class BorrowingCost:
    """What debt costs over a year, split into its parts.

    Interest and fees are reported separately because they behave differently:
    interest falls as the balance does, while an annual fee does not. A
    combined figure would hide a card whose real cost is mostly a fee that
    paying it down will never reduce.
    """

    currency: str
    annual_interest_minor: int
    annual_fees_minor: int
    monthly_interest_minor: int
    monthly_fees_minor: int
    #: Debts these figures could actually be computed from, against the number
    #: in scope. A cost of zero derived from no terms at all is not a finding
    #: about the debt, and must not be presented as one.
    priced_count: int = 0
    debt_count: int = 0

    @property
    def annual_total_minor(self) -> int:
        return self.annual_interest_minor + self.annual_fees_minor

    @property
    def fee_share(self) -> float:
        """Share of the annual cost that is fees rather than interest."""
        total = self.annual_total_minor
        return round(self.annual_fees_minor / total * 100, 1) if total > 0 else 0.0


def borrowing_cost(*, as_of: date | None = None) -> BorrowingCost | None:
    """Annual cost of carrying the current debts."""
    views = debt_views(as_of=as_of)
    if not views:
        return None
    currency = _dominant_currency(views)
    scoped = [v for v in views if v.currency == currency]

    monthly_interest = sum(v.monthly_interest_minor for v in scoped)
    monthly_fees = sum(v.fees.monthly_minor if v.fees else 0 for v in scoped)
    annual_fees = sum(v.fees.annual_minor if v.fees else 0 for v in scoped)

    return BorrowingCost(
        currency=currency,
        annual_interest_minor=monthly_interest * 12,
        annual_fees_minor=monthly_fees * 12 + annual_fees,
        monthly_interest_minor=monthly_interest,
        monthly_fees_minor=monthly_fees,
        priced_count=sum(1 for v in scoped if v.profile_id is not None),
        debt_count=len(scoped),
    )


def _monthly_income_minor() -> int | None:
    """Typical monthly inflow, or `None` when it can't be measured.

    `None` rather than zero: scoring someone's debt-to-income as if they earned
    nothing would produce an alarming figure derived purely from missing data.
    """
    from apps.finance import selectors as finance_selectors

    statement = finance_selectors.cashflow_statement(months=6)
    if statement is None or not statement.rows:
        return None
    inflows = [r.inflow_minor for r in statement.rows if r.inflow_minor > 0]
    if not inflows:
        return None
    return sum(inflows) // len(inflows)


def debt_stress(*, as_of: date | None = None) -> dict | None:
    """The Debt Stress Score, with its full derivation.

    Assembles the inputs the pure scorer needs and returns `explain()` output,
    so a caller always gets the reasoning alongside the number — a score
    nobody can interrogate is one they will over-trust or ignore.
    """
    summary = debt_summary(as_of=as_of)
    if summary is None:
        return None

    views = debt_views(as_of=as_of)
    scoped = [v for v in views if v.currency == summary.currency]

    # Utilisation only means anything for revolving credit: a mortgage has no
    # limit to be a percentage of.
    revolving = sum(
        v.balance_minor for v in scoped if v.debt_kind == DebtKind.CREDIT_CARD
    )

    plan = payoff_plan(as_of=as_of)
    inputs = stress.StressInputs(
        total_balance_minor=summary.total_balance_minor,
        total_minimum_minor=summary.total_minimum_minor,
        monthly_interest_minor=summary.total_monthly_interest_minor,
        monthly_income_minor=_monthly_income_minor(),
        revolving_balance_minor=revolving,
        weighted_apr=summary.weighted_apr,
        months_to_debt_free=plan.months_to_debt_free if plan else None,
    )
    result = stress.compute(inputs)
    payload = stress.explain(result)
    payload["currency"] = summary.currency
    return payload


# =============================================================================
# Debt intelligence signals — consumed by the coach and the alerts surface
# =============================================================================
#: A promotional rate inside this window is worth warning about. Long enough to
#: actually do something (shift the balance, arrange a transfer), short enough
#: that the warning still feels relevant.
PROMO_WARNING_DAYS = 60

#: Fees above this share of a debt's annual cost mean paying the balance down
#: barely touches what it costs to hold.
HIGH_FEE_SHARE = 0.25

#: An idle balance above this is worth offsetting against a mortgage.
OFFSET_OPPORTUNITY_MINOR = 100_000


@dataclass(frozen=True, slots=True)
class DebtSignal:
    """One observation about a debt, with the evidence behind it.

    Deliberately shaped like the coach's `InsightCandidate` without importing
    it: this module stays free of the intelligence app, and the coach adapts
    these rather than this module knowing about insights.
    """

    kind: str
    severity: str
    title: str
    body: str
    rationale: str
    dedupe_key: str
    evidence: dict
    account_id: str | None = None
    action: dict | None = None


def _promo_expiry_signals(views: list[DebtView], as_of: date) -> list[DebtSignal]:
    out: list[DebtSignal] = []
    for view in views:
        days = view.promo_days_remaining
        if days is None or days > PROMO_WARNING_DAYS:
            continue
        # What the balance will start costing once the promo ends.
        future_apr = view.next_rate_apr
        monthly_after = (
            payoff._monthly_interest_minor(
                view.balance_minor, future_apr, compounding=view.compounding
            )
            if future_apr
            else None
        )
        out.append(
            DebtSignal(
                kind="promo_expiry",
                severity="warning" if days > 14 else "critical",
                title=f"{view.name}: promotional rate ends in {days} days",
                body=(
                    f"On {view.promo_ends_on:%-d %b} the rate returns to "
                    f"{float(future_apr):.1f}%."
                    + (
                        f" At today's balance that's about "
                        f"{monthly_after / 100:,.0f} {view.currency} a month in interest."
                        if monthly_after
                        else ""
                    )
                ),
                rationale=(
                    "Your recorded promotional rate has an end date, and the balance still "
                    "outstanding will be charged at the standard rate from that day."
                ),
                dedupe_key=f"promo:{view.account_id}:{view.promo_ends_on}",
                evidence={
                    "days_remaining": days,
                    "ends_on": view.promo_ends_on.isoformat() if view.promo_ends_on else None,
                    "balance_minor": view.balance_minor,
                    "standard_apr": float(future_apr) if future_apr else None,
                },
                account_id=view.account_id,
                action={"action": "open_debt_planner"},
            )
        )
    return out


def _rate_increase_signals(views: list[DebtView], as_of: date) -> list[DebtSignal]:
    """Notified rate rises that haven't bitten yet."""
    out: list[DebtSignal] = []
    for view in views:
        if view.next_rate_change_on is None or view.next_rate_apr is None:
            continue
        if view.next_rate_apr <= view.apr:
            continue
        days = (view.next_rate_change_on - as_of).days
        if days > 90:
            continue
        out.append(
            DebtSignal(
                kind="rate_increase",
                severity="warning",
                title=f"{view.name}: rate rises to {float(view.next_rate_apr):.1f}% soon",
                body=(
                    f"From {view.next_rate_change_on:%-d %b} this debt moves from "
                    f"{float(view.apr):.1f}% to {float(view.next_rate_apr):.1f}%."
                ),
                rationale=(
                    "A future rate has been recorded against this debt and takes effect on that "
                    "date. Your payoff plan already accounts for it."
                ),
                dedupe_key=f"rate_up:{view.account_id}:{view.next_rate_change_on}",
                evidence={
                    "current_apr": float(view.apr),
                    "new_apr": float(view.next_rate_apr),
                    "effective_from": view.next_rate_change_on.isoformat(),
                },
                account_id=view.account_id,
            )
        )
    return out


def _high_fee_signals(views: list[DebtView]) -> list[DebtSignal]:
    out: list[DebtSignal] = []
    for view in views:
        if view.fees is None:
            continue
        annual_fees = view.fees.monthly_minor * 12 + view.fees.annual_minor
        annual_interest = view.monthly_interest_minor * 12
        total = annual_fees + annual_interest
        if total <= 0 or annual_fees / total < HIGH_FEE_SHARE:
            continue
        out.append(
            DebtSignal(
                kind="high_fees",
                severity="opportunity",
                title=f"{view.name} costs {annual_fees / 100:,.0f} {view.currency} a year in fees",
                body=(
                    f"That's {annual_fees / total * 100:.0f}% of what this debt costs you. "
                    "Paying the balance down won't reduce it."
                ),
                # The genuinely useful part: fees don't shrink with the balance.
                rationale=(
                    "Fees are charged regardless of the balance, so unlike interest they don't "
                    "fall as you repay. A product without them may cost less even at a higher rate."
                ),
                dedupe_key=f"fees:{view.account_id}",
                evidence={
                    "annual_fees_minor": annual_fees,
                    "annual_interest_minor": annual_interest,
                    "fee_share": round(annual_fees / total * 100, 1),
                },
                account_id=view.account_id,
            )
        )
    return out


def _offset_opportunity_signals(views: list[DebtView]) -> list[DebtSignal]:
    """Idle cash that could be offsetting a mortgage.

    Only suggested where the debt already supports offsetting — proposing it on
    a product that doesn't offer it would be advice the user cannot act on.
    """
    from apps.finance.models import AccountType, FinancialAccount

    candidates = [
        v
        for v in views
        if v.debt_kind == DebtKind.MORTGAGE and v.offset_minor == 0 and v.apr > 0
    ]
    if not candidates:
        return []

    idle = 0
    for account in FinancialAccount.objects.filter(
        account_type=AccountType.SAVINGS, archived_at__isnull=True
    ).select_related("ledger_account__balance"):
        if account.currency == candidates[0].currency:
            idle += max(0, account_current_balance_minor(account))
    if idle < OFFSET_OPPORTUNITY_MINOR:
        return []

    debt = candidates[0]
    saving = payoff._monthly_interest_minor(
        debt.balance_minor, debt.apr, compounding=debt.compounding
    ) - payoff._monthly_interest_minor(
        debt.balance_minor, debt.apr, compounding=debt.compounding, offset_minor=idle
    )
    if saving <= 0:
        return []

    return [
        DebtSignal(
            kind="offset_opportunity",
            severity="opportunity",
            title=f"Offsetting could save about {saving / 100:,.0f} {debt.currency} a month",
            body=(
                f"You hold about {idle / 100:,.0f} {debt.currency} in savings. Linking it to "
                f"{debt.name} would reduce the interest charged without moving the money."
            ),
            rationale=(
                "Offset arrangements charge interest on the balance less the linked savings. "
                "The money stays yours and stays available — it simply stops being charged for."
            ),
            dedupe_key=f"offset:{debt.account_id}",
            evidence={
                "idle_savings_minor": idle,
                "monthly_saving_minor": saving,
                "annual_saving_minor": saving * 12,
            },
            account_id=debt.account_id,
            action={"action": "open_debt_planner"},
        )
    ]


def _refinance_opportunity_signals(views: list[DebtView], as_of: date) -> list[DebtSignal]:
    """Debts priced well above the rest of the portfolio.

    Deliberately conservative: this flags that a debt is expensive relative to
    what the user already pays elsewhere. It does not claim a specific product
    is available, because we have no rate data to support that.
    """
    priced = [v for v in views if v.apr > 0 and v.minimum_payment_minor > 0]
    if len(priced) < 2:
        return []

    total = sum(v.balance_minor for v in priced)
    if total <= 0:
        return []
    weighted = sum(float(v.apr) * v.balance_minor for v in priced) / total

    out: list[DebtSignal] = []
    for view in priced:
        # Materially above the portfolio average and big enough to matter.
        if float(view.apr) < weighted * 1.5 or view.balance_minor < 100_000:
            continue
        annual_interest = view.monthly_interest_minor * 12
        out.append(
            DebtSignal(
                kind="refinance_opportunity",
                severity="opportunity",
                title=f"{view.name} is your most expensive borrowing at {float(view.apr):.1f}%",
                body=(
                    f"It costs about {annual_interest / 100:,.0f} {view.currency} a year in "
                    f"interest, against a {weighted:.1f}% average across your other debts."
                ),
                rationale=(
                    f"This compares each debt's rate against the balance-weighted average of "
                    f"{weighted:.1f}%. Whether a better rate is actually available to you depends "
                    "on your circumstances — this only shows where the cost is concentrated."
                ),
                dedupe_key=f"refinance:{view.account_id}:{as_of.strftime('%Y-%m')}",
                evidence={
                    "apr": float(view.apr),
                    "portfolio_average_apr": round(weighted, 2),
                    "annual_interest_minor": annual_interest,
                },
                account_id=view.account_id,
                action={"action": "open_debt_planner"},
            )
        )
    return out[:1]


def _milestone_signals(views: list[DebtView]) -> list[DebtSignal]:
    """Progress worth acknowledging.

    A planner that only ever reports problems is one people stop opening. These
    are real, measured milestones — not encouragement invented to fill space.
    """
    out: list[DebtSignal] = []
    for view in views:
        repaid = view.percent_repaid
        if repaid is None:
            continue
        for threshold in (75, 50, 25):
            if repaid >= threshold:
                out.append(
                    DebtSignal(
                        kind="debt_milestone",
                        severity="info",
                        title=f"{view.name} is {threshold}% repaid",
                        body=(
                            f"You've cleared {repaid:.0f}% of the original "
                            f"{view.original_principal_minor / 100:,.0f} {view.currency}."
                        ),
                        rationale=(
                            "Measured against the original principal you recorded for this debt."
                        ),
                        dedupe_key=f"milestone:{view.account_id}:{threshold}",
                        evidence={
                            "percent_repaid": repaid,
                            "original_principal_minor": view.original_principal_minor,
                            "balance_minor": view.balance_minor,
                        },
                        account_id=view.account_id,
                    )
                )
                break
    return out


def debt_signals(*, as_of: date | None = None) -> list[DebtSignal]:
    """Everything the debt module has to say, most serious first.

    Consumed by the coach (as insights) and the debt dashboard (as alerts), so
    the two can never disagree about what's worth mentioning.
    """
    as_of = as_of or timezone.localdate()
    views = debt_views(as_of=as_of)
    if not views:
        return []

    signals = [
        *_promo_expiry_signals(views, as_of),
        *_rate_increase_signals(views, as_of),
        *_refinance_opportunity_signals(views, as_of),
        *_high_fee_signals(views),
        *_offset_opportunity_signals(views),
        *_milestone_signals(views),
    ]
    order = {"critical": 0, "warning": 1, "opportunity": 2, "info": 3}
    return sorted(signals, key=lambda s: order.get(s.severity, 4))


# =============================================================================
# Analytics
# =============================================================================
def debt_analytics(
    *,
    strategy: str = PayoffStrategy.AVALANCHE,
    extra_monthly_minor: int = 0,
    months: int = 24,
    as_of: date | None = None,
) -> dict | None:
    """Series for the debt dashboards, all derived from one simulation.

    Computed from a single `payoff_plan` call rather than several: every series
    here is a different view of the same projection, and running the simulator
    once per chart would be both slower and capable of disagreeing with itself.

    Nothing is stored — these are projections, and a cached one goes stale the
    moment a payment posts.
    """
    plan = payoff_plan(
        strategy=strategy, extra_monthly_minor=extra_monthly_minor, as_of=as_of
    )
    if plan is None:
        return None

    interest_over_time: list[dict] = []
    running_interest = 0
    running_principal = 0
    opening = sum(p.starting_balance_minor for p in plan.per_debt)

    for month in plan.months[:months]:
        principal = month.total_paid_minor - month.total_interest_minor - month.total_fees_minor
        running_interest += month.total_interest_minor
        running_principal += max(0, principal)
        interest_over_time.append(
            {
                "as_of": month.as_of,
                "interest_minor": month.total_interest_minor,
                "fees_minor": month.total_fees_minor,
                "principal_minor": max(0, principal),
                "cumulative_interest_minor": running_interest,
                "cumulative_principal_minor": running_principal,
                "remaining_balance_minor": month.remaining_balance_minor,
            }
        )

    views = debt_views(as_of=as_of)
    currency = plan.currency
    scoped = [v for v in views if v.currency == currency]

    # Composition by kind, so the shape of the debt is visible at a glance.
    composition: dict[str, int] = {}
    for view in scoped:
        composition[view.debt_kind] = composition.get(view.debt_kind, 0) + view.balance_minor

    total = sum(composition.values())
    composition_rows = [
        {
            "kind": kind,
            "balance_minor": balance,
            "percent": round(balance / total * 100, 1) if total else 0.0,
        }
        for kind, balance in sorted(composition.items(), key=lambda kv: -kv[1])
    ]

    # Velocity: how fast the balance is actually falling. The first month's
    # principal is the honest current rate; averaging over the whole plan would
    # flatter it, since the rollover accelerates later.
    first_principal = interest_over_time[0]["principal_minor"] if interest_over_time else 0

    return {
        "currency": currency,
        "strategy": plan.strategy,
        "opening_balance_minor": opening,
        "series": interest_over_time,
        "composition": composition_rows,
        "monthly_velocity_minor": first_principal,
        "total_interest_minor": plan.total_interest_minor,
        "total_fees_minor": plan.total_fees_minor,
        "months_to_debt_free": plan.months_to_debt_free,
        "debt_free_on": plan.debt_free_on,
    }


def payoff_timeline_csv(
    *,
    strategy: str = PayoffStrategy.AVALANCHE,
    extra_monthly_minor: int = 0,
    as_of: date | None = None,
) -> str:
    """The full payoff schedule as CSV.

    Amounts are exported in major units with two decimals rather than minor
    integers: a spreadsheet is where this is going, and 52350 in a column
    someone will sum is a trap.
    """
    import csv
    import io

    plan = payoff_plan(
        strategy=strategy, extra_monthly_minor=extra_monthly_minor, as_of=as_of
    )
    if plan is None:
        return ""

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "month",
            "date",
            "debt",
            "opening_balance",
            "payment",
            "interest",
            "fees",
            "principal",
            "closing_balance",
            "cleared",
            "currency",
        ]
    )
    for month in plan.months:
        for payment in month.payments:
            opening = payment.balance_after_minor + payment.principal_minor
            writer.writerow(
                [
                    month.month_index,
                    month.as_of.isoformat(),
                    payment.name,
                    f"{opening / 100:.2f}",
                    f"{payment.payment_minor / 100:.2f}",
                    f"{payment.interest_minor / 100:.2f}",
                    f"{payment.fee_minor / 100:.2f}",
                    f"{payment.principal_minor / 100:.2f}",
                    f"{payment.balance_after_minor / 100:.2f}",
                    "yes" if payment.cleared else "",
                    plan.currency,
                ]
            )
    return buffer.getvalue()


def payoff_timeline_pdf(
    *,
    strategy: str = PayoffStrategy.AVALANCHE,
    extra_monthly_minor: int = 0,
    as_of: date | None = None,
) -> bytes:
    """The payoff schedule as a printable PDF.

    A document rather than a data dump — someone exporting this is filing it or
    taking it to a lender, so it leads with the summary that makes the table
    make sense: what it costs, and when it ends.

    Amounts are in major units for the same reason as the CSV: this is read by
    people, not parsed.

    Returns empty bytes when there is nothing to schedule, so callers can answer
    204 rather than serving a blank document.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    import io

    plan = payoff_plan(
        strategy=strategy, extra_monthly_minor=extra_monthly_minor, as_of=as_of
    )
    if plan is None:
        return b""

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title="Debt payoff schedule",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    story = []

    strategy_label = {
        "avalanche": "Highest rate first",
        "snowball": "Smallest balance first",
        "custom": "Custom order",
    }.get(plan.strategy, plan.strategy)

    story.append(Paragraph("Debt payoff schedule", styles["Title"]))
    story.append(Spacer(1, 4 * mm))

    # The summary a reader needs before the table means anything.
    summary_rows = [
        ["Strategy", strategy_label],
        ["Monthly budget", f"{plan.monthly_budget_minor / 100:,.2f} {plan.currency}"],
        [
            "Debt free",
            plan.debt_free_on.strftime("%B %Y")
            if plan.debt_free_on
            else "Not at these payments",
        ],
        ["Total interest", f"{plan.total_interest_minor / 100:,.2f} {plan.currency}"],
    ]
    if plan.total_fees_minor:
        summary_rows.append(
            ["Total fees", f"{plan.total_fees_minor / 100:,.2f} {plan.currency}"]
        )
    summary_rows.append(
        ["Total paid", f"{plan.total_paid_minor / 100:,.2f} {plan.currency}"]
    )

    summary = Table(summary_rows, colWidths=[45 * mm, 60 * mm])
    summary.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#656c81")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ]
        )
    )
    story.append(summary)
    story.append(Spacer(1, 6 * mm))

    # A plan that cannot finish is the most important thing on the page.
    if not plan.is_complete:
        story.append(
            Paragraph(
                "<b>At these payments the balance never clears</b> — the interest is more "
                "than the payments cover.",
                styles["BodyText"],
            )
        )
        story.append(Spacer(1, 4 * mm))

    header = ["Month", "Debt", "Payment", "Interest", "Fees", "Principal", "Balance"]
    rows = [header]
    for month in plan.months:
        for payment in month.payments:
            rows.append(
                [
                    month.as_of.strftime("%b %Y"),
                    payment.name[:22],
                    f"{payment.payment_minor / 100:,.2f}",
                    f"{payment.interest_minor / 100:,.2f}",
                    f"{payment.fee_minor / 100:,.2f}",
                    f"{payment.principal_minor / 100:,.2f}",
                    f"{payment.balance_after_minor / 100:,.2f}",
                ]
            )

    table = Table(rows, repeatRows=1, colWidths=[20 * mm, 34 * mm, 22 * mm, 21 * mm, 17 * mm, 22 * mm, 24 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f2f6")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#3d4356")),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#c9cdd8")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafbfc")]),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(table)

    doc.build(story)
    return buffer.getvalue()
