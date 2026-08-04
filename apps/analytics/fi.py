"""Financial independence: when does work become optional?

The single most-asked question in any advisory sit-down, and the one personal
finance apps almost never answer. The arithmetic is not the hard part — it is
being honest about the assumptions, which is where this module spends most of
its care:

* **The FI number is spending-derived, not income-derived.** You are
  financially independent when a sustainable withdrawal covers what you
  actually spend — measured from the ledger's own months, not from a
  questionnaire answer that was aspirational the day it was typed.
* **Returns are stated as a band, never a number.** The difference between 4%
  and 6% real return is routinely a decade of someone's life. One figure would
  be a lie of precision; three figures with the assumption attached is a
  forecast a person can argue with.
* **"Never, at the current pace" is a legitimate answer** — and it converts
  the question into the actionable inverse: what monthly saving *would* get
  there in fifteen years. An advisor who answered "never" and stopped would be
  fired; so would this module.
* **No birthdate is collected.** The answer is "in about N years — around
  2041", not an age. Years-from-now says the same thing without the product
  needing to hold one more piece of identity it has no other use for.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

from apps.finance import selectors as finance_selectors

from .filters import Period, ReportFilters
from .reports import _currency_for, _month_range, _monthly_totals

#: Trailing complete months of ledger history the measurement reads.
HISTORY_MONTHS = 6

#: Withdrawal rate the FI number is derived from. 4% is the convention the
#: entire FIRE literature argues about; it is stated in the payload so the
#: reader knows exactly which convention they are looking at.
SAFE_WITHDRAWAL_RATE = 0.04

#: Real (after-inflation) annual returns the projection brackets with.
RETURN_BAND = (0.04, 0.05, 0.06)

#: The conversational anchor for the "never" case.
FALLBACK_HORIZON_YEARS = 15

#: Beyond this, "reachable" is only true of the arithmetic. A 1,000 pot with
#: zero saving does compound to any number eventually — in a century or two —
#: and reporting that as a date would be technically correct and humanly
#: false. Nobody plans across sixty years of accumulation.
NEVER_HORIZON_YEARS = 60


class NotEnoughHistoryError(Exception):
    """Too little ledger history to measure spending honestly."""


@dataclass(frozen=True)
class FIBandPoint:
    real_return: float
    #: None when unreachable at the current pace.
    years: float | None
    around_year: int | None


@dataclass(frozen=True)
class FIProjection:
    currency: str
    as_of: date
    months_measured: int
    #: Median monthly outflow — what independence must actually cover.
    monthly_spending_minor: int
    #: Median monthly (inflow − outflow) across measured months. Can be <= 0.
    monthly_savings_minor: int
    net_worth_minor: int
    fi_number_minor: int
    swr: float
    progress_pct: float
    band: list[FIBandPoint] = field(default_factory=list)
    #: True when the middle-of-band projection cannot reach the number.
    never_at_current_pace: bool = False
    #: The actionable inverse for the never case: monthly saving that reaches
    #: the number in FALLBACK_HORIZON_YEARS at the middle return.
    required_monthly_for_horizon_minor: int | None = None
    caveats: list[str] = field(default_factory=list)


def _monthly_rate(annual: float) -> float:
    return (1 + annual) ** (1 / 12) - 1


def _months_to_target(net: int, monthly_saving: int, target: int, annual_return: float) -> float | None:
    """Months until net worth reaches the target, or None when it never does.

    Future value of the current pot plus a level monthly contribution:
    ``net·(1+i)^n + s·((1+i)^n − 1)/i = target`` solves in closed form for
    ``(1+i)^n``, so no iteration and no convergence edge cases.
    """
    if net >= target:
        return 0.0
    i = _monthly_rate(annual_return)
    numerator = target * i + monthly_saving
    denominator = net * i + monthly_saving
    if denominator <= 0 or numerator <= denominator:
        # Growth plus saving never overtakes the target.
        return None
    return math.log(numerator / denominator) / math.log(1 + i)


def _required_monthly(net: int, target: int, years: int, annual_return: float) -> int:
    i = _monthly_rate(annual_return)
    n = years * 12
    growth = (1 + i) ** n
    needed = (target - net * growth) * i / (growth - 1)
    return max(0, math.ceil(needed))


def project(*, as_of: date | None = None) -> FIProjection:
    as_of = as_of or timezone.localdate()

    filters = ReportFilters(period=Period.LAST_12_MONTHS)
    currency = _currency_for(filters)
    start, end = filters.window(as_of=as_of)
    monthly = _monthly_totals(filters, start, end)

    # Complete months only: the current month always looks frugal because it
    # is not finished, and the projection would inherit that optimism.
    month_starts = [m for m in _month_range(start, end) if m < as_of.replace(day=1)]
    spend_samples: list[int] = []
    save_samples: list[int] = []
    for month in month_starts[-HISTORY_MONTHS:]:
        flows = monthly.get(month)
        if not flows:
            continue
        outflow = flows["outflow_minor"]
        inflow = flows["inflow_minor"]
        if outflow <= 0 and inflow <= 0:
            continue
        spend_samples.append(outflow)
        if inflow > 0:
            save_samples.append(inflow - outflow)

    if len(spend_samples) < 2:
        raise NotEnoughHistoryError(
            "Fewer than two complete months of spending on record — the FI number "
            "would be a guess about your life, not a measurement of it."
        )

    monthly_spending = int(statistics.median(spend_samples))
    monthly_savings = int(statistics.median(save_samples)) if save_samples else 0
    if monthly_spending <= 0:
        raise NotEnoughHistoryError("No outflows recorded — nothing for independence to cover.")

    net = next((row.net_minor for row in finance_selectors.net_worth() if row.currency == currency), 0)

    fi_number = round(monthly_spending * 12 / SAFE_WITHDRAWAL_RATE)
    progress = round(max(0, net) / fi_number * 100, 1) if fi_number else 0.0

    band: list[FIBandPoint] = []
    for annual in RETURN_BAND:
        months = _months_to_target(net, monthly_savings, fi_number, annual)
        if months is not None and months / 12 > NEVER_HORIZON_YEARS:
            months = None
        years = round(months / 12, 1) if months is not None else None
        band.append(
            FIBandPoint(
                real_return=annual,
                years=years,
                around_year=(as_of.year + round(months / 12)) if months is not None else None,
            )
        )

    middle = band[len(band) // 2]
    never = middle.years is None
    required = (
        _required_monthly(net, fi_number, FALLBACK_HORIZON_YEARS, RETURN_BAND[len(RETURN_BAND) // 2])
        if never
        else None
    )

    caveats = []
    if not save_samples:
        caveats.append(
            "No months with recorded income, so the saving rate is treated as zero — "
            "add income sources or categorise income transactions to sharpen this."
        )
    if len(spend_samples) < HISTORY_MONTHS:
        caveats.append(
            f"Only {len(spend_samples)} complete months of history; the spending figure "
            "firms up as more months land."
        )
    caveats.append(
        "Returns are real (after inflation); today's money throughout. The number moves "
        "with your actual spending, which is the point."
    )

    return FIProjection(
        currency=currency,
        as_of=as_of,
        months_measured=len(spend_samples),
        monthly_spending_minor=monthly_spending,
        monthly_savings_minor=monthly_savings,
        net_worth_minor=net,
        fi_number_minor=fi_number,
        swr=SAFE_WITHDRAWAL_RATE,
        progress_pct=progress,
        band=band,
        never_at_current_pace=never,
        required_monthly_for_horizon_minor=required,
        caveats=caveats,
    )
