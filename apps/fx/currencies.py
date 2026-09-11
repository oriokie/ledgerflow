"""ISO 4217 currency catalog.

The seed tuple is what a fresh database gets, and the fallback when the
`Currency` table has not been migrated yet. Live reads go through the table so
an operator can add, hide, or rename a currency without a deploy.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.utils import ProgrammingError


@dataclass(frozen=True)
class Currency:
    code: str
    name: str
    symbol: str
    digits: int = 2  # minor-unit decimal places (JPY=0, KWD=3, most=2)
    is_active: bool = True
    sort_order: int = 0


SEED_CURRENCIES: tuple[Currency, ...] = (
    Currency("USD", "US Dollar", "$", sort_order=0),
    Currency("EUR", "Euro", "€", sort_order=1),
    Currency("GBP", "British Pound", "£", sort_order=2),
    Currency("KES", "Kenyan Shilling", "KSh", sort_order=3),
    Currency("JPY", "Japanese Yen", "¥", 0, sort_order=4),
    Currency("CHF", "Swiss Franc", "CHF", sort_order=10),
    Currency("CAD", "Canadian Dollar", "C$", sort_order=11),
    Currency("AUD", "Australian Dollar", "A$", sort_order=12),
    Currency("NZD", "New Zealand Dollar", "NZ$", sort_order=13),
    Currency("CNY", "Chinese Yuan", "¥", sort_order=14),
    Currency("HKD", "Hong Kong Dollar", "HK$", sort_order=15),
    Currency("SGD", "Singapore Dollar", "S$", sort_order=16),
    Currency("INR", "Indian Rupee", "₹", sort_order=17),
    Currency("NGN", "Nigerian Naira", "₦", sort_order=18),
    Currency("ZAR", "South African Rand", "R", sort_order=19),
    Currency("GHS", "Ghanaian Cedi", "₵", sort_order=20),
    Currency("UGX", "Ugandan Shilling", "USh", 0, sort_order=21),
    Currency("TZS", "Tanzanian Shilling", "TSh", sort_order=22),
    Currency("EGP", "Egyptian Pound", "E£", sort_order=23),
    Currency("AED", "UAE Dirham", "د.إ", sort_order=24),
    Currency("SAR", "Saudi Riyal", "﷼", sort_order=25),
    Currency("BRL", "Brazilian Real", "R$", sort_order=26),
    Currency("MXN", "Mexican Peso", "$", sort_order=27),
    Currency("ARS", "Argentine Peso", "$", sort_order=28),
    Currency("SEK", "Swedish Krona", "kr", sort_order=29),
    Currency("NOK", "Norwegian Krone", "kr", sort_order=30),
    Currency("DKK", "Danish Krone", "kr", sort_order=31),
    Currency("PLN", "Polish Zloty", "zł", sort_order=32),
    Currency("CZK", "Czech Koruna", "Kč", sort_order=33),
    Currency("TRY", "Turkish Lira", "₺", sort_order=34),
    Currency("KRW", "South Korean Won", "₩", 0, sort_order=35),
    Currency("THB", "Thai Baht", "฿", sort_order=36),
    Currency("IDR", "Indonesian Rupiah", "Rp", sort_order=37),
    Currency("MYR", "Malaysian Ringgit", "RM", sort_order=38),
    Currency("PHP", "Philippine Peso", "₱", sort_order=39),
    Currency("KWD", "Kuwaiti Dinar", "KD", 3, sort_order=40),
    Currency("BHD", "Bahraini Dinar", "BD", 3, sort_order=41),
)

#: Approximate USD→quote rates so conversion works before live ingestion.
SEED_USD_RATES: dict[str, str] = {
    "EUR": "0.92",
    "GBP": "0.79",
    "JPY": "157.0",
    "CHF": "0.89",
    "CAD": "1.37",
    "AUD": "1.51",
    "NZD": "1.64",
    "CNY": "7.24",
    "HKD": "7.81",
    "SGD": "1.35",
    "INR": "83.4",
    "KES": "129.0",
    "NGN": "1600.0",
    "ZAR": "18.4",
    "GHS": "15.3",
    "UGX": "3700.0",
    "TZS": "2600.0",
    "EGP": "48.5",
    "AED": "3.67",
    "SAR": "3.75",
    "BRL": "5.44",
    "MXN": "18.6",
    "ARS": "930.0",
    "SEK": "10.6",
    "NOK": "10.8",
    "DKK": "6.87",
    "PLN": "3.95",
    "CZK": "23.3",
    "TRY": "33.0",
    "KRW": "1380.0",
    "THB": "36.5",
    "IDR": "16200.0",
    "MYR": "4.68",
    "PHP": "58.4",
    "KWD": "0.307",
    "BHD": "0.377",
}

#: Back-compat alias: tests and older imports still say `CURRENCIES`.
CURRENCIES = SEED_CURRENCIES
_SEED_BY_CODE = {c.code: c for c in SEED_CURRENCIES}
SUPPORTED_CODES = frozenset(_SEED_BY_CODE)


def _dto(row) -> Currency:
    return Currency(
        code=row.code,
        name=row.name,
        symbol=row.symbol,
        digits=row.digits,
        is_active=row.is_active,
        sort_order=row.sort_order,
    )


def _table_rows():
    from .models import Currency as CurrencyRow

    try:
        return list(CurrencyRow.objects.all().order_by("sort_order", "code"))
    except ProgrammingError:
        return None


def list_currencies(*, active_only: bool = True) -> list[Currency]:
    """Picker catalog. Empty table (pre-migration) falls back to the seed."""
    rows = _table_rows()
    items = [_dto(r) for r in rows] if rows else list(SEED_CURRENCIES)
    if active_only:
        return [c for c in items if c.is_active]
    return items


def get_currency(code: str) -> Currency | None:
    """Look up a code for formatting. Inactive rows still resolve — existing
    books keep their digits after an operator hides the currency from pickers."""
    needle = (code or "").upper()
    if not needle:
        return None
    rows = _table_rows()
    if rows:
        for row in rows:
            if row.code == needle:
                return _dto(row)
        return None
    return _SEED_BY_CODE.get(needle)


def is_known(code: str) -> bool:
    return get_currency(code) is not None


def is_supported(code: str) -> bool:
    """True when a *new* choice may use this code (active catalog row)."""
    needle = (code or "").upper()
    if not needle:
        return False
    rows = _table_rows()
    if rows:
        return any(r.code == needle and r.is_active for r in rows)
    return needle in _SEED_BY_CODE


def currency_digits(code: str) -> int:
    meta = get_currency(code)
    return meta.digits if meta is not None else 2
