"""What-if: the advisor's modelling session, against the real projections.

A scenario is two numbers — a monthly income change and a monthly spending
change — because that is the vocabulary of every real decision this answers:
a raise, a rent increase, dropping a car, taking a cheaper flat. The engine
re-answers three questions the product already answers for the present:

* what is safe to spend (the cash-flow trough),
* when does the balance first go negative,
* when does work become optional.

Two design rules keep it honest:

1. **The baseline and the scenario go through the same arithmetic.** The
   scenario is never computed as "baseline plus a hand-derived adjustment" —
   both run the projection, so a bug cannot make the comparison flatter than
   reality.
2. **The overlay is spread evenly and says so.** A monthly delta is applied as
   a daily drip across the projection rather than as a lump on an invented
   date. Real changes are lumpy; inventing the lump's date would be a claim,
   and the smooth version understates trough risk *slightly* on the cautious
   side — stated in the response rather than hidden.

The FI leg is where scenarios earn their keep: cutting spending moves the
date twice — once because more is saved, and again because the number itself
(spending / withdrawal rate) shrinks. That double effect is the single most
useful thing an advisor's modelling session teaches, and the response makes
it visible instead of leaving it implied.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.utils import timezone

from apps.finance import cashflow_calendar as cc

from . import fi


@dataclass(frozen=True)
class ScenarioLeg:
    safe_to_spend_minor: int | None
    first_negative_on: date | None
    lowest_balance_minor: int | None
    fi_years: float | None
    fi_number_minor: int | None


@dataclass(frozen=True)
class ScenarioResult:
    currency: str
    as_of: date
    monthly_income_delta_minor: int
    monthly_expense_delta_minor: int
    baseline: ScenarioLeg
    scenario: ScenarioLeg
    notes: list[str]


def _cashflow_leg(calendar, daily_delta: float) -> tuple[int | None, date | None, int | None]:
    """Trough, first negative day and lowest balance with a daily drip applied.

    The drip accumulates: day *n* carries n days of the change, exactly as a
    persistent monthly change would compound through a projection window.
    """
    if calendar is None:
        return None, None, None
    lowest = None
    first_negative = None
    for index, day in enumerate(calendar.days, start=1):
        base = day.expected_low_minor if day.expected_low_minor is not None else day.closing_minor
        adjusted = base + round(daily_delta * index)
        if lowest is None or adjusted < lowest:
            lowest = adjusted
        if first_negative is None and adjusted < 0:
            first_negative = day.day
    if lowest is None:
        lowest = calendar.opening_balance_minor
    return max(0, lowest), first_negative, lowest


def _fi_leg(income_delta: int, expense_delta: int) -> tuple[float | None, int | None]:
    """Years to FI under the scenario, through the same closed form as the
    baseline — with both effects of a spending change applied: the saving rate
    moves, and so does the number itself."""
    try:
        projection = fi.project()
    except fi.NotEnoughHistoryError:
        return None, None

    new_spending = max(0, projection.monthly_spending_minor + expense_delta)
    if new_spending == 0:
        return 0.0, 0
    new_number = round(new_spending * 12 / projection.swr)
    new_savings = projection.monthly_savings_minor + income_delta - expense_delta
    middle_return = fi.RETURN_BAND[len(fi.RETURN_BAND) // 2]
    months = fi._months_to_target(projection.net_worth_minor, new_savings, new_number, middle_return)
    if months is not None and months / 12 > fi.NEVER_HORIZON_YEARS:
        months = None
    return (round(months / 12, 1) if months is not None else None), new_number


def preview(
    *,
    monthly_income_delta_minor: int = 0,
    monthly_expense_delta_minor: int = 0,
    as_of: date | None = None,
) -> ScenarioResult:
    as_of = as_of or timezone.localdate()
    calendar = cc.cashflow_calendar(days=35)
    currency = calendar.currency if calendar else "USD"

    net_monthly = monthly_income_delta_minor - monthly_expense_delta_minor
    daily_delta = net_monthly * 12 / 365

    base_safe, base_negative, base_lowest = _cashflow_leg(calendar, 0.0)
    new_safe, new_negative, new_lowest = _cashflow_leg(calendar, daily_delta)

    base_fi_years, base_fi_number = _fi_leg(0, 0)
    new_fi_years, new_fi_number = _fi_leg(monthly_income_delta_minor, monthly_expense_delta_minor)

    notes = [
        "The change is applied evenly across the projection window; real changes "
        "land on real dates, so treat the trough as slightly optimistic.",
    ]
    if monthly_expense_delta_minor < 0 and base_fi_number and new_fi_number:
        notes.append(
            "Spending cuts count twice for independence: more is saved each month, "
            "and the target itself shrinks with what it has to sustain."
        )
    if calendar is None:
        notes.append("No liquid accounts to project, so the cash-flow leg is empty.")

    return ScenarioResult(
        currency=currency,
        as_of=as_of,
        monthly_income_delta_minor=monthly_income_delta_minor,
        monthly_expense_delta_minor=monthly_expense_delta_minor,
        baseline=ScenarioLeg(
            safe_to_spend_minor=base_safe,
            first_negative_on=base_negative,
            lowest_balance_minor=base_lowest,
            fi_years=base_fi_years,
            fi_number_minor=base_fi_number,
        ),
        scenario=ScenarioLeg(
            safe_to_spend_minor=new_safe,
            first_negative_on=new_negative,
            lowest_balance_minor=new_lowest,
            fi_years=new_fi_years,
            fi_number_minor=new_fi_number,
        ),
        notes=notes,
    )
