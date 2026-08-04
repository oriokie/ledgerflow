"""The calculator library — closed-form financial arithmetic, no database.

Every function here is pure: same inputs, same outputs, no ambient tenant, no
queries. That is deliberate and load-bearing. These are the primitives the
projection engine, the scenario comparison and eventually the AI reasoning
layer all quote from, so they have to be provable in isolation — a projection
that disagrees with the mortgage calculator on the same loan is a bug the user
will find before we do.

Three disciplines, inherited from `apps.common.money` and not negotiable:

**Money is integer minor units, everywhere.** Never a float, never a display
string. Floats accumulate error over 480 monthly iterations in a way that shows
up as a balance that does not quite reach zero, and "your mortgage ends owing
you 3 cents" destroys trust in every other number on the page.

**Rates are floats, and they are always annual and nominal unless the parameter
says otherwise.** Mixing monthly and annual rates is the single most common
error in this domain; the names carry the unit so a caller cannot get it wrong
silently.

**The last payment settles the balance exactly.** Interest is rounded to minor
units each period, exactly as a real lender does it, so a schedule accumulates
rounding drift of a few cents. Rather than hide that, the final instalment
absorbs it — which is also what a real lender does. The invariant that falls
out of it is the one worth testing: the principal portions of a schedule sum to
the original principal, to the cent.

Nothing here gives advice. A calculator says "this loan costs X"; deciding
whether X is wise belongs to a layer that knows the person.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: Longest horizon any projection will run. Forty years is the product's stated
#: ceiling, and it is also roughly where "projection" stops meaning anything —
#: compounding a return assumption past it produces numbers with the shape of
#: precision and none of the substance.
MAX_HORIZON_MONTHS = 480

#: Guard rails on rate inputs. These are not opinions about good rates; they
#: are the range outside which the arithmetic stops describing a real product
#: and starts describing a typo. -50%/yr catches a sign error, 200%/yr catches
#: a percentage passed where a fraction belongs (a very common caller mistake).
MIN_ANNUAL_RATE = -0.5
MAX_ANNUAL_RATE = 2.0


class CalculatorError(ValueError):
    """A calculator input that cannot describe a real financial product."""


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------
def monthly_rate(annual_rate: float, *, compounding: str = "monthly") -> float:
    """Convert an annual rate to the equivalent monthly rate.

    Two conventions exist and they disagree, so the caller picks:

    * ``"monthly"`` — nominal, divided by twelve. What lenders quote and what
      every amortisation schedule in the world actually uses. A 12% mortgage
      charges 1% a month.
    * ``"effective"`` — the twelfth root, so twelve months compound back to
      exactly the annual figure. Correct for investment returns, where a
      "7% annual return" means the year ends 7% up, not 7.23%.

    Using the wrong one is a real error with a small signature: over thirty
    years the difference on a return assumption is tens of percent of the final
    pot, which is why the two call sites here never share a default.
    """
    _validate_rate(annual_rate)
    if compounding == "monthly":
        return annual_rate / 12
    if compounding == "effective":
        return (1 + annual_rate) ** (1 / 12) - 1
    raise CalculatorError(f"unknown compounding convention: {compounding!r}")


def _validate_rate(annual_rate: float) -> None:
    if not MIN_ANNUAL_RATE <= annual_rate <= MAX_ANNUAL_RATE:
        raise CalculatorError(
            f"annual rate {annual_rate} is outside [{MIN_ANNUAL_RATE}, {MAX_ANNUAL_RATE}] — "
            "rates are fractions (0.07 for 7%), not percentages"
        )


def _validate_months(months: int) -> None:
    if months <= 0:
        raise CalculatorError("term must be at least one month")
    if months > MAX_HORIZON_MONTHS:
        raise CalculatorError(f"term of {months} months exceeds the {MAX_HORIZON_MONTHS}-month ceiling")


def _validate_amount(amount_minor: int, label: str) -> None:
    if not isinstance(amount_minor, int):
        raise CalculatorError(f"{label} must be an int in minor units, got {type(amount_minor).__name__}")
    if amount_minor < 0:
        raise CalculatorError(f"{label} cannot be negative")


def level_payment_minor(principal_minor: int, annual_rate: float, months: int) -> int:
    """The level instalment that amortises `principal` over `months`.

    The standard annuity formula, with the zero-rate case handled separately
    because the general form divides by the rate. An interest-free instalment
    plan is a real product, not an edge case to reject.
    """
    _validate_amount(principal_minor, "principal")
    _validate_months(months)
    i = monthly_rate(annual_rate)
    if principal_minor == 0:
        return 0
    if i == 0:
        return math.ceil(principal_minor / months)
    payment = principal_minor * i / (1 - (1 + i) ** -months)
    # Ceil rather than round: a payment rounded down can leave the schedule
    # unable to clear the balance within the term, which reads to the user as
    # the calculator inventing an extra month.
    return math.ceil(payment)


# ---------------------------------------------------------------------------
# amortisation — the shared core of the mortgage and loan calculators
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AmortisationPeriod:
    month: int
    payment_minor: int
    interest_minor: int
    principal_minor: int
    balance_minor: int


@dataclass(frozen=True)
class AmortisationResult:
    principal_minor: int
    annual_rate: float
    months: int
    payment_minor: int
    total_paid_minor: int
    total_interest_minor: int
    #: Months actually taken. Shorter than `months` when extra payments clear
    #: the balance early — the headline result of any overpayment question.
    actual_months: int
    schedule: list[AmortisationPeriod] = field(default_factory=list)

    @property
    def interest_share(self) -> float:
        """Fraction of everything paid that was interest. The number that
        answers "what is this loan actually costing me" better than a rate."""
        return self.total_interest_minor / self.total_paid_minor if self.total_paid_minor else 0.0


def amortise(
    *,
    principal_minor: int,
    annual_rate: float,
    months: int,
    extra_monthly_minor: int = 0,
    payment_minor: int | None = None,
    with_schedule: bool = True,
) -> AmortisationResult:
    """Amortise a loan, optionally with a constant overpayment.

    Interest each period is computed on the opening balance and rounded to
    minor units, which is how lenders do it and therefore how the user's
    statement will read. The final instalment is whatever clears the balance,
    absorbing the rounding drift that accumulates over the term.

    `extra_monthly_minor` is applied entirely to principal, which is the
    generous-but-standard reading of an overpayment; the resulting `actual_months`
    is the answer to "when would this be gone if I paid a bit more".

    `payment_minor` overrides the computed instalment, which is what the
    projection engine needs for debts the user already holds: the question
    there is not "what should this cost" but "given what I actually pay, when
    is it gone?" — and the answer is sometimes *never*, which a derived level
    payment can never express. With an override, `months` becomes a ceiling on
    the search rather than the term.
    """
    _validate_amount(principal_minor, "principal")
    _validate_amount(extra_monthly_minor, "extra monthly payment")
    _validate_months(months)

    if payment_minor is None:
        base_payment = level_payment_minor(principal_minor, annual_rate, months)
    else:
        _validate_amount(payment_minor, "payment")
        base_payment = payment_minor
    i = monthly_rate(annual_rate)

    balance = principal_minor
    total_interest = 0
    total_paid = 0
    schedule: list[AmortisationPeriod] = []
    month = 0

    while balance > 0 and month < MAX_HORIZON_MONTHS:
        month += 1
        interest = round(balance * i)
        # A payment that does not cover the interest never retires the debt.
        # Report that as an error rather than looping to the horizon cap and
        # returning a schedule that quietly means "never".
        scheduled = base_payment + extra_monthly_minor
        if scheduled <= interest and balance + interest > scheduled:
            raise CalculatorError(
                f"a payment of {scheduled} does not cover the {interest} of interest accruing "
                f"in month {month} — this balance would grow forever"
            )
        principal_part = scheduled - interest
        if principal_part >= balance:
            # Final instalment: pay exactly what is left, plus that month's
            # interest. This is what makes the principal column sum exactly.
            principal_part = balance
            scheduled = balance + interest
        balance -= principal_part
        total_interest += interest
        total_paid += scheduled
        if with_schedule:
            schedule.append(
                AmortisationPeriod(
                    month=month,
                    payment_minor=scheduled,
                    interest_minor=interest,
                    principal_minor=principal_part,
                    balance_minor=balance,
                )
            )

    return AmortisationResult(
        principal_minor=principal_minor,
        annual_rate=annual_rate,
        months=months,
        payment_minor=base_payment,
        total_paid_minor=total_paid,
        total_interest_minor=total_interest,
        actual_months=month,
        schedule=schedule,
    )


# ---------------------------------------------------------------------------
# mortgage
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MortgageResult:
    property_price_minor: int
    deposit_minor: int
    loan_minor: int
    loan_to_value: float
    annual_rate: float
    months: int
    monthly_payment_minor: int
    #: Payment including the recurring ownership costs a mortgage quote omits
    #: and a household budget cannot.
    monthly_cost_minor: int
    monthly_tax_minor: int
    monthly_insurance_minor: int
    total_interest_minor: int
    total_paid_minor: int
    amortisation: AmortisationResult
    assumptions: list[str] = field(default_factory=list)


def mortgage(
    *,
    property_price_minor: int,
    deposit_minor: int,
    annual_rate: float,
    years: int,
    annual_tax_minor: int = 0,
    annual_insurance_minor: int = 0,
    extra_monthly_minor: int = 0,
    with_schedule: bool = False,
) -> MortgageResult:
    """Price a mortgage, including the costs the advertised payment leaves out.

    The distinction between `monthly_payment_minor` and `monthly_cost_minor`
    is the whole point of this function existing separately from `loan`. A
    lender quotes the first; the household pays the second. Affordability
    answered off the quoted payment is the single most common way people end
    up house-poor, so property tax and insurance are first-class inputs here
    rather than an afterthought the caller is trusted to remember.
    """
    _validate_amount(property_price_minor, "property price")
    _validate_amount(deposit_minor, "deposit")
    _validate_amount(annual_tax_minor, "annual tax")
    _validate_amount(annual_insurance_minor, "annual insurance")
    if deposit_minor > property_price_minor:
        raise CalculatorError("deposit exceeds the property price")

    loan_minor = property_price_minor - deposit_minor
    months = years * 12
    schedule = amortise(
        principal_minor=loan_minor,
        annual_rate=annual_rate,
        months=months,
        extra_monthly_minor=extra_monthly_minor,
        with_schedule=with_schedule,
    )

    monthly_tax = round(annual_tax_minor / 12)
    monthly_insurance = round(annual_insurance_minor / 12)
    ltv = loan_minor / property_price_minor if property_price_minor else 0.0

    assumptions = [
        f"Rate of {annual_rate:.2%} held fixed for the full {years}-year term.",
        "Nominal rate divided by twelve, the convention lenders amortise on.",
    ]
    if annual_tax_minor or annual_insurance_minor:
        assumptions.append(
            "Tax and insurance held flat in today's money — both usually rise with the property."
        )
    else:
        assumptions.append(
            "No property tax or insurance included: the monthly cost of ownership is higher than this payment."
        )
    if extra_monthly_minor:
        assumptions.append("Overpayments applied wholly to principal, with no early-repayment charge.")

    return MortgageResult(
        property_price_minor=property_price_minor,
        deposit_minor=deposit_minor,
        loan_minor=loan_minor,
        loan_to_value=round(ltv, 4),
        annual_rate=annual_rate,
        months=months,
        monthly_payment_minor=schedule.payment_minor,
        monthly_cost_minor=schedule.payment_minor + monthly_tax + monthly_insurance,
        monthly_tax_minor=monthly_tax,
        monthly_insurance_minor=monthly_insurance,
        total_interest_minor=schedule.total_interest_minor,
        total_paid_minor=schedule.total_paid_minor,
        amortisation=schedule,
        assumptions=assumptions,
    )


# ---------------------------------------------------------------------------
# generic loan
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LoanResult:
    principal_minor: int
    annual_rate: float
    months: int
    monthly_payment_minor: int
    total_interest_minor: int
    total_paid_minor: int
    actual_months: int
    #: Interest saved versus the same loan with no overpayment. Zero when no
    #: overpayment was modelled.
    interest_saved_minor: int
    months_saved: int
    amortisation: AmortisationResult
    assumptions: list[str] = field(default_factory=list)


def loan(
    *,
    principal_minor: int,
    annual_rate: float,
    months: int,
    extra_monthly_minor: int = 0,
    with_schedule: bool = False,
) -> LoanResult:
    """Price any instalment loan, and quantify what overpaying would buy.

    When `extra_monthly_minor` is set the function runs the loan twice — once
    plain, once with the overpayment — so the saving is measured rather than
    estimated. Same discipline as the scenario engine: both legs go through the
    same arithmetic, so a bug cannot flatter the comparison.
    """
    plain = amortise(
        principal_minor=principal_minor,
        annual_rate=annual_rate,
        months=months,
        with_schedule=with_schedule or bool(extra_monthly_minor) is False,
    )
    if extra_monthly_minor:
        boosted = amortise(
            principal_minor=principal_minor,
            annual_rate=annual_rate,
            months=months,
            extra_monthly_minor=extra_monthly_minor,
            with_schedule=with_schedule,
        )
        chosen = boosted
        interest_saved = plain.total_interest_minor - boosted.total_interest_minor
        months_saved = plain.actual_months - boosted.actual_months
    else:
        chosen = plain
        interest_saved = 0
        months_saved = 0

    assumptions = [
        f"Rate of {annual_rate:.2%} fixed for the term; nominal, divided by twelve.",
        "Payments made in full and on time, every month.",
    ]
    if extra_monthly_minor:
        assumptions.append("The comparison re-runs the whole loan rather than adjusting the baseline result.")

    return LoanResult(
        principal_minor=principal_minor,
        annual_rate=annual_rate,
        months=months,
        monthly_payment_minor=chosen.payment_minor,
        total_interest_minor=chosen.total_interest_minor,
        total_paid_minor=chosen.total_paid_minor,
        actual_months=chosen.actual_months,
        interest_saved_minor=interest_saved,
        months_saved=months_saved,
        amortisation=chosen,
        assumptions=assumptions,
    )


# ---------------------------------------------------------------------------
# investment growth
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GrowthPoint:
    month: int
    contributed_minor: int
    balance_minor: int
    #: Balance minus everything paid in — the part that is growth rather than
    #: saving. Shown because people routinely credit returns for what was
    #: actually their own discipline.
    growth_minor: int


@dataclass(frozen=True)
class InvestmentGrowthResult:
    initial_minor: int
    monthly_contribution_minor: int
    annual_return: float
    months: int
    final_balance_minor: int
    total_contributed_minor: int
    total_growth_minor: int
    #: The same projection with inflation stripped out, when a rate was given.
    real_final_balance_minor: int | None
    schedule: list[GrowthPoint] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)


def investment_growth(
    *,
    initial_minor: int,
    monthly_contribution_minor: int,
    annual_return: float,
    months: int,
    annual_inflation: float | None = None,
    contribution_growth: float = 0.0,
    with_schedule: bool = False,
) -> InvestmentGrowthResult:
    """Compound a pot forward, separating growth from contributions.

    Returns compound on the *effective* convention: a stated 7% annual return
    means the year ends 7% up. Using the lender convention here would silently
    inflate a thirty-year projection by several percent of the final pot.

    `annual_inflation`, when supplied, produces the same figure in today's
    money. That number is almost always the one worth quoting — a pot of
    "4.2 million in 2065" means nothing without it.
    """
    _validate_amount(initial_minor, "initial balance")
    _validate_amount(monthly_contribution_minor, "monthly contribution")
    _validate_months(months)
    i = monthly_rate(annual_return, compounding="effective")

    balance = float(initial_minor)
    contribution = float(monthly_contribution_minor)
    contributed = initial_minor
    schedule: list[GrowthPoint] = []

    for month in range(1, months + 1):
        balance = balance * (1 + i) + contribution
        contributed += round(contribution)
        if contribution_growth and month % 12 == 0:
            contribution *= 1 + contribution_growth
        if with_schedule:
            schedule.append(
                GrowthPoint(
                    month=month,
                    contributed_minor=contributed,
                    balance_minor=round(balance),
                    growth_minor=round(balance) - contributed,
                )
            )

    final = round(balance)
    real_final = None
    if annual_inflation is not None:
        _validate_rate(annual_inflation)
        real_final = round(final / ((1 + annual_inflation) ** (months / 12)))

    assumptions = [
        f"Return of {annual_return:.2%} a year, compounded so twelve months make exactly that.",
        "A smooth return every month — real markets do not do this, which is what the "
        "Monte Carlo view is for.",
        "No tax on growth, no platform or fund fees.",
    ]
    if contribution_growth:
        assumptions.append(
            f"Contributions rising {contribution_growth:.2%} a year, applied on each anniversary."
        )
    if annual_inflation is not None:
        assumptions.append(f"Today's-money figure discounts at {annual_inflation:.2%} a year.")

    return InvestmentGrowthResult(
        initial_minor=initial_minor,
        monthly_contribution_minor=monthly_contribution_minor,
        annual_return=annual_return,
        months=months,
        final_balance_minor=final,
        total_contributed_minor=contributed,
        total_growth_minor=final - contributed,
        real_final_balance_minor=real_final,
        schedule=schedule,
        assumptions=assumptions,
    )


# ---------------------------------------------------------------------------
# savings goal
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SavingsGoalResult:
    target_minor: int
    current_minor: int
    annual_return: float
    #: Months to reach the target at the given contribution, or None when the
    #: contribution never gets there.
    months_to_target: int | None
    #: The contribution that *would* reach it inside `by_months`, when asked.
    required_monthly_minor: int | None
    projected_balance_minor: int | None
    shortfall_minor: int
    on_track: bool
    assumptions: list[str] = field(default_factory=list)


def savings_goal(
    *,
    target_minor: int,
    current_minor: int,
    monthly_contribution_minor: int,
    annual_return: float = 0.0,
    by_months: int | None = None,
) -> SavingsGoalResult:
    """Answer both directions of a savings goal.

    Forward: "at this rate, when do I get there?" Inverse: "to get there by
    then, what does it take?" The inverse is the one that changes behaviour,
    so it is computed whenever a deadline is supplied rather than only when the
    forward answer disappoints.
    """
    _validate_amount(target_minor, "target")
    _validate_amount(current_minor, "current balance")
    _validate_amount(monthly_contribution_minor, "monthly contribution")
    i = monthly_rate(annual_return, compounding="effective")

    months_to_target: int | None = None
    if current_minor >= target_minor:
        months_to_target = 0
    elif monthly_contribution_minor > 0 or i > 0:
        balance = float(current_minor)
        for month in range(1, MAX_HORIZON_MONTHS + 1):
            balance = balance * (1 + i) + monthly_contribution_minor
            if balance >= target_minor:
                months_to_target = month
                break

    required_monthly: int | None = None
    projected: int | None = None
    if by_months is not None:
        _validate_months(by_months)
        growth = (1 + i) ** by_months
        projected_balance = current_minor * growth
        if monthly_contribution_minor:
            projected_balance += (
                monthly_contribution_minor * (growth - 1) / i if i else monthly_contribution_minor * by_months
            )
        projected = round(projected_balance)
        remaining = target_minor - current_minor * growth
        if remaining <= 0:
            required_monthly = 0
        elif i:
            required_monthly = math.ceil(remaining * i / (growth - 1))
        else:
            required_monthly = math.ceil(remaining / by_months)

    shortfall = max(0, target_minor - projected) if projected is not None else 0
    on_track = months_to_target is not None and (by_months is None or months_to_target <= by_months)

    assumptions = ["Contributions made every month without interruption."]
    if annual_return:
        assumptions.append(f"Balance growing {annual_return:.2%} a year while it is saved.")
    else:
        assumptions.append("No return assumed on the balance — appropriate for a cash savings pot.")
    if months_to_target is None:
        assumptions.append(f"Unreachable within the {MAX_HORIZON_MONTHS // 12}-year modelling ceiling.")

    return SavingsGoalResult(
        target_minor=target_minor,
        current_minor=current_minor,
        annual_return=annual_return,
        months_to_target=months_to_target,
        required_monthly_minor=required_monthly,
        projected_balance_minor=projected,
        shortfall_minor=shortfall,
        on_track=on_track,
        assumptions=assumptions,
    )


# ---------------------------------------------------------------------------
# retirement
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RetirementResult:
    years_to_retirement: int
    pot_at_retirement_minor: int
    real_pot_at_retirement_minor: int
    #: Sustainable annual income from the pot at the withdrawal rate.
    sustainable_annual_income_minor: int
    sustainable_monthly_income_minor: int
    target_monthly_income_minor: int | None
    monthly_shortfall_minor: int
    #: Extra monthly saving that would close the shortfall. None when there
    #: isn't one.
    required_extra_monthly_minor: int | None
    on_track: bool
    #: Years the pot lasts if drawn at the target rate rather than the
    #: sustainable one. None when it is never exhausted.
    depletion_years: float | None
    assumptions: list[str] = field(default_factory=list)


def retirement_estimate(
    *,
    current_pot_minor: int,
    monthly_contribution_minor: int,
    years_to_retirement: int,
    annual_return: float,
    annual_inflation: float = 0.0,
    withdrawal_rate: float = 0.04,
    target_monthly_income_minor: int | None = None,
    contribution_growth: float = 0.0,
) -> RetirementResult:
    """Project a retirement pot and say what income it actually buys.

    Reports the pot in both nominal and today's money, because a nominal pot
    thirty years out is a number people badly misread in their own favour. The
    income figure is the one that matters and it is derived from the real pot,
    not the nominal one.

    `depletion_years` answers the question the withdrawal rate hides: if you
    insist on drawing more than the pot sustains, how long before it is gone?
    """
    _validate_amount(current_pot_minor, "current pot")
    _validate_amount(monthly_contribution_minor, "monthly contribution")
    if years_to_retirement <= 0:
        raise CalculatorError("years to retirement must be positive")
    if not 0 < withdrawal_rate <= 0.2:
        raise CalculatorError("withdrawal rate must be a fraction in (0, 0.2]")

    months = years_to_retirement * 12
    growth = investment_growth(
        initial_minor=current_pot_minor,
        monthly_contribution_minor=monthly_contribution_minor,
        annual_return=annual_return,
        months=months,
        annual_inflation=annual_inflation or None,
        contribution_growth=contribution_growth,
    )
    pot = growth.final_balance_minor
    real_pot = growth.real_final_balance_minor if growth.real_final_balance_minor is not None else pot

    sustainable_annual = round(real_pot * withdrawal_rate)
    sustainable_monthly = round(sustainable_annual / 12)

    shortfall = 0
    required_extra = None
    depletion: float | None = None
    on_track = True
    if target_monthly_income_minor is not None:
        _validate_amount(target_monthly_income_minor, "target monthly income")
        shortfall = max(0, target_monthly_income_minor - sustainable_monthly)
        on_track = shortfall == 0
        if shortfall:
            # The extra pot needed, discounted back to a monthly contribution
            # over the accumulation period.
            required_real_pot = round(target_monthly_income_minor * 12 / withdrawal_rate)
            required_nominal = round(required_real_pot * ((1 + annual_inflation) ** years_to_retirement))
            i = monthly_rate(annual_return, compounding="effective")
            factor = (1 + i) ** months
            gap = required_nominal - pot
            required_extra = math.ceil(gap * i / (factor - 1)) if i else math.ceil(gap / months)
            depletion = _depletion_years(
                real_pot, target_monthly_income_minor, annual_return, annual_inflation
            )

    assumptions = [
        f"{years_to_retirement} years of contributions at {annual_return:.2%} a year.",
        f"A {withdrawal_rate:.1%} withdrawal rate — the convention, not a guarantee.",
        "Contributions and returns uninterrupted; no career break, no market crash at the wrong moment.",
    ]
    if annual_inflation:
        assumptions.append(f"Income figures are in today's money, discounted at {annual_inflation:.2%}.")
    else:
        assumptions.append(
            "No inflation assumed, so the income figure is in future money and overstates purchasing power."
        )

    return RetirementResult(
        years_to_retirement=years_to_retirement,
        pot_at_retirement_minor=pot,
        real_pot_at_retirement_minor=real_pot,
        sustainable_annual_income_minor=sustainable_annual,
        sustainable_monthly_income_minor=sustainable_monthly,
        target_monthly_income_minor=target_monthly_income_minor,
        monthly_shortfall_minor=shortfall,
        required_extra_monthly_minor=required_extra,
        on_track=on_track,
        depletion_years=depletion,
        assumptions=assumptions,
    )


def _depletion_years(
    pot_minor: int, monthly_draw_minor: int, annual_return: float, annual_inflation: float
) -> float | None:
    """Years until a pot drawn at `monthly_draw` is exhausted, in real terms.

    Returns None when the real return covers the draw and the pot survives the
    modelling ceiling — "it lasts" is the honest answer there, not a number
    with sixty years of false precision behind it.
    """
    real_return = (1 + annual_return) / (1 + annual_inflation) - 1
    i = monthly_rate(real_return, compounding="effective") if -0.5 < real_return < 2 else 0.0
    balance = float(pot_minor)
    for month in range(1, MAX_HORIZON_MONTHS + 1):
        balance = balance * (1 + i) - monthly_draw_minor
        if balance <= 0:
            return round(month / 12, 1)
    return None


# ---------------------------------------------------------------------------
# net worth projection
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NetWorthPoint:
    month: int
    assets_minor: int
    liabilities_minor: int
    net_worth_minor: int


@dataclass(frozen=True)
class NetWorthProjectionResult:
    months: int
    opening_net_worth_minor: int
    closing_net_worth_minor: int
    #: Month at which net worth first turns positive, for anyone starting
    #: underwater. None when it starts positive or never gets there.
    breakeven_month: int | None
    points: list[NetWorthPoint] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)


def net_worth_projection(
    *,
    assets_minor: int,
    liabilities_minor: int,
    monthly_saving_minor: int,
    annual_asset_return: float,
    monthly_debt_payment_minor: int,
    debt_annual_rate: float,
    months: int,
) -> NetWorthProjectionResult:
    """Project both sides of the balance sheet, not just the savings side.

    Net worth moves for two reasons and most tools model one: assets compound,
    and debt amortises. Someone paying down an expensive loan is building net
    worth as fast as someone investing, and a projection that ignores the
    liability column tells them the opposite.
    """
    _validate_amount(assets_minor, "assets")
    _validate_amount(liabilities_minor, "liabilities")
    _validate_amount(monthly_saving_minor, "monthly saving")
    _validate_amount(monthly_debt_payment_minor, "monthly debt payment")
    _validate_months(months)

    asset_i = monthly_rate(annual_asset_return, compounding="effective")
    debt_i = monthly_rate(debt_annual_rate)

    assets = float(assets_minor)
    debt = float(liabilities_minor)
    opening = assets_minor - liabilities_minor
    breakeven = None
    points: list[NetWorthPoint] = []

    for month in range(1, months + 1):
        assets = assets * (1 + asset_i) + monthly_saving_minor
        if debt > 0:
            interest = debt * debt_i
            debt = max(0.0, debt + interest - monthly_debt_payment_minor)
        net = round(assets) - round(debt)
        if breakeven is None and opening < 0 <= net:
            breakeven = month
        points.append(
            NetWorthPoint(
                month=month,
                assets_minor=round(assets),
                liabilities_minor=round(debt),
                net_worth_minor=net,
            )
        )

    closing = points[-1].net_worth_minor if points else opening
    assumptions = [
        f"Assets growing {annual_asset_return:.2%} a year; debt accruing {debt_annual_rate:.2%}.",
        "Saving and debt payments held flat in nominal terms for the whole window.",
        "No new borrowing, no windfalls, no major purchases beyond those modelled.",
    ]

    return NetWorthProjectionResult(
        months=months,
        opening_net_worth_minor=opening,
        closing_net_worth_minor=closing,
        breakeven_month=breakeven,
        points=points,
        assumptions=assumptions,
    )
