"""Statistical providers — forecasting and anomaly detection.

Deterministic, explainable, dependency-free (pure Python/stdlib). These are
genuinely useful on their own; an LLM tier would *narrate* or *contextualize*
their output, not replace the math — so they remain the source of the numbers
even after LLMs land.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta

from ..protocols import (
    AmountObservation,
    Anomaly,
    AnomalyKind,
    AnomalyProvider,
    CashflowPoint,
    Forecast,
    ForecastPoint,
    ForecastProvider,
    Provenance,
    ProviderKind,
)

FORECAST_VERSION = "1.0.0"
ANOMALY_VERSION = "1.0.0"


class MovingAverageForecaster(ForecastProvider):
    """Trailing-window average with a dispersion band. Simple on purpose: it's
    transparent (a user can see why), stable on short histories, and a solid
    baseline any ML model must beat before it's worth the complexity."""

    def __init__(self, window: int = 3):
        self._window = window

    def forecast_expense(self, history: list[CashflowPoint], periods_ahead: int) -> Forecast:
        expenses = [p.expense_minor for p in history]
        if not expenses:
            base = 0
            spread = 0
            last_start = date.today().replace(day=1)
        else:
            window = expenses[-self._window :]
            base = round(statistics.fmean(window))
            spread = round(statistics.pstdev(window)) if len(window) > 1 else round(base * 0.1)
            last_start = history[-1].period_start

        points = []
        for step in range(1, periods_ahead + 1):
            period_start = last_start + relativedelta(months=step)
            points.append(
                ForecastPoint(
                    period_start=period_start,
                    projected_expense_minor=base,
                    low_minor=max(0, base - spread),
                    high_minor=base + spread,
                )
            )
        return Forecast(
            points=tuple(points),
            provenance=Provenance(
                provider="MovingAverageForecaster",
                kind=ProviderKind.STATISTICAL,
                version=FORECAST_VERSION,
                rationale=f"{self._window}-period trailing average of expenses with ±1σ band.",
            ),
        )


class StatisticalAnomalyDetector(AnomalyProvider):
    """Flags amount spikes (z-score within a payee's own history), duplicates
    (same payee+amount in a short window), and large first-time payees. Every
    flag is explainable in one sentence — critical for something that
    interrupts a user."""

    def __init__(self, z_threshold: float = 3.0, min_history: int = 4):
        self._z = z_threshold
        self._min_history = min_history

    def detect(self, observations: list[AmountObservation]) -> list[Anomaly]:
        anomalies: list[Anomaly] = []
        by_payee: dict[str, list[AmountObservation]] = defaultdict(list)
        for obs in observations:
            by_payee[obs.payee_normalized].append(obs)

        for payee, obs_list in by_payee.items():
            obs_list.sort(key=lambda o: o.occurred_at)
            amounts = [abs(o.amount_minor) for o in obs_list]

            # amount spike via z-score over the payee's own prior amounts
            if len(amounts) >= self._min_history:
                prior = amounts[:-1]
                mean = statistics.fmean(prior)
                stdev = statistics.pstdev(prior)
                latest = obs_list[-1]
                latest_amount = abs(latest.amount_minor)
                spike = False
                z = 0.0
                if stdev > 0:
                    z = (latest_amount - mean) / stdev
                    spike = z >= self._z
                elif mean > 0:
                    # zero-variance history: no spread to measure against, so
                    # fall back to a ratio test — a charge >=2x the constant
                    # norm is a spike (z reported as a scaled ratio for severity).
                    ratio = latest_amount / mean
                    if ratio >= 2.0:
                        spike = True
                        z = ratio * self._z
                if spike:
                    anomalies.append(
                        Anomaly(
                            transaction_id=latest.transaction_id,
                            kind=AnomalyKind.AMOUNT_SPIKE,
                            severity=min(1.0, z / (self._z * 2)),
                            explanation=(
                                f"{payee}: {abs(latest.amount_minor) / 100:.2f} is well above the "
                                f"usual {mean / 100:.2f} for this payee."
                            ),
                            provenance=Provenance(
                                provider="StatisticalAnomalyDetector",
                                kind=ProviderKind.STATISTICAL,
                                version=ANOMALY_VERSION,
                                rationale=f"z-score {z:.1f} ≥ {self._z}",
                            ),
                        )
                    )

            # duplicate: same payee + identical amount within 3 days
            for earlier, later in zip(obs_list, obs_list[1:], strict=False):
                if earlier.amount_minor == later.amount_minor:
                    gap_days = abs((later.occurred_at - earlier.occurred_at).days)
                    if gap_days <= 3:
                        anomalies.append(
                            Anomaly(
                                transaction_id=later.transaction_id,
                                kind=AnomalyKind.DUPLICATE,
                                severity=0.7,
                                explanation=(
                                    f"{payee}: identical charge of {abs(later.amount_minor) / 100:.2f} "
                                    f"{gap_days} day(s) apart — possible double charge."
                                ),
                                provenance=Provenance(
                                    provider="StatisticalAnomalyDetector",
                                    kind=ProviderKind.STATISTICAL,
                                    version=ANOMALY_VERSION,
                                    rationale="same payee+amount within 3 days",
                                ),
                            )
                        )

            # large first-time payee: single observation, above a floor
            if len(amounts) == 1 and amounts[0] >= 50000:  # >= 500.00
                only = obs_list[0]
                anomalies.append(
                    Anomaly(
                        transaction_id=only.transaction_id,
                        kind=AnomalyKind.NEW_PAYEE_LARGE,
                        severity=0.5,
                        explanation=(
                            f"{payee}: first-ever charge and it's large " f"({amounts[0] / 100:.2f})."
                        ),
                        provenance=Provenance(
                            provider="StatisticalAnomalyDetector",
                            kind=ProviderKind.STATISTICAL,
                            version=ANOMALY_VERSION,
                            rationale="first observation for payee ≥ 500.00",
                        ),
                    )
                )

        return anomalies
