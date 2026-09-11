"""FX conversion and live-rate ingestion.

Rates are global reference data. `convert` uses the latest known rate for a
pair, falling back to triangulation through USD when a direct pair is missing.
Amounts are ISO minor units; conversion happens in major units so JPY (0
digits) and KWD (3) do not silently 100× against USD cents.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_EVEN, Decimal

from django.utils import timezone

from .currencies import currency_digits, list_currencies
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


def latest_rate_row(base: str, quote: str) -> ExchangeRate | None:
    return (
        ExchangeRate.objects.filter(base_currency=base.upper(), quote_currency=quote.upper())
        .order_by("-as_of")
        .first()
    )


def latest_rate(base: str, quote: str) -> Decimal | None:
    """Newest rate for base→quote. Tries the direct pair, its inverse, then
    triangulates through USD. Returns None if it can't be determined."""
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return Decimal(1)

    direct = latest_rate_row(base, quote)
    if direct:
        return direct.rate

    inverse = latest_rate_row(quote, base)
    if inverse and inverse.rate:
        return Decimal(1) / inverse.rate

    if base != _PIVOT and quote != _PIVOT:
        base_to_pivot = latest_rate(base, _PIVOT)
        pivot_to_quote = latest_rate(_PIVOT, quote)
        if base_to_pivot and pivot_to_quote:
            return base_to_pivot * pivot_to_quote
    return None


def _scale(code: str) -> Decimal:
    return Decimal(10) ** currency_digits(code)


def convert(*, amount_minor: int, from_currency: str, to_currency: str) -> int | None:
    """Convert a minor-unit amount. Returns None if no rate is available, so
    callers can degrade gracefully rather than fabricate a number.

    The rate is a major-unit quote (1 USD = 157 JPY). Converting minor units
    directly would inflate yen by 100× and shrink dinars by 10×.
    """
    if from_currency.upper() == to_currency.upper():
        return amount_minor
    rate = latest_rate(from_currency, to_currency)
    if rate is None:
        return None
    major = Decimal(amount_minor) / _scale(from_currency)
    dest = (major * rate * _scale(to_currency)).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    return int(dest)


def usd_quotes() -> dict[str, ExchangeRate]:
    """Latest USD→quote row per currency, one query on Postgres."""
    rows = (
        ExchangeRate.objects.filter(base_currency=_PIVOT)
        .order_by("quote_currency", "-as_of")
        .distinct("quote_currency")
    )
    return {row.quote_currency: row for row in rows}


def refresh_rates(*, source: str = "live", force: bool = False) -> dict:
    """Pull USD quotes from the live feed and write a new as-of for each
    active catalog currency the feed knows.

    Pairs whose newest row is `source=manual` are left alone unless `force` is
    set, so an operator-set rate is not clobbered by the overnight job.
    """
    from .providers import RateProviderError, fetch_usd_rates

    try:
        quotes, feed = fetch_usd_rates()
    except RateProviderError:
        logger.exception("Live FX refresh failed.")
        raise

    as_of = timezone.now()
    updated = 0
    skipped_manual = 0
    missing: list[str] = []
    catalog = [c for c in list_currencies(active_only=True) if c.code != _PIVOT]
    latest = usd_quotes()

    for currency in catalog:
        rate = quotes.get(currency.code)
        if rate is None:
            missing.append(currency.code)
            continue
        existing = latest.get(currency.code)
        if existing is not None and existing.source == "manual" and not force:
            skipped_manual += 1
            continue
        upsert_rate(base=_PIVOT, quote=currency.code, rate=rate, source=source or feed, as_of=as_of)
        updated += 1

    logger.info(
        "FX refresh source=%s updated=%s skipped_manual=%s missing=%s",
        feed,
        updated,
        skipped_manual,
        ",".join(missing) or "-",
    )
    return {
        "updated": updated,
        "skipped_manual": skipped_manual,
        "missing": missing,
        "source": feed,
        "as_of": as_of.isoformat(),
    }
