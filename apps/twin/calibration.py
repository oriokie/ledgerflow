"""Marking the twin's homework.

`record()` writes down what is expected of next month. `score()` comes back once
the month has closed and fills in what happened. `accuracy()` reports how well
the product has been predicting this household — including, when it is true,
that it has been predicting badly.

That last part is the whole point. A calibration report that can only improve
is not a measurement, and the honest failure modes are built in:

* a forecast made *after* the month it describes is refused outright;
* an already-scored month is never re-scored, so a prediction cannot be quietly
  restated once the answer is known;
* `trend` can come back "worse", and the copy for that case is written.

**Why median absolute percentage error.** Spending data has months with a car
repair in them. A mean error lets one such month dominate a year of otherwise
decent forecasts and report a household as unpredictable when it is not. The
median answers the question people actually have — "in a typical month, how
close is this?" — and the outliers are visible separately in the sample count.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import ForecastKind, ForecastSnapshot
from .parameters import DigitalTwin


class CalibrationError(Exception):
    """A forecast that cannot honestly be recorded or scored."""


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    start = _month_start(value)
    return (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )


@transaction.atomic
def record(
    *,
    kind: str,
    period: date,
    predicted_minor: int,
    currency: str,
    twin: DigitalTwin | None = None,
    made_on: date | None = None,
) -> ForecastSnapshot:
    """Write down a prediction, with the evidence behind it.

    Refuses a forecast for a month that has already begun. "Predicting" the
    present is not prediction, and allowing it would let the calibration report
    fill up with easy marks.
    """
    made_on = made_on or timezone.localdate()
    period = _month_start(period)
    if period <= _month_start(made_on):
        raise CalibrationError(
            "A forecast has to be about a month that has not started yet — otherwise "
            "it is a description, and scoring it would flatter the record."
        )
    if kind not in ForecastKind.values:
        raise CalibrationError(f"unknown forecast kind: {kind!r}")

    try:
        return ForecastSnapshot.objects.create(
            kind=kind,
            period=period,
            made_on=made_on,
            predicted_minor=predicted_minor,
            currency=currency,
            months_observed=twin.months_observed if twin else 0,
            confidence=twin.confidence if twin else "none",
        )
    except IntegrityError as exc:
        raise CalibrationError(
            f"A {kind} forecast for {period} already exists. Keeping a second guess "
            "would let whichever turned out better be the one reported."
        ) from exc


@transaction.atomic
def score(*, as_of: date | None = None) -> int:
    """Fill in the actuals for every forecast whose month has closed.

    Idempotent, and deliberately one-way: a snapshot with `actual_minor` set is
    skipped, so no amount of re-running can move a mark.
    """
    as_of = as_of or timezone.localdate()
    current = _month_start(as_of)

    from apps.finance import selectors as finance_selectors

    statement = finance_selectors.cashflow_statement(months=24, as_of=as_of)
    if statement is None:
        return 0
    by_period = {row.period_start: row for row in statement.rows}

    scored = 0
    pending = ForecastSnapshot.objects.filter(actual_minor__isnull=True, period__lt=current)
    for snapshot in pending:
        row = by_period.get(snapshot.period)
        if row is None:
            continue
        if snapshot.kind == ForecastKind.MONTHLY_SPEND:
            actual = row.outflow_minor
        elif snapshot.kind == ForecastKind.MONTHLY_INCOME:
            actual = row.inflow_minor
        else:
            actual = row.ending_balance_minor
        snapshot.actual_minor = actual
        snapshot.scored_at = timezone.now()
        snapshot.save(update_fields=["actual_minor", "scored_at"])
        scored += 1
    return scored


@dataclass(frozen=True)
class KindAccuracy:
    kind: str
    label: str
    samples: int
    #: Median absolute percentage error. None when nothing is scored yet.
    median_error: float | None
    #: Whether recent forecasts beat older ones. None when there is too little
    #: history to say — which is most of the time, and saying so is correct.
    trend: str | None
    detail: str


@dataclass(frozen=True)
class CalibrationReport:
    as_of: date
    total_scored: int
    kinds: list[KindAccuracy] = field(default_factory=list)
    headline: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def overall_median_error(self) -> float | None:
        errors = [k.median_error for k in self.kinds if k.median_error is not None]
        return round(statistics.median(errors), 4) if errors else None


#: Below this many scored months, any "trend" is noise. Stated rather than
#: quietly reported, because a confident trend from three points is worse than
#: no trend at all.
MIN_SAMPLES_FOR_TREND = 6


def accuracy(*, as_of: date | None = None) -> CalibrationReport:
    """How well the product has been predicting this household."""
    as_of = as_of or timezone.localdate()
    kinds: list[KindAccuracy] = []
    total = 0

    for kind, label in ForecastKind.choices:
        scored = list(
            ForecastSnapshot.objects.filter(kind=kind, actual_minor__isnull=False).order_by("period")
        )
        errors = [s.absolute_percent_error for s in scored if s.absolute_percent_error is not None]
        total += len(errors)

        if not errors:
            kinds.append(
                KindAccuracy(
                    kind=kind,
                    label=label,
                    samples=0,
                    median_error=None,
                    trend=None,
                    detail="Nothing scored yet — a forecast has to be made, and then a "
                    "month has to pass, before this says anything.",
                )
            )
            continue

        median = round(statistics.median(errors), 4)
        trend = None
        if len(errors) >= MIN_SAMPLES_FOR_TREND:
            half = len(errors) // 2
            older = statistics.median(errors[:half])
            recent = statistics.median(errors[half:])
            if recent < older * 0.9:
                trend = "improving"
            elif recent > older * 1.1:
                trend = "worse"
            else:
                trend = "steady"

        detail = f"Typically within {median:.0%} of the outcome, across {len(errors)} month(s)."
        if trend == "worse":
            detail += " Recent forecasts have been further out than older ones."
        elif trend == "improving":
            detail += " Recent forecasts have been closer than older ones."

        kinds.append(
            KindAccuracy(
                kind=kind,
                label=label,
                samples=len(errors),
                median_error=median,
                trend=trend,
                detail=detail,
            )
        )

    notes = [
        "Errors are median rather than mean: one month with a car repair in it should "
        "not decide whether your spending is predictable.",
        "Measured against what actually happened, not against a revised forecast — "
        "predictions are never rewritten once the month they describe has closed.",
    ]
    report = CalibrationReport(as_of=as_of, total_scored=total, kinds=kinds, notes=notes)

    overall = report.overall_median_error
    if total == 0:
        headline = "Not enough history yet to say how well this predicts you."
    elif overall is None:
        headline = "Scored, but nothing measurable came out of it."
    elif overall < 0.10:
        headline = f"Typically within {overall:.0%} — this knows your patterns well."
    elif overall < 0.25:
        headline = f"Typically within {overall:.0%} — a reasonable guide, not a guarantee."
    else:
        headline = (
            f"Typically {overall:.0%} out. Treat the projections as a direction of travel "
            "rather than a figure, until this narrows."
        )

    return CalibrationReport(
        as_of=report.as_of,
        total_scored=report.total_scored,
        kinds=report.kinds,
        headline=headline,
        notes=notes,
    )


def forecast_next_month(*, twin: DigitalTwin, as_of: date | None = None) -> list[ForecastSnapshot]:
    """Predict next month from the twin's own measurements, and record it.

    The prediction is deliberately simple — the household's recent median,
    grown by its own measured spending growth. A more elaborate model would
    make the calibration report harder to interpret without making it more
    useful: what is being tested is whether the twin's *measurements* describe
    the household, not whether a forecasting technique is clever.
    """
    as_of = as_of or timezone.localdate()
    period = _next_month(as_of)

    from apps.finance import selectors as finance_selectors

    statement = finance_selectors.cashflow_statement(months=12, as_of=as_of)
    if statement is None or not statement.rows:
        return []

    current = _month_start(as_of)
    # Complete months *with activity*. `cashflow_statement` emits a row for
    # every month in its window whether or not anything happened, so a sparse
    # history medians against a wall of zeros and forecasts nothing — the same
    # trap `parameters._monthly_flows` already steps around, in a third place.
    complete = [r for r in statement.rows if r.period_start < current and (r.inflow_minor or r.outflow_minor)]
    if len(complete) < 2:
        return []

    growth = twin.get("spending_growth")
    monthly_growth = (1 + growth.effective) ** (1 / 12) if growth else 1.0

    outflows = sorted(r.outflow_minor for r in complete)
    inflows = sorted(r.inflow_minor for r in complete)
    predictions = {
        ForecastKind.MONTHLY_SPEND: round(statistics.median(outflows) * monthly_growth),
        ForecastKind.MONTHLY_INCOME: round(statistics.median(inflows)),
    }

    out = []
    for kind, predicted in predictions.items():
        try:
            out.append(
                record(
                    kind=kind,
                    period=period,
                    predicted_minor=predicted,
                    currency=statement.currency,
                    twin=twin,
                    made_on=as_of,
                )
            )
        except CalibrationError:
            # Already forecast for this month. Leaving the first one standing is
            # the point of the uniqueness rule.
            continue
    return out
