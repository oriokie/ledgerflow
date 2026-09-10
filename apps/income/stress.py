"""What happens if one income stream stops.

Pure arithmetic, no ORM, for the same reasons as ``apps.debt.stress``: the
scenario must be directly testable and identically reproducible. The question
is the one personal financial management exists to answer and the product
could not, until now: if this paycheque disappears, can the household still
cover what is already committed?

Commitments are held constant. Bills, debt minimums and recurring expenses do
not vanish because a stream stopped — that is the whole point of the
counterfactual. What changes is the denominator.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StressSnapshot:
    monthly_income_minor: int
    monthly_fixed_minor: int
    committed_minor: int
    free_minor: int
    #: ``None`` when there is no remaining income to be a percentage of.
    committed_pct: float | None
    #: How far commitments exceed remaining income. Zero when they still fit.
    shortfall_minor: int


@dataclass(frozen=True, slots=True)
class SourceStopScenario:
    source_id: str
    source_name: str
    dropped_monthly_minor: int
    currency: str
    before: StressSnapshot
    after: StressSnapshot
    sentence: str


def snapshot(
    *,
    monthly_income_minor: int,
    monthly_fixed_minor: int,
    committed_minor: int,
) -> StressSnapshot:
    """One side of the counterfactual.

    Negative remaining income is clamped to zero rather than reported as a
    negative salary: a household that has lost its last stream earns nothing,
    it does not owe itself a paycheque.
    """
    income = max(0, monthly_income_minor)
    fixed = max(0, monthly_fixed_minor)
    committed = max(0, committed_minor)
    free = income - committed
    pct = round(committed / income * 100, 1) if income > 0 else None
    return StressSnapshot(
        monthly_income_minor=income,
        monthly_fixed_minor=fixed,
        committed_minor=committed,
        free_minor=free,
        committed_pct=pct,
        shortfall_minor=max(0, committed - income),
    )


def if_source_stops(
    *,
    source_id: str,
    source_name: str,
    dropped_monthly_minor: int,
    currency: str,
    monthly_income_minor: int,
    monthly_fixed_minor: int,
    committed_minor: int,
    source_is_fixed: bool,
) -> SourceStopScenario:
    """Recompute committed income as if ``dropped_monthly_minor`` never arrives.

    ``dropped_monthly_minor`` must already be the source's monthly equivalent.
    An ad-hoc stream has no honest monthly figure; callers must refuse before
    they reach here rather than invent one.
    """
    dropped = max(0, dropped_monthly_minor)
    before = snapshot(
        monthly_income_minor=monthly_income_minor,
        monthly_fixed_minor=monthly_fixed_minor,
        committed_minor=committed_minor,
    )
    remaining_fixed = monthly_fixed_minor - dropped if source_is_fixed else monthly_fixed_minor
    after = snapshot(
        monthly_income_minor=monthly_income_minor - dropped,
        monthly_fixed_minor=remaining_fixed,
        committed_minor=committed_minor,
    )
    return SourceStopScenario(
        source_id=source_id,
        source_name=source_name,
        dropped_monthly_minor=dropped,
        currency=currency,
        before=before,
        after=after,
        sentence=_sentence(source_name, before, after),
    )


def _sentence(name: str, before: StressSnapshot, after: StressSnapshot) -> str:
    if after.monthly_income_minor <= 0:
        return f"Without {name} there is no remaining income to cover what is already committed each month."
    if after.shortfall_minor > 0:
        return (
            f"Without {name}, commitments would exceed remaining income "
            "— a shortfall against the month's bills, debt, and recurring spend."
        )
    if before.committed_pct is not None and after.committed_pct is not None:
        if after.committed_pct > before.committed_pct:
            return (
                f"Without {name}, committed share of income would rise from "
                f"{before.committed_pct:.0f}% to {after.committed_pct:.0f}%."
            )
        if after.committed_pct < before.committed_pct:
            return (
                f"Without {name}, committed share of income would fall from "
                f"{before.committed_pct:.0f}% to {after.committed_pct:.0f}%."
            )
    return f"Without {name}, remaining income still covers what is already committed."
