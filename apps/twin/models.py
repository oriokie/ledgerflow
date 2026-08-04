"""Forecasts, kept so they can be marked.

Everything else in this product computes a projection and shows it. Nothing has
ever gone back afterwards to ask whether it was right. That gap is the reason
"the twin becomes more accurate over time" would otherwise be a slogan: without
a record of what was predicted, improvement is unfalsifiable — and so is
decline.

So a forecast is written down (what was expected, for which month, on what
evidence) and later compared against what happened. The comparison can say the
twin is getting *worse*, and it must be able to, or it is marketing.

Two design choices carry most of the weight:

**Snapshots are immutable.** A row is never rewritten after the month it
describes has closed. Recording an updated prediction against a past month,
however innocently, turns the whole mechanism into a machine for generating
good news.

**The evidence is stored with the prediction.** `months_observed` and
`confidence` are copied onto the row rather than looked up later, because the
question worth answering is not "how wrong were we" but "were we more wrong
when we knew less" — and that is unanswerable if the evidence field moves.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import TenantOwnedModel


class ForecastKind(models.TextChoices):
    """What was predicted. Deliberately few: a forecast worth marking is one
    the household would notice us being wrong about."""

    MONTHLY_SPEND = "monthly_spend", "Monthly spending"
    MONTHLY_INCOME = "monthly_income", "Monthly income"
    CLOSING_LIQUID = "closing_liquid", "Cash at month end"


class ForecastSnapshot(TenantOwnedModel):
    """One prediction, made on one day, about one month.

    Inherits `TenantOwnedModel` rather than `SoftDeletableModel` deliberately:
    these are immutable records, like ledger entries. A forecast history that
    can be tidied is a forecast history nobody should trust.
    """

    kind = models.CharField(max_length=24, choices=ForecastKind.choices)
    #: First day of the month being predicted.
    period = models.DateField()
    #: The day the prediction was made. Must precede `period` for it to mean
    #: anything, which `services.record` enforces.
    made_on = models.DateField()
    predicted_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3)

    #: The evidence behind the prediction, frozen at the moment it was made.
    months_observed = models.PositiveSmallIntegerField(default=0)
    confidence = models.CharField(max_length=12, default="none")

    #: Filled in once the month has closed. Null means "not yet markable".
    actual_minor = models.BigIntegerField(null=True, blank=True)
    scored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # One prediction per kind per month. A second would be a second
            # guess, and keeping both lets the flattering one be reported.
            models.UniqueConstraint(fields=["tenant_id", "kind", "period"], name="uniq_forecast_period"),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "kind", "period"], name="forecast_period_idx"),
        ]
        ordering = ["-period"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.kind} for {self.period} (predicted {self.predicted_minor})"

    @property
    def is_scored(self) -> bool:
        return self.actual_minor is not None

    @property
    def error_minor(self) -> int | None:
        if self.actual_minor is None:
            return None
        return self.predicted_minor - self.actual_minor

    @property
    def absolute_percent_error(self) -> float | None:
        """|error| as a share of what actually happened.

        Against the actual rather than the prediction — the convention that
        stops a forecast of zero scoring perfectly on a month where something
        happened.
        """
        if self.actual_minor is None or self.actual_minor == 0:
            return None
        return abs(self.predicted_minor - self.actual_minor) / abs(self.actual_minor)
