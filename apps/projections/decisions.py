"""The decision assistant — the questions people actually arrive with.

"Can I afford this?" is not a projection request. It is a request for a verdict,
and the difference matters: a projection hands somebody 480 numbers and lets
them work it out, while a verdict takes a position on their behalf and has to
be right, or at least has to be honest about how sure it is.

Every evaluator here returns the same shape — a `Decision` — and that shape is
the argument this module is making about what an answer owes the person reading
it:

``verdict``        a position, not a shrug. "Yes, with a caveat" is an answer;
                   "it depends on your circumstances" is a refusal wearing a
                   suit.
``because``        the two or three figures the verdict actually turns on, so a
                   disagreement can be about the right thing.
``costs``          what it takes away. Every yes has one, and an assistant that
                   only lists benefits is a salesman.
``risks``          what would have to happen for this to go wrong, and how bad.
``alternatives``   the option not asked about. Someone asking "can I afford a
                   500k car" is often better served by "yes, and a 300k car
                   leaves you six months of runway instead of two".
``confidence``     how much of this rests on measurement versus assumption.

**No LLM touches any of this.** Every number is computed here, by the Phase 1
engine and the calculators, from the household's own ledger. The narrative
layer in `apps.intelligence.advisor` may *phrase* these findings; it may not
originate them, and it is not permitted to state a figure this module did not
produce. That boundary is the whole reason the product can put a verdict on
screen at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import adapters, kenya
from . import calculators as calc
from .engine import (
    CompiledEvent,
    DebtPosition,
    EconomicAssumptions,
    FinancialPosition,
)
from .risk import RUNWAY_FLOOR_MONTHS, RUNWAY_TARGET_MONTHS

#: Share of net income going to housing above which lenders, and most of the
#: research, agree the rest of a budget stops working. Stated in the output.
HOUSING_CEILING = 0.30

#: Total debt service ceiling, housing included.
TOTAL_DEBT_CEILING = 0.36


class Verdict:
    YES = "yes"
    YES_WITH_CARE = "yes_with_care"
    TIGHT = "tight"
    NO = "no"
    UNKNOWN = "unknown"


#: How sure the answer is. Not a probability — a statement about what the
#: answer rests on, which is more useful and less pretend-precise.
class Confidence:
    MEASURED = "measured"  # almost entirely from recorded history
    MIXED = "mixed"  # measured position, assumed future
    ASSUMED = "assumed"  # mostly assumption; treat as a sketch


@dataclass(frozen=True)
class Finding:
    """One figure the verdict turns on.

    `amount_minor` is kept separate from `text` so the API can render money in
    the user's format and so the narrative layer has an allow-list of figures
    it is permitted to repeat.
    """

    label: str
    text: str
    amount_minor: int | None = None
    months: int | None = None
    percent: float | None = None


@dataclass(frozen=True)
class Decision:
    question: str
    verdict: str
    headline: str
    confidence: str
    because: list[Finding] = field(default_factory=list)
    costs: list[Finding] = field(default_factory=list)
    risks: list[Finding] = field(default_factory=list)
    alternatives: list[Finding] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def figures(self) -> set[int]:
        """Every monetary figure this decision computed.

        The allow-list the narrative layer is checked against: a model may
        repeat one of these, and may not introduce one of its own.
        """
        out: set[int] = set()
        for group in (self.because, self.costs, self.risks, self.alternatives):
            for finding in group:
                if finding.amount_minor is not None:
                    out.add(abs(finding.amount_minor))
        return out


def _confidence(position: FinancialPosition, horizon_months: int) -> str:
    """More assumption in the answer means less confidence in it.

    Short horizons off a measured position are near-fact; thirty-year answers
    are mostly a view about returns wearing a number.
    """
    if position.monthly_net_income_minor <= 0 or position.monthly_expenses_minor <= 0:
        return Confidence.ASSUMED
    if horizon_months <= 36:
        return Confidence.MEASURED
    if horizon_months <= 180:
        return Confidence.MIXED
    return Confidence.ASSUMED


# ---------------------------------------------------------------------------
# "Can I afford this mortgage?"
# ---------------------------------------------------------------------------
def can_i_afford_mortgage(
    *,
    position: FinancialPosition,
    property_price_minor: int,
    deposit_minor: int,
    annual_rate: float,
    years: int = 25,
    annual_tax_minor: int = 0,
    annual_insurance_minor: int = 0,
    assumptions: EconomicAssumptions | None = None,
) -> Decision:
    """The question the product exists to answer well.

    Three tests, and a yes needs all three: the payment fits against income,
    the deposit does not eat the emergency fund, and the projection does not
    go negative afterwards. Most affordability calculators run only the first,
    which is why people pass them and then struggle.
    """
    quote = calc.mortgage(
        property_price_minor=property_price_minor,
        deposit_minor=deposit_minor,
        annual_rate=annual_rate,
        years=years,
        annual_tax_minor=annual_tax_minor,
        annual_insurance_minor=annual_insurance_minor,
    )
    income = position.monthly_net_income_minor
    # `None`, not `inf`, when there is no income to measure against. "Cannot be
    # computed" is what this actually means, and `inf` is both a lie about the
    # ratio and not representable in JSON — it reached the serialiser as a 500
    # for every workspace with an account but no history yet.
    housing_share = quote.monthly_cost_minor / income if income else None
    existing_service = sum(d.monthly_payment_minor for d in position.debts)
    total_share = (quote.monthly_cost_minor + existing_service) / income if income else None

    runway_after = (position.liquid_minor - deposit_minor) / max(
        1, position.monthly_expenses_minor + quote.monthly_cost_minor
    )

    # The third test: run the household forward with the purchase in it.
    purchase = CompiledEvent(
        label="This home",
        start_month=1,
        one_off_cash_minor=-deposit_minor,
        asset_delta_minor=property_price_minor,
        new_debt=DebtPosition(
            label="This mortgage",
            balance_minor=quote.loan_minor,
            annual_rate=annual_rate,
            monthly_payment_minor=quote.monthly_payment_minor,
        ),
        monthly_expense_delta_minor=quote.monthly_tax_minor + quote.monthly_insurance_minor,
    )
    horizon = min(calc.MAX_HORIZON_MONTHS, years * 12)
    projected = adapters.project_live(
        position=position,
        assumptions=assumptions or EconomicAssumptions(),
        events=[purchase],
        months=horizon,
    )

    fails_projection = projected.first_negative_month is not None
    if income <= 0:
        verdict, headline = Verdict.UNKNOWN, "No recorded income to test a payment against."
    elif deposit_minor > position.liquid_minor:
        verdict = Verdict.NO
        headline = "The deposit is more than you hold in cash."
    elif fails_projection:
        verdict = Verdict.NO
        headline = "The payment fits on paper, but the balance runs out before the term does."
    elif housing_share > HOUSING_CEILING or total_share > TOTAL_DEBT_CEILING:
        verdict = Verdict.TIGHT
        headline = "Affordable only if very little else changes."
    elif runway_after < RUNWAY_FLOOR_MONTHS:
        verdict = Verdict.YES_WITH_CARE
        headline = "Affordable, but the deposit leaves the emergency fund thin."
    else:
        verdict = Verdict.YES
        headline = "Affordable on every test that matters."

    because = [
        Finding(
            "Monthly cost of ownership",
            "Payment plus tax and insurance — the figure the household actually pays.",
            amount_minor=quote.monthly_cost_minor,
        ),
        Finding(
            "Share of your income",
            (
                f"{housing_share:.0%} of net income, against a {HOUSING_CEILING:.0%} guide."
                if housing_share is not None
                else "No recorded income yet, so this cannot be measured against one."
            ),
            percent=round(housing_share, 4) if housing_share is not None else None,
        ),
        Finding(
            "Runway after the deposit",
            f"{runway_after:.1f} months of everything covered by remaining cash.",
            months=int(runway_after),
        ),
    ]
    costs = [
        Finding(
            "Deposit, gone on day one",
            "Cash converted into a house is cash you cannot reach in a bad month.",
            amount_minor=deposit_minor,
        ),
        Finding(
            "Interest over the full term",
            f"Total paid to borrow, over {years} years.",
            amount_minor=quote.total_interest_minor,
        ),
    ]
    risks = []
    if fails_projection and projected.first_negative_month:
        risks.append(
            Finding(
                "The balance runs out",
                f"On this path the balance first goes negative in month {projected.first_negative_month}.",
                months=projected.first_negative_month,
            )
        )
    if total_share is not None and total_share > HOUSING_CEILING:
        risks.append(
            Finding(
                "Everything committed",
                f"{total_share:.0%} of income is spoken for once existing debts are counted.",
                percent=round(total_share, 4),
            )
        )
    if runway_after < RUNWAY_TARGET_MONTHS:
        risks.append(
            Finding(
                "Thin cover afterwards",
                "A boiler, a car or a month without work would go straight onto credit.",
                months=int(runway_after),
            )
        )

    alternatives = []
    affordable = _max_affordable_price(
        position=position, annual_rate=annual_rate, years=years, deposit_minor=deposit_minor
    )
    if verdict in (Verdict.NO, Verdict.TIGHT) and affordable > 0:
        alternatives.append(
            Finding(
                "A price that clears every test",
                "Same deposit and rate, at the price where the payment stops straining.",
                amount_minor=affordable,
            )
        )

    return Decision(
        question="Can I afford this mortgage?",
        verdict=verdict,
        headline=headline,
        confidence=_confidence(position, horizon),
        because=because,
        costs=costs,
        risks=risks,
        alternatives=alternatives,
        assumptions=quote.assumptions
        + [
            f"Housing guide of {HOUSING_CEILING:.0%} of net income, {TOTAL_DEBT_CEILING:.0%} including other debt.",
            "Your income and spending are the medians measured from your own ledger.",
        ],
    )


def _max_affordable_price(
    *, position: FinancialPosition, annual_rate: float, years: int, deposit_minor: int
) -> int:
    """The largest price whose monthly cost stays inside the guides.

    Solved by bisection rather than algebraically: the constraint is the *cost
    of ownership*, which includes tax and insurance the caller may express as
    fixed amounts, so there is no clean closed form and a search is honest
    about that.
    """
    income = position.monthly_net_income_minor
    if income <= 0:
        return 0
    existing = sum(d.monthly_payment_minor for d in position.debts)
    budget = income * HOUSING_CEILING
    if existing + budget > income * TOTAL_DEBT_CEILING:
        budget = max(0, income * TOTAL_DEBT_CEILING - existing)
    if budget <= 0:
        return 0

    # Upper bound from the annuity closed form — the principal a level payment
    # of `budget` sustains, plus slack for the integer rounding the real
    # schedule applies. A fixed ceiling sat here before (deposit + 1e9 minor,
    # i.e. ten million in major units), which quietly capped the answer for
    # any income large enough to carry more than that: the one group whose
    # "price that clears every test" was materially understated was high
    # earners, precisely the people most likely to ask.
    i = calc.monthly_rate(annual_rate)
    n = years * 12
    sustainable = budget * n if i == 0 else budget * (1 - (1 + i) ** -n) / i
    low, high = deposit_minor, deposit_minor + int(sustainable * 1.01) + 1_000
    for _ in range(60):
        mid = (low + high) // 2
        if mid <= deposit_minor:
            break
        payment = calc.level_payment_minor(mid - deposit_minor, annual_rate, years * 12)
        if payment <= budget:
            low = mid
        else:
            high = mid
    return low


# ---------------------------------------------------------------------------
# "How much house can I comfortably afford?"
# ---------------------------------------------------------------------------
def how_much_house(
    *,
    position: FinancialPosition,
    annual_rate: float,
    years: int = 25,
    deposit_minor: int | None = None,
) -> Decision:
    """The inverse, and the more useful question.

    The deposit defaults to what the household could put down while keeping the
    conventional emergency fund intact — because the answer "you can afford a
    huge house if you spend every shilling of savings on it" is arithmetically
    true and practically useless.
    """
    keep_back = position.monthly_expenses_minor * RUNWAY_FLOOR_MONTHS
    usable_deposit = deposit_minor if deposit_minor is not None else max(0, position.liquid_minor - keep_back)
    price = _max_affordable_price(
        position=position, annual_rate=annual_rate, years=years, deposit_minor=usable_deposit
    )
    income = position.monthly_net_income_minor

    if income <= 0 or price <= usable_deposit:
        return Decision(
            question="How much house can I comfortably afford?",
            verdict=Verdict.UNKNOWN,
            headline="Not enough recorded income to put a number on this.",
            confidence=Confidence.ASSUMED,
            assumptions=["Add income history and this becomes measurable rather than guessed."],
        )

    payment = calc.level_payment_minor(price - usable_deposit, annual_rate, years * 12)
    return Decision(
        question="How much house can I comfortably afford?",
        verdict=Verdict.YES,
        headline="Comfortably, on your measured income and keeping your emergency fund.",
        confidence=_confidence(position, years * 12),
        because=[
            Finding(
                "Price you can carry",
                "The most expensive home whose payment stays inside the guides.",
                amount_minor=price,
            ),
            Finding(
                "Deposit assumed",
                "What is left after holding back three months of spending.",
                amount_minor=usable_deposit,
            ),
            Finding(
                "Monthly payment at that price",
                f"Principal and interest over {years} years.",
                amount_minor=payment,
            ),
        ],
        costs=[
            Finding(
                "Held back deliberately",
                f"{RUNWAY_FLOOR_MONTHS} months of spending kept in cash rather than spent on the deposit.",
                amount_minor=keep_back,
            )
        ],
        risks=[
            Finding(
                "Excludes the costs of owning",
                "Tax, insurance and upkeep are not in this figure and are not optional.",
            )
        ],
        assumptions=[
            f"Payment capped at {HOUSING_CEILING:.0%} of net income, {TOTAL_DEBT_CEILING:.0%} with other debt.",
            f"Rate of {annual_rate:.2%} held for {years} years.",
            "Emergency fund preserved rather than spent on the deposit.",
        ],
    )


# ---------------------------------------------------------------------------
# "Should I pay off debt or invest?"
# ---------------------------------------------------------------------------
def debt_or_invest(
    *,
    position: FinancialPosition,
    monthly_amount_minor: int,
    expected_return: float,
    months: int = 120,
    assumptions: EconomicAssumptions | None = None,
) -> Decision:
    """Run both, rather than quoting the rule of thumb.

    The rule of thumb — pay debt above your expected return, invest below — is
    usually right and it hides the thing that decides it in practice: paying
    debt is certain and investing is not. Both legs go through the engine so
    the comparison is measured, and the certainty gap is stated rather than
    priced.
    """
    base = assumptions or EconomicAssumptions()
    if not position.debts:
        return Decision(
            question="Should I pay debt down or invest?",
            verdict=Verdict.UNKNOWN,
            headline="No debts on record, so there is nothing to weigh investing against.",
            confidence=Confidence.MEASURED,
        )

    highest = max(position.debts, key=lambda d: d.annual_rate)

    # Overpaying is modelled as the debt carrying a larger payment, which is
    # what actually happens. Modelling it as an extra *expense* instead would
    # take the money out of cash flow without ever reducing the balance —
    # charging for the decision and delivering none of its benefit.
    faster = tuple(
        DebtPosition(
            label=d.label,
            balance_minor=d.balance_minor,
            annual_rate=d.annual_rate,
            monthly_payment_minor=d.monthly_payment_minor + (monthly_amount_minor if d is highest else 0),
        )
        for d in position.debts
    )

    # Two fairness rules, each of which existed to fix a real distortion:
    #
    # 1. **Only the decided-about money earns the expected return.** The first
    #    version swapped `annual_investment_return` globally, which re-rated
    #    the household's *existing* portfolio — a large portfolio asking about
    #    a small overpayment got an answer dominated by the re-rating, and the
    #    distortion scaled with wealth rather than with the decision. The
    #    monthly amount is carried as its own asset tranche instead.
    #
    # 2. **Both legs spend the same money every month, forever.** Once a debt
    #    clears, the payment that serviced it is freed — and a leg that lets
    #    freed cash idle at the cash rate while the other leg compounds loses
    #    for reasons that have nothing to do with the question. So each leg
    #    redirects the freed payment into the same investment vehicle the
    #    moment its debt clears: the comparison is "avalanche then invest"
    #    against "invest alongside the minimums", which is the choice people
    #    are actually weighing.
    def _payoff_month(payment_minor: int) -> int | None:
        try:
            return calc.amortise(
                principal_minor=highest.balance_minor,
                annual_rate=highest.annual_rate,
                months=calc.MAX_HORIZON_MONTHS,
                payment_minor=payment_minor,
                with_schedule=False,
            ).actual_months
        except calc.CalculatorError:
            return None  # the payment never clears it; nothing to redirect

    def _invested(label: str, start: int, monthly: int) -> list[CompiledEvent]:
        return [
            CompiledEvent(
                label=label,
                start_month=month,
                one_off_cash_minor=-monthly,
                asset_delta_minor=monthly,
                asset_annual_growth=expected_return,
            )
            for month in range(start, months + 1)
        ]

    boosted_payment = highest.monthly_payment_minor + monthly_amount_minor
    debt_events: list[CompiledEvent] = []
    cleared_boosted = _payoff_month(boosted_payment)
    if cleared_boosted is not None and cleared_boosted < months:
        debt_events = _invested("Freed payment, invested", cleared_boosted + 1, boosted_payment)

    invest_events = _invested("Invest instead", 1, monthly_amount_minor)
    cleared_minimum = _payoff_month(highest.monthly_payment_minor)
    if cleared_minimum is not None and cleared_minimum < months:
        invest_events += _invested(
            "Freed minimum, invested", cleared_minimum + 1, highest.monthly_payment_minor
        )

    debt_leg = adapters.project_live(
        position=replace(position, debts=faster), assumptions=base, events=debt_events, months=months
    )
    invest_leg = adapters.project_live(
        position=position, assumptions=base, events=invest_events, months=months
    )

    difference = debt_leg.closing_net_worth_minor - invest_leg.closing_net_worth_minor
    debt_wins = difference > 0

    if debt_wins:
        verdict = Verdict.YES
        headline = f"Clearing {highest.label} first leaves you better off, and it is the certain option."
    elif abs(difference) < monthly_amount_minor:
        verdict = Verdict.YES_WITH_CARE
        headline = "Close enough to a tie that certainty should decide it — which favours the debt."
    else:
        verdict = Verdict.NO
        headline = "Investing comes out ahead on these assumptions, but only if the return holds."

    return Decision(
        question="Should I pay debt down or invest?",
        verdict=verdict,
        headline=headline,
        confidence=_confidence(position, months),
        because=[
            Finding(
                "Paying the debt down",
                f"Net worth after {months // 12} years with the extra going to {highest.label}.",
                amount_minor=debt_leg.closing_net_worth_minor,
            ),
            Finding(
                "Investing instead",
                f"Net worth after {months // 12} years at a {expected_return:.1%} return.",
                amount_minor=invest_leg.closing_net_worth_minor,
            ),
            Finding(
                "Difference",
                "What the choice is worth over the window.",
                amount_minor=abs(difference),
            ),
        ],
        costs=[
            Finding(
                "Interest avoided by paying down",
                "Guaranteed, and taxed nowhere.",
                amount_minor=max(
                    0, invest_leg.total_interest_paid_minor - debt_leg.total_interest_paid_minor
                ),
            )
        ],
        risks=[
            Finding(
                "The return is a hope; the rate is a fact",
                f"{highest.label} charges {highest.annual_rate:.1%} whatever markets do. "
                f"The {expected_return:.1%} is an assumption.",
                percent=round(highest.annual_rate, 4),
            )
        ],
        alternatives=[
            Finding(
                "Split it",
                "Half to the highest rate and half invested captures most of both, "
                "and is what most people actually stick to.",
                amount_minor=monthly_amount_minor // 2,
            )
        ],
        assumptions=[
            f"Both legs run the same engine over {months} months; only the destination differs.",
            "The extra goes to the highest-rate debt, which is where each shilling buys most.",
            f"Only the money being decided about earns the {expected_return:.1%}; your existing "
            "portfolio keeps the standard return assumption in both legs.",
            "When a debt clears, the payment it freed is invested rather than left idle, in "
            "both legs — so the comparison is about ordering, not about one leg wasting cash.",
            "Investment returns are assumed steady — see the simulation for what varying them does.",
        ],
    )


# ---------------------------------------------------------------------------
# "Can I retire at 55?"
# ---------------------------------------------------------------------------
def can_i_retire(
    *,
    position: FinancialPosition,
    years_until: int,
    monthly_income_needed_minor: int,
    annual_return: float = 0.07,
    annual_inflation: float = 0.05,
    withdrawal_rate: float = 0.04,
    monthly_pension_income_minor: int = 0,
) -> Decision:
    """Whether the pot supports the life, and what would close the gap.

    The answer is derived from `retirement_estimate`, so it agrees with the
    calculator by construction rather than by care.
    """
    monthly_saving = (
        max(0, position.monthly_net_income_minor - position.monthly_expenses_minor)
        + position.monthly_investment_contribution_minor
    )
    needed_from_pot = max(0, monthly_income_needed_minor - monthly_pension_income_minor)

    estimate = calc.retirement_estimate(
        current_pot_minor=position.investment_minor + position.liquid_minor,
        monthly_contribution_minor=monthly_saving,
        years_to_retirement=years_until,
        annual_return=annual_return,
        annual_inflation=annual_inflation,
        withdrawal_rate=withdrawal_rate,
        target_monthly_income_minor=needed_from_pot,
    )

    if estimate.on_track:
        verdict = Verdict.YES
        headline = "On the current saving rate, yes — with room."
    elif estimate.monthly_shortfall_minor < needed_from_pot * 0.15:
        verdict = Verdict.TIGHT
        headline = "Close. A modest increase in saving, or a year or two longer, closes it."
    else:
        verdict = Verdict.NO
        headline = "Not at the current pace — but the gap has a price, below."

    because = [
        Finding(
            "What the pot would support",
            f"Monthly income in today's money, drawing {withdrawal_rate:.1%} a year.",
            amount_minor=estimate.sustainable_monthly_income_minor,
        ),
        Finding(
            "What you said you need",
            "From savings, after any pension.",
            amount_minor=needed_from_pot,
        ),
        Finding(
            "Pot at that date, in today's money",
            f"After {years_until} years of saving {monthly_saving} a month.",
            amount_minor=estimate.real_pot_at_retirement_minor,
        ),
    ]
    risks = []
    if estimate.depletion_years is not None:
        risks.append(
            Finding(
                "Drawing what you need anyway",
                f"The pot would last about {estimate.depletion_years:.0f} years at that rate, then stop.",
                months=int(estimate.depletion_years * 12),
            )
        )
    risks.append(
        Finding(
            "Sequence of returns",
            "A bad first decade of retirement does more damage than a bad average, "
            "because withdrawals lock the losses in.",
        )
    )

    alternatives = []
    if estimate.required_extra_monthly_minor:
        alternatives.append(
            Finding(
                "Save this much more each month",
                "What closes the gap by the date you asked about.",
                amount_minor=estimate.required_extra_monthly_minor,
            )
        )
        alternatives.append(
            Finding(
                "Or go later",
                "Every extra year adds contributions and removes one of drawdown, "
                "which moves the number twice.",
            )
        )

    return Decision(
        question=f"Can I retire in {years_until} years?",
        verdict=verdict,
        headline=headline,
        confidence=Confidence.ASSUMED if years_until > 15 else Confidence.MIXED,
        because=because,
        costs=[
            Finding(
                "Monthly saving assumed",
                "Measured from your income less your spending, plus recorded contributions.",
                amount_minor=monthly_saving,
            )
        ],
        risks=risks,
        alternatives=alternatives,
        assumptions=estimate.assumptions,
    )


# ---------------------------------------------------------------------------
# "Should I buy or rent?"
# ---------------------------------------------------------------------------
def buy_or_rent(
    *,
    position: FinancialPosition,
    property_price_minor: int,
    deposit_minor: int,
    annual_rate: float,
    monthly_rent_minor: int,
    years: int = 10,
    annual_tax_minor: int = 0,
    annual_insurance_minor: int = 0,
    maintenance_rate: float = 0.01,
    assumptions: EconomicAssumptions | None = None,
) -> Decision:
    """Compare two whole financial lives, not two monthly payments.

    The common framing — "rent is dead money" — compares a rent cheque to a
    mortgage payment and ignores that most of an early mortgage payment is also
    dead money, that a deposit has an opportunity cost, and that maintenance
    exists. Both legs here are full projections: the buyer gets a house and a
    debt, the renter invests the deposit they did not spend.
    """
    base = assumptions or EconomicAssumptions()
    months = years * 12
    quote = calc.mortgage(
        property_price_minor=property_price_minor,
        deposit_minor=deposit_minor,
        annual_rate=annual_rate,
        years=25,
        annual_tax_minor=annual_tax_minor,
        annual_insurance_minor=annual_insurance_minor,
    )
    monthly_maintenance = round(property_price_minor * maintenance_rate / 12)

    buying = adapters.project_live(
        position=position,
        assumptions=base,
        events=[
            CompiledEvent(
                label="Buy",
                start_month=1,
                one_off_cash_minor=-deposit_minor,
                asset_delta_minor=property_price_minor,
                new_debt=DebtPosition(
                    label="Mortgage",
                    balance_minor=quote.loan_minor,
                    annual_rate=annual_rate,
                    monthly_payment_minor=quote.monthly_payment_minor,
                ),
                monthly_expense_delta_minor=(
                    quote.monthly_tax_minor + quote.monthly_insurance_minor + monthly_maintenance
                ),
            )
        ],
        months=months,
    )
    renting = adapters.project_live(
        position=position,
        assumptions=base,
        events=[
            CompiledEvent(
                label="Rent",
                start_month=1,
                monthly_expense_delta_minor=monthly_rent_minor,
            ),
            # The deposit the renter did not spend is *invested*, not left in a
            # current account. Leaving it in cash — at the cash return, which
            # defaults to zero — would silently hand the comparison to buying,
            # and that single modelling choice is what makes most published
            # buy-vs-rent calculators wrong.
            CompiledEvent(
                label="Invest the deposit",
                start_month=1,
                one_off_cash_minor=-deposit_minor,
                asset_delta_minor=deposit_minor,
                asset_annual_growth=base.annual_investment_return,
            ),
        ],
        months=months,
    )

    difference = buying.closing_net_worth_minor - renting.closing_net_worth_minor
    buying_wins = difference > 0

    return Decision(
        question="Should I buy or rent?",
        verdict=Verdict.YES if buying_wins else Verdict.NO,
        headline=(
            f"Over {years} years, buying leaves you ahead."
            if buying_wins
            else f"Over {years} years, renting leaves you ahead on these numbers."
        ),
        confidence=_confidence(position, months),
        because=[
            Finding(
                "Net worth after buying",
                f"Including the home's value and the mortgage still owed, after {years} years.",
                amount_minor=buying.closing_net_worth_minor,
            ),
            Finding(
                "Net worth after renting",
                f"With the deposit kept and invested, after {years} years.",
                amount_minor=renting.closing_net_worth_minor,
            ),
            Finding(
                "Difference",
                "What the decision is worth over the window.",
                amount_minor=abs(difference),
            ),
        ],
        costs=[
            Finding(
                "Monthly cost of owning",
                "Payment, tax, insurance and maintenance — not just the mortgage.",
                amount_minor=quote.monthly_cost_minor + monthly_maintenance,
            ),
            Finding(
                "Monthly rent compared",
                "The alternative, for the same period.",
                amount_minor=monthly_rent_minor,
            ),
        ],
        risks=[
            Finding(
                "Property growth is the swing factor",
                "This comparison moves more on the assumed house-price growth than on anything you control.",
            ),
            Finding(
                "Moving costs are not modelled",
                "Buying and selling both carry fees that a ten-year window may not absorb.",
            ),
        ],
        assumptions=[
            f"Maintenance at {maintenance_rate:.1%} of the property's value a year.",
            "Rent held flat in today's money and inflated with everything else.",
            f"Property appreciating {base.annual_property_growth:.1%} a year — the assumption "
            "this answer is most sensitive to.",
            "The renter keeps the deposit rather than spending it, or the comparison is rigged.",
        ],
    )


# ---------------------------------------------------------------------------
# "Buy and let out"
# ---------------------------------------------------------------------------
def buy_and_let_out(
    *,
    position: FinancialPosition,
    property_price_minor: int,
    deposit_minor: int,
    annual_rate: float,
    years: int = 25,
    expected_monthly_rent_minor: int,
    monthly_service_minor: int = 0,
    vacancy_rate: float = 0.08,
    agent_fee_rate: float = kenya.LETTING_AGENT_FEE_RATE,
    tax_rate: float = kenya.RENTAL_INCOME_TAX_RATE,
    monthly_repairs_minor: int = 0,
    monthly_own_rent_minor: int = 0,
    urban: bool = True,
) -> Decision:
    """Buy a property to let, while optionally still paying your own rent.

    Net monthly cost = own rent + mortgage + service − rental income after
    vacancy, agent fees and tax. That is the figure a buy-to-let advert
    leaves out, and the one a household actually feels.
    """
    quote = calc.mortgage(
        property_price_minor=property_price_minor,
        deposit_minor=deposit_minor,
        annual_rate=annual_rate,
        years=years,
    )
    yields = kenya.rental_yield(
        property_price_minor=property_price_minor,
        expected_monthly_rent_minor=expected_monthly_rent_minor,
        vacancy_rate=vacancy_rate,
        agent_fee_rate=agent_fee_rate,
        tax_rate=tax_rate,
        monthly_service_minor=monthly_service_minor,
        monthly_repairs_minor=monthly_repairs_minor,
    )
    upfront = kenya.purchase_upfront_costs(
        property_price_minor=property_price_minor,
        deposit_minor=deposit_minor,
        urban=urban,
    )
    net_monthly = (
        monthly_own_rent_minor
        + quote.monthly_payment_minor
        + monthly_service_minor
        - yields.net_monthly_income_minor
    )
    income = position.monthly_net_income_minor
    share = net_monthly / income if income else None

    if deposit_minor + upfront.stamp_duty_minor + upfront.legal_fees_minor > position.liquid_minor:
        verdict, headline = Verdict.NO, "Completion costs take more cash than you hold."
    elif net_monthly > 0 and share is not None and share > TOTAL_DEBT_CEILING:
        verdict, headline = Verdict.TIGHT, "The property costs more each month than it returns."
    elif net_monthly > 0:
        verdict, headline = (
            Verdict.YES_WITH_CARE,
            "It runs at a monthly shortfall — only if the rest of the budget absorbs it.",
        )
    else:
        verdict, headline = Verdict.YES, "After vacancy, agent and tax, the rent covers the mortgage."

    return Decision(
        question="Should I buy this to let out?",
        verdict=verdict,
        headline=headline,
        confidence=_confidence(position, years * 12),
        because=[
            Finding(
                "Net monthly cost",
                "Own rent + mortgage + service − net rental income.",
                amount_minor=net_monthly,
            ),
            Finding(
                "Gross rental yield",
                f"{yields.gross_yield:.1%} of purchase price.",
                percent=yields.gross_yield,
            ),
            Finding(
                "Net rental yield",
                f"{yields.net_yield:.1%} after vacancy, agent, tax and running costs.",
                percent=yields.net_yield,
            ),
        ],
        costs=[
            Finding(
                "Cash on completion",
                "Deposit, stamp duty, legal and valuation.",
                amount_minor=upfront.total_minor,
            ),
            Finding(
                "Mortgage payment",
                "Quoted instalment, before service or voids.",
                amount_minor=quote.monthly_payment_minor,
            ),
        ],
        risks=[
            Finding("Empty months", f"Vacancy modelled at {vacancy_rate:.0%} of the year."),
            Finding(
                "Tax on rent",
                f"Residential rental income tax at {tax_rate:.1%} (rates as of {kenya.RATES_AS_OF.isoformat()}).",
            ),
        ],
        assumptions=yields.assumptions + upfront.assumptions + quote.assumptions,
    )


# ---------------------------------------------------------------------------
# "Build"
# ---------------------------------------------------------------------------
def build_a_house(
    *,
    position: FinancialPosition,
    land_cost_minor: int,
    construction_cost_minor: int,
    overrun_buffer: float = 0.20,
    annual_rate: float = 0.0,
    years: int = 15,
    deposit_minor: int = 0,
    monthly_own_rent_minor: int = 0,
    extra_km: float = 0.0,
    cost_per_km_minor: int = 0,
    working_days: int = 22,
    construction_months: int = 18,
) -> Decision:
    """Land + build, with an overrun buffer and the rent you keep paying until handover."""
    buffered = construction_cost_minor + round(construction_cost_minor * overrun_buffer)
    total = land_cost_minor + buffered
    commute = calc.commute_cost(
        extra_km=extra_km, cost_per_km_minor=cost_per_km_minor, working_days=working_days
    )
    borrowed = max(0, total - deposit_minor)
    payment = calc.level_payment_minor(borrowed, annual_rate, years * 12) if borrowed else 0
    funding_gap = max(0, total - deposit_minor - position.liquid_minor)
    rent_during = monthly_own_rent_minor * construction_months
    cash_needed = deposit_minor + rent_during

    if funding_gap > 0:
        verdict, headline = Verdict.NO, "There is a funding gap before a single brick is laid."
    elif cash_needed > position.liquid_minor:
        verdict, headline = (
            Verdict.TIGHT,
            "The land deposit plus rent during the build empties the emergency fund.",
        )
    elif (
        payment
        and position.monthly_net_income_minor
        and payment / position.monthly_net_income_minor > HOUSING_CEILING
    ):
        verdict, headline = (
            Verdict.TIGHT,
            "The loan that finishes the build takes more than a third of take-home.",
        )
    else:
        verdict, headline = Verdict.YES, "The build is funded, with the overrun buffer included."

    return Decision(
        question="Should I build rather than buy?",
        verdict=verdict,
        headline=headline,
        confidence=Confidence.ASSUMED,
        because=[
            Finding(
                "Land plus buffered construction",
                f"Construction includes a {overrun_buffer:.0%} overrun buffer.",
                amount_minor=total,
            ),
            Finding(
                "Funding gap",
                "What you still need after cash on hand and the deposit.",
                amount_minor=funding_gap,
            ),
            Finding("Monthly loan if you borrow the rest", f"Over {years} years.", amount_minor=payment),
        ],
        costs=[
            Finding(
                "Rent paid during the build",
                f"{construction_months} months of the current rent.",
                amount_minor=rent_during,
            ),
            Finding(
                "Extra commute",
                "Round-trip extra km × working days × cost/km.",
                amount_minor=commute.monthly_cost_minor,
            ),
        ],
        risks=[
            Finding(
                "Overrun",
                f"A further 20 points on top of the {overrun_buffer:.0%} buffer would add {round(construction_cost_minor * 0.20)}.",
            ),
            Finding("The rent does not stop", "You pay rent until handover, which most build quotes ignore."),
        ],
        assumptions=[
            f"Overrun buffer {overrun_buffer:.0%} of construction cost.",
            commute.assumptions[0],
            "No stamp duty on a completed house you already own the land for; land purchase duty is not modelled here.",
        ],
    )


# ---------------------------------------------------------------------------
# Rent vs Buy vs Build — same inputs, three options
# ---------------------------------------------------------------------------
def rent_buy_build(
    *,
    position: FinancialPosition,
    monthly_rent_minor: int,
    property_price_minor: int,
    deposit_minor: int,
    annual_rate: float,
    years: int = 10,
    land_cost_minor: int = 0,
    construction_cost_minor: int = 0,
    overrun_buffer: float = 0.20,
    extra_km: float = 0.0,
    cost_per_km_minor: int = 0,
) -> Decision:
    """Side-by-side: keep renting, buy and live in it, or build."""
    renting = buy_or_rent(
        position=position,
        property_price_minor=property_price_minor,
        deposit_minor=deposit_minor,
        annual_rate=annual_rate,
        monthly_rent_minor=monthly_rent_minor,
        years=years,
    )
    live_in = can_i_afford_mortgage(
        position=position,
        property_price_minor=property_price_minor,
        deposit_minor=deposit_minor,
        annual_rate=annual_rate,
        years=25,
    )
    build = build_a_house(
        position=position,
        land_cost_minor=land_cost_minor or property_price_minor // 3,
        construction_cost_minor=construction_cost_minor or (property_price_minor * 2) // 3,
        overrun_buffer=overrun_buffer,
        annual_rate=annual_rate,
        deposit_minor=deposit_minor,
        monthly_own_rent_minor=monthly_rent_minor,
        extra_km=extra_km,
        cost_per_km_minor=cost_per_km_minor,
    )
    # Rank by whether each option is viable, then by the cash it leaves.
    ranked = [
        ("Keep renting", renting),
        ("Buy and live in it", live_in),
        ("Build", build),
    ]
    viable = [name for name, d in ranked if d.verdict in (Verdict.YES, Verdict.YES_WITH_CARE)]
    headline = (
        f"{viable[0]} is the option that clears the tests."
        if viable
        else "None of the three options is comfortable on these numbers."
    )
    verdict = Verdict.YES if viable else Verdict.NO
    return Decision(
        question="Rent, buy, or build?",
        verdict=verdict,
        headline=headline,
        confidence=Confidence.MIXED,
        because=[
            Finding(
                f"{name}: {d.verdict}",
                d.headline,
                amount_minor=d.because[0].amount_minor if d.because else None,
            )
            for name, d in ranked
        ],
        costs=[c for _, d in ranked for c in d.costs[:1]],
        risks=[r for _, d in ranked for r in d.risks[:1]],
        alternatives=[
            Finding(
                "Same inputs",
                "Rent, purchase price, deposit, rate and build costs were held still across the three options.",
            )
        ],
        assumptions=[
            "Three options, one set of numbers — the comparison is only honest if nothing else changes.",
            *renting.assumptions[:2],
        ],
    )


# ---------------------------------------------------------------------------
# School fees
# ---------------------------------------------------------------------------
def school_fees_plan(
    *,
    position: FinancialPosition,
    fee_per_term_minor: int,
    children: int = 1,
    terms_per_year: int = 3,
) -> Decision:
    """Term-by-term school-fee cash flow against take-home."""
    plan = calc.school_fees(
        fee_per_term_minor=fee_per_term_minor, children=children, terms_per_year=terms_per_year
    )
    income = position.monthly_net_income_minor
    share = plan.monthly_average_minor / income if income else None
    if share is not None and share > 0.25:
        verdict, headline = Verdict.TIGHT, "Fees take more than a quarter of take-home once averaged monthly."
    elif plan.term_cashflows_minor[0] > position.liquid_minor:
        verdict, headline = Verdict.NO, "The next term's bill is larger than the cash you hold."
    else:
        verdict, headline = Verdict.YES, "The term bills fit, if you save the monthly average in between."

    return Decision(
        question="Can I cover school fees?",
        verdict=verdict,
        headline=headline,
        confidence=Confidence.MEASURED if income else Confidence.ASSUMED,
        because=[
            Finding(
                "Annual total",
                f"{children} child(ren) × {terms_per_year} terms.",
                amount_minor=plan.annual_total_minor,
            ),
            Finding(
                "Monthly average",
                "What to set aside each month so the lumps do not surprise you.",
                amount_minor=plan.monthly_average_minor,
            ),
            Finding(
                "Each term",
                "The cash that leaves three times a year.",
                amount_minor=plan.term_cashflows_minor[0],
            ),
        ],
        costs=[
            Finding(
                "Share of take-home",
                (
                    f"{share:.0%} of net income."
                    if share is not None
                    else "No recorded income to measure against."
                ),
            ),
        ],
        assumptions=plan.assumptions,
    )


# ---------------------------------------------------------------------------
# Commute
# ---------------------------------------------------------------------------
def commute_cost_decision(
    *,
    position: FinancialPosition,
    extra_km: float,
    cost_per_km_minor: int,
    working_days: int = 22,
) -> Decision:
    result = calc.commute_cost(
        extra_km=extra_km, cost_per_km_minor=cost_per_km_minor, working_days=working_days
    )
    income = position.monthly_net_income_minor
    share = result.monthly_cost_minor / income if income else None
    verdict = Verdict.TIGHT if share is not None and share > 0.10 else Verdict.YES
    return Decision(
        question="What does the extra commute cost?",
        verdict=verdict,
        headline=(
            "The extra distance is a material slice of take-home."
            if verdict == Verdict.TIGHT
            else "The extra commute is a cost, and here is the monthly figure."
        ),
        confidence=Confidence.MEASURED,
        because=[
            Finding(
                "Monthly extra commute",
                f"{extra_km} km extra × 2 × {working_days} days × cost/km.",
                amount_minor=result.monthly_cost_minor,
            )
        ],
        assumptions=result.assumptions,
    )


# ---------------------------------------------------------------------------
# SACCO loan
# ---------------------------------------------------------------------------
def sacco_loan_decision(
    *,
    position: FinancialPosition,
    amount_minor: int,
    shares_held_minor: int = 0,
    share_multiple: float = kenya.SACCO_SHARE_MULTIPLE,
    annual_rate: float = kenya.SACCO_TYPICAL_RATE,
    months: int = 36,
) -> Decision:
    """Can this household take this SACCO loan given the shares they already hold."""
    quote = calc.sacco_loan(
        amount_minor=amount_minor,
        shares_held_minor=shares_held_minor,
        share_multiple=share_multiple,
        annual_rate=annual_rate,
        months=months,
    )
    income = position.monthly_net_income_minor
    extra = quote.extra_shares_needed_minor
    existing_service = sum(d.monthly_payment_minor for d in position.debts)
    share = (quote.monthly_payment_minor + existing_service) / income if income else None
    leftover = position.liquid_minor - extra

    if amount_minor <= 0:
        verdict, headline = Verdict.UNKNOWN, "A loan of nothing does not need a verdict."
    elif extra > position.liquid_minor:
        verdict, headline = (
            Verdict.NO,
            "Unlocking this loan takes more extra shares than you hold in cash.",
        )
    elif share is not None and share > TOTAL_DEBT_CEILING:
        verdict, headline = (
            Verdict.TIGHT,
            "The instalment plus existing debts take more than a third of take-home.",
        )
    elif leftover < position.monthly_expenses_minor * RUNWAY_FLOOR_MONTHS:
        verdict, headline = (
            Verdict.YES_WITH_CARE,
            "The loan fits, but buying the extra shares leaves the emergency fund thin.",
        )
    else:
        verdict, headline = Verdict.YES, "The SACCO will lend this, and the instalment fits."

    alternatives = []
    if quote.capacity_minor < amount_minor:
        alternatives.append(
            Finding(
                "What current shares already unlock",
                "The largest loan this SACCO would grant without buying more shares.",
                amount_minor=quote.capacity_minor,
            )
        )

    return Decision(
        question="Can I take this SACCO loan?",
        verdict=verdict,
        headline=headline,
        confidence=Confidence.MEASURED if income else Confidence.ASSUMED,
        because=[
            Finding(
                "Borrowing power on shares held",
                f"{share_multiple:g}× deposits already in the SACCO.",
                amount_minor=quote.capacity_minor,
            ),
            Finding(
                "Monthly instalment",
                f"{months} months at {annual_rate:.1%}.",
                amount_minor=quote.monthly_payment_minor,
            ),
            Finding(
                "Share of take-home",
                (
                    f"{share:.0%} of net income including existing debts, against a "
                    f"{TOTAL_DEBT_CEILING:.0%} guide."
                    if share is not None
                    else "No recorded income to measure against."
                ),
                percent=round(share, 4) if share is not None else None,
            ),
        ],
        costs=[
            Finding(
                "Extra shares to unlock the loan",
                "Cash that has to go into the SACCO before the loan is disbursed.",
                amount_minor=extra,
            ),
            Finding(
                "Interest over the term",
                f"Total paid to borrow, over {months} months.",
                amount_minor=quote.total_interest_minor,
            ),
        ],
        risks=(
            [
                Finding(
                    "Everything committed",
                    "Existing debts plus this instalment leave little room for a bad month.",
                    percent=round(share, 4),
                )
            ]
            if share is not None and share > HOUSING_CEILING
            else []
        ),
        alternatives=alternatives,
        assumptions=quote.assumptions
        + [
            f"Debt-service guide of {TOTAL_DEBT_CEILING:.0%} of net income, existing loans included.",
            "Your income and cash are the figures measured from your own ledger.",
        ],
    )
