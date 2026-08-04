"""Life events, and the compiler that reduces them to engine primitives.

The product speaks in life events — "we're having a baby", "I'm going down to
four days a week", "we want to buy in two years". The engine speaks in six
primitives (see `engine.CompiledEvent`). This module is the translation layer,
and keeping it a *translation* rather than a set of engine special-cases is
what stops the projection arithmetic from growing a branch per life decision.

Each kind declares the parameters it accepts and compiles to one or more
`CompiledEvent`s. Two properties are enforced for every kind:

**Compilation needs the position.** "I lose my job" is not a number until you
know what the job pays. Several kinds are proportional to the household's
current income or expenses, so the compiler receives the `FinancialPosition`
and derives from it rather than making the user restate what the app already
knows.

**Gross in, net out.** Users quote salaries gross; the engine works in what
actually lands. Every income-side parameter named `gross` is converted using
the assumption set's effective tax rate exactly once, here, so no downstream
code has to remember to.

Unknown parameters are rejected rather than ignored. A typo in a scenario's
parameters that silently does nothing is worse than an error, because the user
sees a projection that looks like it accounted for something it did not.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .calculators import level_payment_minor
from .engine import CompiledEvent, DebtPosition, EconomicAssumptions, FinancialPosition


class EventKind:
    """The fifteen life events, as plain strings.

    Deliberately not a Django `TextChoices`: this module has to be importable
    and testable without the app registry standing up. `models.py` mirrors
    these into choices, and a test pins the two lists together.
    """

    HOME_PURCHASE = "home_purchase"
    MORTGAGE = "mortgage"
    VEHICLE_PURCHASE = "vehicle_purchase"
    JOB_CHANGE = "job_change"
    SALARY_INCREASE = "salary_increase"
    JOB_LOSS = "job_loss"
    HOURS_REDUCTION = "hours_reduction"
    DEBT_PAYOFF = "debt_payoff"
    INVEST_MORE = "invest_more"
    NEW_CHILD = "new_child"
    RETIREMENT = "retirement"
    EDUCATION = "education"
    RELOCATION = "relocation"
    BUSINESS_START = "business_start"
    ONE_TIME_PURCHASE = "one_time_purchase"

    # --- household events (Phase 3) --------------------------------------
    # Added to the same compile target rather than to the engine: a marriage
    # and a mortgage are wholly different life experiences and exactly the
    # same six primitives, which is the point of having a compiler at all.
    MARRIAGE = "marriage"
    PARENTAL_LEAVE = "parental_leave"
    SEPARATION = "separation"
    CARING_FOR_PARENT = "caring_for_parent"
    INHERITANCE = "inheritance"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return tuple(
            value for name, value in vars(cls).items() if not name.startswith("_") and isinstance(value, str)
        )


#: Human labels, used for choices and for the `label` on a compiled event.
EVENT_LABELS: dict[str, str] = {
    EventKind.HOME_PURCHASE: "Buying a home",
    EventKind.MORTGAGE: "Taking a mortgage",
    EventKind.VEHICLE_PURCHASE: "Buying a vehicle",
    EventKind.JOB_CHANGE: "Changing jobs",
    EventKind.SALARY_INCREASE: "A pay rise",
    EventKind.JOB_LOSS: "Losing employment",
    EventKind.HOURS_REDUCTION: "Reducing working hours",
    EventKind.DEBT_PAYOFF: "Paying off debt",
    EventKind.INVEST_MORE: "Investing more",
    EventKind.NEW_CHILD: "A new child",
    EventKind.RETIREMENT: "Retiring",
    EventKind.EDUCATION: "Education costs",
    EventKind.RELOCATION: "Relocating",
    EventKind.BUSINESS_START: "Starting a business",
    EventKind.ONE_TIME_PURCHASE: "A large one-off purchase",
    EventKind.MARRIAGE: "Getting married",
    EventKind.PARENTAL_LEAVE: "Parental leave",
    EventKind.SEPARATION: "Separating or divorcing",
    EventKind.CARING_FOR_PARENT: "Caring for a parent",
    EventKind.INHERITANCE: "An inheritance",
}


class EventParamError(ValueError):
    """A life event whose parameters cannot describe a real decision."""


@dataclass(frozen=True)
class ParamSpec:
    name: str
    required: bool = False
    default: object = 0
    kind: type = int


#: What each event accepts. Serialisers render this straight into API docs, so
#: the schema and the compiler cannot drift apart.
EVENT_PARAMS: dict[str, tuple[ParamSpec, ...]] = {
    EventKind.HOME_PURCHASE: (
        ParamSpec("price_minor", required=True),
        ParamSpec("deposit_minor"),
        ParamSpec("annual_rate", default=0.0, kind=float),
        ParamSpec("term_years", default=25),
        ParamSpec("monthly_running_costs_minor"),
        ParamSpec("annual_growth", default=None, kind=float),
    ),
    EventKind.MORTGAGE: (
        ParamSpec("principal_minor", required=True),
        ParamSpec("annual_rate", default=0.0, kind=float),
        ParamSpec("term_years", default=25),
        ParamSpec("cash_received", default=1, kind=int),
    ),
    EventKind.VEHICLE_PURCHASE: (
        ParamSpec("price_minor", required=True),
        ParamSpec("deposit_minor"),
        ParamSpec("annual_rate", default=0.0, kind=float),
        ParamSpec("term_years", default=5),
        ParamSpec("monthly_running_costs_minor"),
        ParamSpec("annual_depreciation", default=0.15, kind=float),
    ),
    EventKind.JOB_CHANGE: (
        ParamSpec("monthly_gross_delta_minor", required=True),
        ParamSpec("gap_months"),
    ),
    EventKind.SALARY_INCREASE: (ParamSpec("monthly_gross_increase_minor", required=True),),
    EventKind.JOB_LOSS: (
        ParamSpec("months_without_work", required=True),
        ParamSpec("monthly_replacement_income_minor"),
        ParamSpec("severance_minor"),
    ),
    EventKind.HOURS_REDUCTION: (ParamSpec("retained_fraction", required=True, kind=float),),
    EventKind.DEBT_PAYOFF: (
        ParamSpec("debt_label", default="", kind=str),
        ParamSpec("amount_minor"),
    ),
    EventKind.INVEST_MORE: (ParamSpec("monthly_amount_minor", required=True),),
    EventKind.NEW_CHILD: (
        ParamSpec("monthly_cost_minor", required=True),
        ParamSpec("one_off_cost_minor"),
        ParamSpec("support_years", default=18),
    ),
    EventKind.RETIREMENT: (
        ParamSpec("monthly_pension_income_minor"),
        ParamSpec("monthly_drawdown_minor"),
        ParamSpec("expense_change_minor"),
    ),
    EventKind.EDUCATION: (
        ParamSpec("monthly_cost_minor", required=True),
        ParamSpec("duration_months", required=True),
        ParamSpec("upfront_minor"),
    ),
    EventKind.RELOCATION: (
        ParamSpec("moving_cost_minor"),
        ParamSpec("monthly_expense_delta_minor"),
        ParamSpec("monthly_gross_income_delta_minor"),
    ),
    EventKind.BUSINESS_START: (
        ParamSpec("startup_cost_minor", required=True),
        ParamSpec("monthly_cost_minor"),
        ParamSpec("monthly_revenue_minor"),
        ParamSpec("ramp_months", default=0),
    ),
    EventKind.ONE_TIME_PURCHASE: (
        ParamSpec("amount_minor", required=True),
        ParamSpec("annual_rate", default=0.0, kind=float),
        ParamSpec("term_months"),
    ),
    EventKind.MARRIAGE: (
        ParamSpec("wedding_cost_minor"),
        ParamSpec("partner_monthly_gross_income_minor"),
        ParamSpec("shared_monthly_saving_minor"),
    ),
    EventKind.PARENTAL_LEAVE: (
        ParamSpec("months", required=True),
        ParamSpec("paid_fraction", default=0.0, kind=float),
    ),
    EventKind.SEPARATION: (
        ParamSpec("retained_income_fraction", default=1.0, kind=float),
        ParamSpec("retained_assets_fraction", default=0.5, kind=float),
        ParamSpec("one_off_cost_minor"),
        ParamSpec("monthly_expense_delta_minor"),
    ),
    EventKind.CARING_FOR_PARENT: (
        ParamSpec("monthly_cost_minor", required=True),
        ParamSpec("years", default=5),
        ParamSpec("income_reduction_fraction", default=0.0, kind=float),
    ),
    EventKind.INHERITANCE: (
        ParamSpec("amount_minor", required=True),
        ParamSpec("invested_fraction", default=1.0, kind=float),
    ),
}


def validate_params(kind: str, params: dict) -> dict:
    """Coerce and check one event's parameters against its spec.

    Rejects unknown keys. A misspelled parameter that is silently dropped
    produces a projection which looks like it modelled something it ignored,
    and the user has no way to tell.
    """
    if kind not in EVENT_PARAMS:
        raise EventParamError(f"unknown event kind: {kind!r}")
    specs = {spec.name: spec for spec in EVENT_PARAMS[kind]}
    unknown = set(params) - set(specs)
    if unknown:
        raise EventParamError(f"{kind}: unknown parameter(s) {sorted(unknown)}")

    resolved: dict = {}
    for name, spec in specs.items():
        if name not in params:
            if spec.required:
                raise EventParamError(f"{kind}: {name} is required")
            resolved[name] = spec.default
            continue
        value = params[name]
        if value is None:
            resolved[name] = spec.default
            continue
        try:
            resolved[name] = spec.kind(value)
        except (TypeError, ValueError) as exc:
            raise EventParamError(f"{kind}: {name} must be {spec.kind.__name__}") from exc
    return resolved


def _net(gross_minor: int, assumptions: EconomicAssumptions) -> int:
    """Gross to net, applied exactly once and only here."""
    return round(gross_minor * (1 - assumptions.effective_tax_rate))


def _financed(
    *, price_minor: int, deposit_minor: int, annual_rate: float, months: int, label: str
) -> DebtPosition | None:
    borrowed = price_minor - deposit_minor
    if borrowed <= 0:
        return None
    payment = level_payment_minor(borrowed, annual_rate, months)
    return DebtPosition(
        label=label, balance_minor=borrowed, annual_rate=annual_rate, monthly_payment_minor=payment
    )


# ---------------------------------------------------------------------------
# per-kind compilers
# ---------------------------------------------------------------------------
def _home_purchase(p, start, position, assumptions, label):
    months = max(1, int(p["term_years"]) * 12)
    debt = _financed(
        price_minor=p["price_minor"],
        deposit_minor=p["deposit_minor"],
        annual_rate=p["annual_rate"],
        months=months,
        label=f"{label} mortgage",
    )
    return [
        CompiledEvent(
            label=label,
            start_month=start,
            one_off_cash_minor=-p["deposit_minor"],
            asset_delta_minor=p["price_minor"],
            asset_annual_growth=p["annual_growth"],
            new_debt=debt,
            monthly_expense_delta_minor=p["monthly_running_costs_minor"],
        )
    ]


def _mortgage(p, start, position, assumptions, label):
    months = max(1, int(p["term_years"]) * 12)
    payment = level_payment_minor(p["principal_minor"], p["annual_rate"], months)
    return [
        CompiledEvent(
            label=label,
            start_month=start,
            # Borrowing without buying puts cash in hand — a remortgage or an
            # equity release. Paired with a purchase, the caller sets
            # cash_received to 0 so the money is not counted twice.
            one_off_cash_minor=p["principal_minor"] if p["cash_received"] else 0,
            new_debt=DebtPosition(
                label=label,
                balance_minor=p["principal_minor"],
                annual_rate=p["annual_rate"],
                monthly_payment_minor=payment,
            ),
        )
    ]


def _vehicle_purchase(p, start, position, assumptions, label):
    months = max(1, int(p["term_years"]) * 12)
    debt = _financed(
        price_minor=p["price_minor"],
        deposit_minor=p["deposit_minor"],
        annual_rate=p["annual_rate"],
        months=months,
        label=f"{label} finance",
    )
    return [
        CompiledEvent(
            label=label,
            start_month=start,
            one_off_cash_minor=-p["deposit_minor"],
            asset_delta_minor=p["price_minor"],
            # Negative growth: a vehicle is the one asset most people are
            # certain about, and it is certainly going down.
            asset_annual_growth=-abs(p["annual_depreciation"]),
            new_debt=debt,
            monthly_expense_delta_minor=p["monthly_running_costs_minor"],
        )
    ]


def _job_change(p, start, position, assumptions, label):
    events = [
        CompiledEvent(
            label=label,
            start_month=start + int(p["gap_months"]),
            monthly_income_delta_minor=_net(p["monthly_gross_delta_minor"], assumptions),
        )
    ]
    gap = int(p["gap_months"])
    if gap:
        # The gap is unpaid: income drops to zero until the new job starts.
        events.append(
            CompiledEvent(
                label=f"{label} (gap)",
                start_month=start,
                end_month=start + gap - 1,
                monthly_income_delta_minor=-position.monthly_net_income_minor,
            )
        )
    return events


def _salary_increase(p, start, position, assumptions, label):
    return [
        CompiledEvent(
            label=label,
            start_month=start,
            monthly_income_delta_minor=_net(p["monthly_gross_increase_minor"], assumptions),
        )
    ]


def _job_loss(p, start, position, assumptions, label):
    duration = max(1, int(p["months_without_work"]))
    lost = position.monthly_net_income_minor - p["monthly_replacement_income_minor"]
    events = [
        CompiledEvent(
            label=label,
            start_month=start,
            end_month=start + duration - 1,
            monthly_income_delta_minor=-lost,
        )
    ]
    if p["severance_minor"]:
        events.append(
            CompiledEvent(
                label=f"{label} (severance)",
                start_month=start,
                one_off_cash_minor=p["severance_minor"],
            )
        )
    return events


def _hours_reduction(p, start, position, assumptions, label):
    retained = float(p["retained_fraction"])
    if not 0 < retained <= 1:
        raise EventParamError("retained_fraction must be in (0, 1]")
    lost = round(position.monthly_net_income_minor * (1 - retained))
    return [CompiledEvent(label=label, start_month=start, monthly_income_delta_minor=-lost)]


def _debt_payoff(p, start, position, assumptions, label):
    if p["debt_label"]:
        return [CompiledEvent(label=label, start_month=start, clears_debt_labels=(str(p["debt_label"]),))]
    return [CompiledEvent(label=label, start_month=start, one_off_cash_minor=-p["amount_minor"])]


def _invest_more(p, start, position, assumptions, label):
    return [
        CompiledEvent(
            label=label, start_month=start, monthly_investment_delta_minor=p["monthly_amount_minor"]
        )
    ]


def _new_child(p, start, position, assumptions, label):
    years = max(1, int(p["support_years"]))
    events = [
        CompiledEvent(
            label=label,
            start_month=start,
            end_month=start + years * 12 - 1,
            monthly_expense_delta_minor=p["monthly_cost_minor"],
        )
    ]
    if p["one_off_cost_minor"]:
        events.append(
            CompiledEvent(
                label=f"{label} (setup)",
                start_month=start,
                one_off_cash_minor=-p["one_off_cost_minor"],
            )
        )
    return events


def _retirement(p, start, position, assumptions, label):
    return [
        CompiledEvent(
            label=label,
            start_month=start,
            # Earned income stops; pension replaces part of it. Modelled as a
            # delta against the current net income so the user does not have to
            # restate what they already earn.
            monthly_income_delta_minor=(
                p["monthly_pension_income_minor"] - position.monthly_net_income_minor
            ),
            monthly_expense_delta_minor=p["expense_change_minor"],
            # A drawdown is a negative contribution: money leaving the pot.
            monthly_investment_delta_minor=-p["monthly_drawdown_minor"],
        )
    ]


def _education(p, start, position, assumptions, label):
    duration = max(1, int(p["duration_months"]))
    events = [
        CompiledEvent(
            label=label,
            start_month=start,
            end_month=start + duration - 1,
            monthly_expense_delta_minor=p["monthly_cost_minor"],
        )
    ]
    if p["upfront_minor"]:
        events.append(
            CompiledEvent(
                label=f"{label} (upfront)",
                start_month=start,
                one_off_cash_minor=-p["upfront_minor"],
            )
        )
    return events


def _relocation(p, start, position, assumptions, label):
    events = [
        CompiledEvent(
            label=label,
            start_month=start,
            monthly_expense_delta_minor=p["monthly_expense_delta_minor"],
            monthly_income_delta_minor=_net(p["monthly_gross_income_delta_minor"], assumptions),
        )
    ]
    if p["moving_cost_minor"]:
        events.append(
            CompiledEvent(
                label=f"{label} (move)",
                start_month=start,
                one_off_cash_minor=-p["moving_cost_minor"],
            )
        )
    return events


def _business_start(p, start, position, assumptions, label):
    ramp = max(0, int(p["ramp_months"]))
    events = [
        CompiledEvent(
            label=f"{label} (setup)", start_month=start, one_off_cash_minor=-p["startup_cost_minor"]
        ),
        CompiledEvent(
            label=f"{label} (costs)",
            start_month=start,
            monthly_expense_delta_minor=p["monthly_cost_minor"],
        ),
    ]
    if p["monthly_revenue_minor"]:
        # Revenue only after the ramp. Modelling it from day one is the single
        # most flattering thing a business projection can do, and the most
        # common reason one is wrong.
        events.append(
            CompiledEvent(
                label=f"{label} (revenue)",
                start_month=start + ramp,
                monthly_income_delta_minor=_net(p["monthly_revenue_minor"], assumptions),
            )
        )
    return events


def _one_time_purchase(p, start, position, assumptions, label):
    term = int(p["term_months"])
    if term:
        payment = level_payment_minor(p["amount_minor"], p["annual_rate"], term)
        return [
            CompiledEvent(
                label=label,
                start_month=start,
                new_debt=DebtPosition(
                    label=label,
                    balance_minor=p["amount_minor"],
                    annual_rate=p["annual_rate"],
                    monthly_payment_minor=payment,
                ),
            )
        ]
    return [CompiledEvent(label=label, start_month=start, one_off_cash_minor=-p["amount_minor"])]


# ---------------------------------------------------------------------------
# household compilers (Phase 3)
# ---------------------------------------------------------------------------
def _marriage(p, start, position, assumptions, label):
    """Two incomes, one household, and a party.

    Modelled as a permanent income addition rather than a merged position,
    because the projection is run from *this* household's ledger and the
    partner's balance sheet is not in it. The income is the part that changes
    this household's arithmetic; saying more than that would be inventing
    numbers about somebody the product has never seen.
    """
    events = [
        CompiledEvent(
            label=label,
            start_month=start,
            monthly_income_delta_minor=_net(p["partner_monthly_gross_income_minor"], assumptions),
            monthly_investment_delta_minor=p["shared_monthly_saving_minor"],
        )
    ]
    if p["wedding_cost_minor"]:
        events.append(
            CompiledEvent(
                label=f"{label} (the day itself)",
                start_month=start,
                one_off_cash_minor=-p["wedding_cost_minor"],
            )
        )
    return events


def _parental_leave(p, start, position, assumptions, label):
    """A window of reduced income, ending on a knowable date.

    `paid_fraction` is what statutory or employer pay replaces. Defaulting it
    to zero is the pessimistic reading and the right one: entitlement varies
    enormously and a projection that assumes generous cover is the one that
    surprises people at the worst possible moment.
    """
    months = max(1, int(p["months"]))
    retained = min(1.0, max(0.0, float(p["paid_fraction"])))
    lost = round(position.monthly_net_income_minor * (1 - retained))
    return [
        CompiledEvent(
            label=label,
            start_month=start,
            end_month=start + months - 1,
            monthly_income_delta_minor=-lost,
        )
    ]


def _separation(p, start, position, assumptions, label):
    """The event nobody wants modelled and everybody wants answered.

    Assets are split by fraction and applied as a one-off reduction; income
    changes to the share retained. It is a blunt model and it is stated as one
    — the legal reality is negotiated, not arithmetic — but a household asking
    "could I manage on my own" deserves a number rather than a silence.
    """
    income_kept = min(1.0, max(0.0, float(p["retained_income_fraction"])))
    assets_kept = min(1.0, max(0.0, float(p["retained_assets_fraction"])))
    events = [
        CompiledEvent(
            label=label,
            start_month=start,
            monthly_income_delta_minor=-round(position.monthly_net_income_minor * (1 - income_kept)),
            monthly_expense_delta_minor=p["monthly_expense_delta_minor"],
            one_off_cash_minor=-round(position.liquid_minor * (1 - assets_kept)) - p["one_off_cost_minor"],
        )
    ]
    return events


def _caring_for_parent(p, start, position, assumptions, label):
    """Cost, and often a quieter cost: the hours it takes out of earning."""
    years = max(1, int(p["years"]))
    reduction = min(1.0, max(0.0, float(p["income_reduction_fraction"])))
    return [
        CompiledEvent(
            label=label,
            start_month=start,
            end_month=start + years * 12 - 1,
            monthly_expense_delta_minor=p["monthly_cost_minor"],
            monthly_income_delta_minor=-round(position.monthly_net_income_minor * reduction),
        )
    ]


def _inheritance(p, start, position, assumptions, label):
    """A lump sum, split between cash and invested.

    No tax is applied. Inheritance tax varies by jurisdiction, relationship and
    estate structure to a degree this product cannot responsibly guess at, so
    the amount is taken as *received* and the assumption says so.
    """
    invested = min(1.0, max(0.0, float(p["invested_fraction"])))
    to_investments = round(p["amount_minor"] * invested)
    to_cash = p["amount_minor"] - to_investments
    events = [
        CompiledEvent(
            label=label,
            start_month=start,
            one_off_cash_minor=to_cash,
        )
    ]
    if to_investments:
        events.append(
            CompiledEvent(
                label=f"{label} (invested)",
                start_month=start,
                asset_delta_minor=to_investments,
                asset_annual_growth=assumptions.annual_investment_return,
            )
        )
    return events


_COMPILERS: dict[str, Callable] = {
    EventKind.HOME_PURCHASE: _home_purchase,
    EventKind.MORTGAGE: _mortgage,
    EventKind.VEHICLE_PURCHASE: _vehicle_purchase,
    EventKind.JOB_CHANGE: _job_change,
    EventKind.SALARY_INCREASE: _salary_increase,
    EventKind.JOB_LOSS: _job_loss,
    EventKind.HOURS_REDUCTION: _hours_reduction,
    EventKind.DEBT_PAYOFF: _debt_payoff,
    EventKind.INVEST_MORE: _invest_more,
    EventKind.NEW_CHILD: _new_child,
    EventKind.RETIREMENT: _retirement,
    EventKind.EDUCATION: _education,
    EventKind.RELOCATION: _relocation,
    EventKind.BUSINESS_START: _business_start,
    EventKind.ONE_TIME_PURCHASE: _one_time_purchase,
    EventKind.MARRIAGE: _marriage,
    EventKind.PARENTAL_LEAVE: _parental_leave,
    EventKind.SEPARATION: _separation,
    EventKind.CARING_FOR_PARENT: _caring_for_parent,
    EventKind.INHERITANCE: _inheritance,
}


def compile_event(
    *,
    kind: str,
    start_month: int,
    params: dict,
    position: FinancialPosition,
    assumptions: EconomicAssumptions,
    label: str = "",
) -> list[CompiledEvent]:
    """Reduce one life event to the primitives the engine understands."""
    if start_month < 1:
        raise EventParamError("start_month is 1-based; the first projected month is 1")
    resolved = validate_params(kind, params)
    compiler = _COMPILERS[kind]
    return compiler(resolved, start_month, position, assumptions, label or EVENT_LABELS[kind])
