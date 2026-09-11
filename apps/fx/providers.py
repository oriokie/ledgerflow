"""Live FX rate providers.

Default is the public ExchangeRate-API open endpoint (USD base, no key, covers
KES/NGN/UGX and the rest of the seed catalog). Frankfurter (ECB) is the
fallback: fewer quotes, still no key. A custom URL can be set with
`FX_RATES_URL` — any JSON object that has a `rates` map of CODE→number works.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://open.er-api.com/v6/latest/USD"
FRANKFURTER_URL = "https://api.frankfurter.app/latest?from=USD"


class RateProviderError(RuntimeError):
    """The live feed could not be read. Callers surface this; they never invent rates."""


def _parse_rates(payload: object) -> dict[str, Decimal]:
    if not isinstance(payload, dict):
        raise RateProviderError("Rate feed returned a non-object body.")
    raw = payload.get("rates")
    if not isinstance(raw, dict) or not raw:
        raise RateProviderError("Rate feed had no `rates` map.")
    out: dict[str, Decimal] = {}
    for code, value in raw.items():
        key = str(code).upper()
        if len(key) != 3 or not key.isalpha():
            continue
        try:
            rate = Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
        if rate <= 0:
            continue
        out[key] = rate
    if not out:
        raise RateProviderError("Rate feed listed no usable quotes.")
    return out


def _get_json(url: str, *, timeout: int) -> dict:
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise RateProviderError(f"Rate feed request failed: {exc}") from exc
    if response.status_code >= 400:
        raise RateProviderError(f"Rate feed returned {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RateProviderError("Rate feed returned a non-JSON body.") from exc
    if not isinstance(payload, dict):
        raise RateProviderError("Rate feed returned a non-object body.")
    return payload


def fetch_usd_rates() -> tuple[dict[str, Decimal], str]:
    """Return `{QUOTE: rate}` for 1 USD, plus a short source label."""
    timeout = int(getattr(settings, "FX_RATES_TIMEOUT", 12))
    primary = getattr(settings, "FX_RATES_URL", "") or DEFAULT_URL
    try:
        payload = _get_json(primary, timeout=timeout)
        return _parse_rates(payload), _source_label(primary)
    except RateProviderError as primary_exc:
        if primary.rstrip("/") == DEFAULT_URL.rstrip("/"):
            logger.warning("Primary FX feed failed (%s); trying Frankfurter.", primary_exc)
            payload = _get_json(FRANKFURTER_URL, timeout=timeout)
            return _parse_rates(payload), "frankfurter"
        raise


def _source_label(url: str) -> str:
    if "open.er-api.com" in url or "exchangerate-api.com" in url:
        return "er-api"
    if "frankfurter.app" in url:
        return "frankfurter"
    return "live"
