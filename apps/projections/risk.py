"""Risk — the exposures a projection line does not show.

A projection answers "where does this go". It does not answer "what would have
to go wrong for this to stop being true", and those are different questions
with different remedies. A household can be on a beautiful trajectory and one
missed payslip from an overdraft; the line looks the same either way.

Five exposures, each measured from the position rather than asked about:

*Runway* — months of expenses covered by liquid savings. The oldest measure in
personal finance and still the most predictive of whether a bad month becomes a
bad year.

*Leverage* — debt against assets. Not a problem in itself; a problem when it
sits alongside a thin runway, which is why the summary reads them together.

*Debt service* — what fraction of income is already committed to debt before
anything is chosen. Above roughly a third, most of the levers a person has stop
working.

*Income concentration* — how much of the household's income comes from its
single largest source. One employer is one decision away from zero income, and
a projection built on that income never says so.

*Sequence exposure* — how much of net worth sits in assets whose order of
returns matters. A retiree with 90% in equities and a 4% withdrawal is exposed
to something an average return figure genuinely cannot express.

Each is scored 0..100 where **higher is safer**, matching the existing health
score's direction so the two never contradict each other on screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .engine import FinancialPosition

#: Runway targets, in months. Three is the conventional floor and six the
#: conventional comfort; both are stated in the output rather than assumed.
RUNWAY_FLOOR_MONTHS = 3
RUNWAY_TARGET_MONTHS = 6

#: Debt service above this fraction of income is where the research and the
#: lenders broadly agree things get fragile.
DEBT_SERVICE_CEILING = 0.36


@dataclass(frozen=True)
class RiskFactor:
    key: str
    label: str
    #: 0..100, higher is safer — same direction as the health score.
    score: int
    #: The measured quantity, in whatever unit the label implies.
    value: float
    detail: str
    #: What would reduce this exposure. Absent when the factor is already fine.
    remedy: str = ""


@dataclass(frozen=True)
class RiskProfile:
    currency: str
    #: Weakest-first: the list is a queue, not a report card.
    factors: list[RiskFactor] = field(default_factory=list)
    #: The lowest factor score. A household is as resilient as its weakest
    #: exposure, not as its average one — averaging would let a large pot hide
    #: a total absence of liquidity.
    resilience: int = 0
    headline: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def weakest(self) -> RiskFactor | None:
        return self.factors[0] if self.factors else None


def _band(value: float, floor: float, target: float) -> int:
    """Linear 0..100 between a floor and a target, clamped."""
    if target <= floor:
        return 100 if value >= target else 0
    return int(max(0, min(100, round((value - floor) / (target - floor) * 100))))


def assess(
    *,
    position: FinancialPosition,
    income_sources: list[int] | None = None,
) -> RiskProfile:
    """Measure the household's exposures.

    `income_sources` is the monthly amount from each distinct source. When it
    is not supplied, concentration cannot be measured honestly and the factor
    is omitted rather than assumed — reporting "100, well diversified" for a
    household whose sources we never counted would be worse than silence.
    """
    factors: list[RiskFactor] = []
    notes: list[str] = []

    monthly_expenses = position.monthly_expenses_minor
    income = position.monthly_net_income_minor
    debt_payments = sum(d.monthly_payment_minor for d in position.debts)
    debt_balance = sum(d.balance_minor for d in position.debts)
    assets = position.liquid_minor + position.investment_minor + position.other_assets_minor

    # -- runway -------------------------------------------------------------
    if monthly_expenses > 0:
        runway = position.liquid_minor / monthly_expenses
        factors.append(
            RiskFactor(
                key="runway",
                label="Emergency runway",
                score=_band(runway, 0, RUNWAY_TARGET_MONTHS),
                value=round(runway, 1),
                detail=(
                    f"{runway:.1f} months of spending held in cash "
                    f"(the usual floor is {RUNWAY_FLOOR_MONTHS}, comfort is {RUNWAY_TARGET_MONTHS})."
                ),
                remedy=(
                    ""
                    if runway >= RUNWAY_TARGET_MONTHS
                    else "Hold more in cash before committing to anything with a monthly payment."
                ),
            )
        )
    else:
        notes.append("No recorded spending, so runway cannot be measured.")

    # -- debt service -------------------------------------------------------
    if income > 0:
        service = debt_payments / income
        factors.append(
            RiskFactor(
                key="debt_service",
                label="Income already committed to debt",
                score=_band(DEBT_SERVICE_CEILING - service, 0, DEBT_SERVICE_CEILING),
                value=round(service, 4),
                detail=(
                    f"{service:.0%} of income goes to debt payments "
                    f"(fragile above {DEBT_SERVICE_CEILING:.0%})."
                ),
                remedy=(
                    ""
                    if service < DEBT_SERVICE_CEILING * 0.7
                    else "Clearing the highest-rate balance frees the most room per shilling."
                ),
            )
        )
    else:
        notes.append("No recorded income, so debt service cannot be measured as a share of it.")

    # -- leverage -----------------------------------------------------------
    if assets > 0:
        leverage = debt_balance / assets
        factors.append(
            RiskFactor(
                key="leverage",
                label="Debt against assets",
                score=_band(1 - leverage, 0.4, 1.0),
                value=round(leverage, 4),
                detail=f"Debt is {leverage:.0%} of what you hold.",
                remedy="" if leverage < 0.4 else "Either balance grows or debt shrinks; both work.",
            )
        )
    elif debt_balance > 0:
        factors.append(
            RiskFactor(
                key="leverage",
                label="Debt against assets",
                score=0,
                value=1.0,
                detail="Debt with no recorded assets behind it.",
                remedy="Adding your accounts and holdings may show this is better than it looks.",
            )
        )

    # -- income concentration ----------------------------------------------
    if income_sources:
        total = sum(income_sources)
        if total > 0:
            largest = max(income_sources) / total
            factors.append(
                RiskFactor(
                    key="income_concentration",
                    label="Reliance on one income",
                    score=_band(1 - largest, 0.0, 0.5),
                    value=round(largest, 4),
                    detail=(
                        f"{largest:.0%} of income comes from a single source"
                        f"{' — all of it' if largest >= 0.99 else ''}."
                    ),
                    remedy=(
                        ""
                        if largest < 0.7
                        else "Nothing to fix today, but it is the reason the runway matters."
                    ),
                )
            )
    else:
        notes.append(
            "Income sources are not itemised, so reliance on a single employer is not "
            "measured here rather than being guessed at."
        )

    # -- sequence exposure --------------------------------------------------
    if assets > 0:
        volatile_share = position.investment_minor / assets
        factors.append(
            RiskFactor(
                key="sequence",
                label="Exposure to when returns arrive",
                score=_band(1 - volatile_share, 0.0, 0.8),
                value=round(volatile_share, 4),
                detail=(
                    f"{volatile_share:.0%} of assets are invested, where the *order* of "
                    "returns changes the outcome, not just the average."
                ),
                remedy=(
                    ""
                    if volatile_share < 0.6
                    else "Holding a couple of years of spending outside the market is what "
                    "removes the need to sell into a fall."
                ),
            )
        )

    factors.sort(key=lambda f: f.score)
    resilience = factors[0].score if factors else 0

    weakest = factors[0] if factors else None
    if weakest is None:
        headline = "Not enough recorded to measure resilience yet."
    elif weakest.score >= 70:
        headline = "No single exposure stands out as fragile."
    elif weakest.score >= 40:
        headline = f"{weakest.label} is the weak point worth attention."
    else:
        headline = f"{weakest.label} is the exposure that would bite first."

    notes.append(
        "Resilience is the weakest factor, not the average — a household is as exposed "
        "as its thinnest cover, and averaging lets a large balance hide having no cash."
    )

    return RiskProfile(
        currency=position.currency,
        factors=factors,
        resilience=resilience,
        headline=headline,
        notes=notes,
    )
