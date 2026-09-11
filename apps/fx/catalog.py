"""Operator mutations on the global currency catalog.

Kept out of `currencies.py` so the read path (pickers, formatting) never
imports write-side validation, and out of the platform views so a management
command or a Celery task can do the same work with the same rules.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import IntegrityError

from .currencies import Currency as CurrencyInfo
from .currencies import _dto, list_currencies
from .models import Currency
from .services import latest_rate_row, upsert_rate, usd_quotes


class CatalogError(ValueError):
    """A write that would produce a catalog the product cannot defend."""


def _normalize_code(code: str) -> str:
    value = (code or "").strip().upper()
    if len(value) != 3 or not value.isalpha():
        raise CatalogError("Currency codes are three letters, e.g. KES.")
    return value


def serialize(info: CurrencyInfo, *, quotes: dict | None = None) -> dict:
    quote = None if quotes is None else quotes.get(info.code)
    if info.code == "USD":
        rate, as_of, source = "1", None, "parity"
    elif quote is not None:
        rate, as_of, source = str(quote.rate), quote.as_of.isoformat(), quote.source
    else:
        row = latest_rate_row("USD", info.code)
        if row is not None:
            rate, as_of, source = str(row.rate), row.as_of.isoformat(), row.source
        else:
            rate, as_of, source = None, None, ""
    return {
        "code": info.code,
        "name": info.name,
        "symbol": info.symbol,
        "digits": info.digits,
        "is_active": info.is_active,
        "sort_order": info.sort_order,
        "usd_rate": rate,
        "usd_rate_as_of": as_of,
        "usd_rate_source": source,
    }


def list_for_admin() -> list[dict]:
    quotes = usd_quotes()
    return [serialize(c, quotes=quotes) for c in list_currencies(active_only=False)]


def create_currency(
    *,
    code: str,
    name: str,
    symbol: str,
    digits: int = 2,
    is_active: bool = True,
    sort_order: int = 100,
    usd_rate: Decimal | str | None = None,
) -> dict:
    code = _normalize_code(code)
    name = (name or "").strip()
    symbol = (symbol or "").strip() or code
    if not name:
        raise CatalogError("A currency needs a name.")
    if digits < 0 or digits > 4:
        raise CatalogError("Minor-unit digits are 0 to 4.")
    try:
        row = Currency.objects.create(
            code=code,
            name=name,
            symbol=symbol,
            digits=digits,
            is_active=is_active,
            sort_order=sort_order,
        )
    except IntegrityError as exc:
        raise CatalogError(f"{code} is already in the catalog.") from exc
    if usd_rate is not None:
        set_usd_rate(code=code, rate=usd_rate, source="manual")
    return serialize(_dto(row))


def update_currency(code: str, **changes) -> dict:
    code = _normalize_code(code)
    row = Currency.objects.filter(pk=code).first()
    if row is None:
        raise CatalogError(f"{code} is not in the catalog.")
    allowed = {"name", "symbol", "digits", "is_active", "sort_order"}
    unknown = set(changes) - allowed
    if unknown:
        raise CatalogError(f"Cannot change {', '.join(sorted(unknown))}.")
    if "name" in changes:
        name = (changes["name"] or "").strip()
        if not name:
            raise CatalogError("A currency needs a name.")
        changes["name"] = name
    if "symbol" in changes:
        symbol = (changes["symbol"] or "").strip()
        if not symbol:
            raise CatalogError("A currency needs a symbol.")
        changes["symbol"] = symbol
    if "digits" in changes:
        digits = int(changes["digits"])
        if digits < 0 or digits > 4:
            raise CatalogError("Minor-unit digits are 0 to 4.")
        changes["digits"] = digits
    for field, value in changes.items():
        setattr(row, field, value)
    row.save(update_fields=[*changes.keys(), "updated_at"] if changes else ["updated_at"])
    return serialize(_dto(row))


def set_usd_rate(*, code: str, rate: Decimal | float | str, source: str = "manual") -> dict:
    code = _normalize_code(code)
    if code == "USD":
        raise CatalogError("USD is the pivot; it is always 1.")
    if not Currency.objects.filter(pk=code).exists():
        raise CatalogError(f"{code} is not in the catalog.")
    try:
        value = Decimal(str(rate))
    except (InvalidOperation, ValueError) as exc:
        raise CatalogError("Rate must be a positive number.") from exc
    if value <= 0:
        raise CatalogError("Rate must be a positive number.")
    row = upsert_rate(base="USD", quote=code, rate=value, source=source)
    info = next((c for c in list_currencies(active_only=False) if c.code == code), None)
    if info is None:
        raise CatalogError(f"{code} is not in the catalog.")
    return serialize(info, quotes={code: row})
