"""FX conversion service.

Rates are global reference data. `convert` uses the latest known rate for a
pair, falling back to triangulation through USD when a direct pair is missing.
Live-rate ingestion is a hook (`refresh_rates`) — in this build rates are seeded
and can be set manually; wiring a provider (ECB/OpenExchangeRates) is a drop-in.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.utils import timezone

from .models import ExchangeRate

logger = logging.getLogger(__name__)

_PIVOT = "USD"


def upsert_rate(
    *, base: str, quote: str, rate: Decimal | float | str, source: str = "manual", as_of=None
) -> ExchangeRate:
    base, quote = base.upper(), quote.upper()
    as_of = as_of or timezone.now()
    obj, _ = ExchangeRate.objects.update_or_create(
        base_currency=base,
        quote_currency=quote,
        as_of=as_of,
        source=source,
        defaults={"rate": Decimal(str(rate))},
    )
    return obj


def latest_rate(base: str, quote: str) -> Decimal | None:
    """Newest rate for base→quote. Tries the direct pair, its inverse, then
    triangulates through USD. Returns None if it can't be determined."""
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return Decimal(1)

    direct = ExchangeRate.objects.filter(base_currency=base, quote_currency=quote).order_by("-as_of").first()
    if direct:
        return direct.rate

    inverse = ExchangeRate.objects.filter(base_currency=quote, quote_currency=base).order_by("-as_of").first()
    if inverse and inverse.rate:
        return Decimal(1) / inverse.rate

    if base != _PIVOT and quote != _PIVOT:
        base_to_pivot = latest_rate(base, _PIVOT)
        pivot_to_quote = latest_rate(_PIVOT, quote)
        if base_to_pivot and pivot_to_quote:
            return base_to_pivot * pivot_to_quote
    return None


def convert(*, amount_minor: int, from_currency: str, to_currency: str) -> int | None:
    """Convert a minor-unit amount. Returns None if no rate is available, so
    callers can degrade gracefully rather than fabricate a number."""
    if from_currency.upper() == to_currency.upper():
        return amount_minor
    rate = latest_rate(from_currency, to_currency)
    if rate is None:
        return None
    return int(round(Decimal(amount_minor) * rate))


def refresh_rates(*, source: str = "manual") -> int:
    """Hook for periodic live-rate ingestion (Celery beat). No external provider
    is wired in this build; returns the count fetched (0)."""
    logger.info("refresh_rates called (source=%s) — no provider configured.", source)
    return 0
