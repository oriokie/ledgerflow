"""Sensitivity — which assumption is actually load-bearing?

Monte Carlo says how wide the spread is. This says *what is making it wide*,
which is the more actionable of the two: if a plan collapses on the inflation
assumption and barely notices the return assumption, then the argument worth
having is about inflation, and no amount of portfolio tinkering addresses it.

The method is one-at-a-time. Each assumption is moved to a low and a high value
with everything else held at baseline, and the resulting swing in closing net
worth is recorded. That deliberately ignores interaction effects — inflation
and interest rates do not move independently in the real world — and the report
says so, because a tornado chart implying independence would be a claim.

It also answers the specific questions the product promises in plain terms:
*what happens if inflation reaches 10%*, *what if rates rise* — those are not
special cases here, they are a `what_if` over the same machinery, so the number
on the "what if inflation hits 10%" card and the number in the inflation bar of
the tornado are the same number by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .engine import (
    CompiledEvent,
    DebtPosition,
    EconomicAssumptions,
    FinancialPosition,
    project,
)

#: The assumptions worth testing, with the low/high each is moved to.
#: Absolute values rather than relative swings: "inflation at 10%" is a
#: sentence a person can hold an opinion about; "inflation +40% relative" is not.
LEVERS: dict[str, tuple[str, float, float]] = {
    "annual_inflation": ("Inflation", 0.02, 0.10),
    "annual_salary_growth": ("Pay growth", 0.00, 0.06),
    "annual_investment_return": ("Investment return", 0.02, 0.10),
    "annual_property_growth": ("Property growth", 0.00, 0.08),
    "effective_tax_rate": ("Effective tax", 0.00, 0.35),
}

#: Debt rates are not an `EconomicAssumptions` field — they live on each debt —
#: so "what if interest rates rise" is applied as a shift across every debt the
#: household holds. Expressed in percentage points, which is how rate rises are
#: quoted and argued about.
RATE_SHIFTS = (-0.02, 0.05)


@dataclass(frozen=True)
class Swing:
    lever: str
    label: str
    low_value: float
    high_value: float
    low_closing_minor: int
    high_closing_minor: int
    baseline_closing_minor: int

    @property
    def spread_minor(self) -> int:
        """How much this one assumption moves the answer. The ranking key."""
        return abs(self.high_closing_minor - self.low_closing_minor)

    @property
    def direction(self) -> str:
        """Whether a higher value helps or hurts. Not always obvious — higher
        inflation hurts, higher property growth helps, higher pay growth helps
        but by less than people expect once it is taxed."""
        if self.high_closing_minor > self.low_closing_minor:
            return "higher is better"
        return "higher is worse"


@dataclass(frozen=True)
class SensitivityResult:
    currency: str
    months: int
    baseline_closing_minor: int
    #: Ordered most-influential first — the tornado.
    swings: list[Swing] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def dominant(self) -> Swing | None:
        return self.swings[0] if self.swings else None


def _closing(
    position: FinancialPosition,
    assumptions: EconomicAssumptions,
    events: list[CompiledEvent],
    months: int,
) -> int:
    return project(
        position=position, assumptions=assumptions, events=events, months=months
    ).closing_net_worth_minor


def _shift_debt_rates(position: FinancialPosition, delta: float) -> FinancialPosition:
    """Every debt's rate moved by `delta`, floored at zero.

    A rate rise does not reduce the payment, so the payment is held: that is
    what makes a rise bite, and modelling the payment rising with it would
    quietly convert an affordability problem into a cash-flow one.
    """
    shifted = tuple(
        DebtPosition(
            label=d.label,
            balance_minor=d.balance_minor,
            annual_rate=max(0.0, d.annual_rate + delta),
            monthly_payment_minor=d.monthly_payment_minor,
        )
        for d in position.debts
    )
    return replace(position, debts=shifted)


def analyse(
    *,
    position: FinancialPosition,
    assumptions: EconomicAssumptions | None = None,
    events: list[CompiledEvent] | None = None,
    months: int = 120,
) -> SensitivityResult:
    """Rank the assumptions by how much each moves the outcome on its own."""
    base = assumptions or EconomicAssumptions()
    events = list(events or [])
    baseline = _closing(position, base, events, months)

    swings: list[Swing] = []
    for field_name, (label, low, high) in LEVERS.items():
        low_closing = _closing(position, replace(base, **{field_name: low}), events, months)
        high_closing = _closing(position, replace(base, **{field_name: high}), events, months)
        swings.append(
            Swing(
                lever=field_name,
                label=label,
                low_value=low,
                high_value=high,
                low_closing_minor=low_closing,
                high_closing_minor=high_closing,
                baseline_closing_minor=baseline,
            )
        )

    if position.debts:
        low_rate, high_rate = RATE_SHIFTS
        swings.append(
            Swing(
                lever="debt_rates",
                label="Interest rates on what you owe",
                low_value=low_rate,
                high_value=high_rate,
                low_closing_minor=_closing(_shift_debt_rates(position, low_rate), base, events, months),
                high_closing_minor=_closing(_shift_debt_rates(position, high_rate), base, events, months),
                baseline_closing_minor=baseline,
            )
        )

    swings.sort(key=lambda s: s.spread_minor, reverse=True)

    notes = [
        "Each assumption is moved on its own with the others held still, so the bars "
        "add up to more than reality would: inflation and interest rates move together.",
        "The ranking is what to argue about first, not a prediction of any one of them.",
    ]
    if not position.debts:
        notes.append("No debts on record, so a rate rise has nothing to act on here.")

    return SensitivityResult(
        currency=position.currency,
        months=months,
        baseline_closing_minor=baseline,
        swings=swings,
        notes=notes,
    )


@dataclass(frozen=True)
class WhatIf:
    question: str
    changed: str
    baseline_closing_minor: int
    changed_closing_minor: int
    baseline_trough_minor: int
    changed_trough_minor: int
    #: Whether the change introduces a month the balance goes negative that the
    #: baseline did not have. The single most decision-relevant bit here.
    introduces_shortfall: bool
    notes: list[str] = field(default_factory=list)

    @property
    def delta_minor(self) -> int:
        return self.changed_closing_minor - self.baseline_closing_minor


def what_if(
    *,
    position: FinancialPosition,
    assumptions: EconomicAssumptions | None = None,
    events: list[CompiledEvent] | None = None,
    months: int = 120,
    inflation: float | None = None,
    investment_return: float | None = None,
    salary_growth: float | None = None,
    rate_shift: float | None = None,
) -> WhatIf:
    """Answer one named question — "what if inflation reaches 10%?".

    Shares every line of arithmetic with `analyse`, so the figure on a what-if
    card and the corresponding bar of the tornado cannot disagree.
    """
    base = assumptions or EconomicAssumptions()
    events = list(events or [])

    changed_assumptions = base
    changed_position = position
    described: list[str] = []

    if inflation is not None:
        changed_assumptions = replace(changed_assumptions, annual_inflation=inflation)
        described.append(f"inflation at {inflation:.1%}")
    if investment_return is not None:
        changed_assumptions = replace(changed_assumptions, annual_investment_return=investment_return)
        described.append(f"returns at {investment_return:.1%}")
    if salary_growth is not None:
        changed_assumptions = replace(changed_assumptions, annual_salary_growth=salary_growth)
        described.append(f"pay growth at {salary_growth:.1%}")
    if rate_shift is not None:
        changed_position = _shift_debt_rates(position, rate_shift)
        described.append(f"borrowing rates {rate_shift:+.1%}")

    if not described:
        raise ValueError("a what-if needs at least one assumption to change")

    baseline = project(position=position, assumptions=base, events=events, months=months)
    changed = project(
        position=changed_position, assumptions=changed_assumptions, events=events, months=months
    )

    introduces = baseline.first_negative_month is None and changed.first_negative_month is not None
    notes = [
        "Both lines run through the same engine; only the named assumption differs.",
    ]
    if introduces:
        notes.append(
            "This is the finding that matters: under this assumption the balance goes "
            "negative at some point, and it does not in the baseline."
        )

    return WhatIf(
        question=" and ".join(described),
        changed=", ".join(described),
        baseline_closing_minor=baseline.closing_net_worth_minor,
        changed_closing_minor=changed.closing_net_worth_minor,
        baseline_trough_minor=baseline.lowest_liquid_minor,
        changed_trough_minor=changed.lowest_liquid_minor,
        introduces_shortfall=introduces,
        notes=notes,
    )
