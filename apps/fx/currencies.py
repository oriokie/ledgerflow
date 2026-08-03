"""A curated ISO 4217 currency catalog — enough to cover the vast majority of
users without shipping all 180. Kept as reference data (code, name, symbol,
minor-unit digits) so the UI can offer a lookup instead of free text and so
formatting knows how many decimal places a currency uses.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Currency:
    code: str
    name: str
    symbol: str
    digits: int = 2  # minor-unit decimal places (JPY=0, KWD=3, most=2)


CURRENCIES: tuple[Currency, ...] = (
    Currency("USD", "US Dollar", "$"),
    Currency("EUR", "Euro", "€"),
    Currency("GBP", "British Pound", "£"),
    Currency("JPY", "Japanese Yen", "¥", 0),
    Currency("CHF", "Swiss Franc", "CHF"),
    Currency("CAD", "Canadian Dollar", "C$"),
    Currency("AUD", "Australian Dollar", "A$"),
    Currency("NZD", "New Zealand Dollar", "NZ$"),
    Currency("CNY", "Chinese Yuan", "¥"),
    Currency("HKD", "Hong Kong Dollar", "HK$"),
    Currency("SGD", "Singapore Dollar", "S$"),
    Currency("INR", "Indian Rupee", "₹"),
    Currency("KES", "Kenyan Shilling", "KSh"),
    Currency("NGN", "Nigerian Naira", "₦"),
    Currency("ZAR", "South African Rand", "R"),
    Currency("GHS", "Ghanaian Cedi", "₵"),
    Currency("UGX", "Ugandan Shilling", "USh", 0),
    Currency("TZS", "Tanzanian Shilling", "TSh"),
    Currency("EGP", "Egyptian Pound", "E£"),
    Currency("AED", "UAE Dirham", "د.إ"),
    Currency("SAR", "Saudi Riyal", "﷼"),
    Currency("BRL", "Brazilian Real", "R$"),
    Currency("MXN", "Mexican Peso", "$"),
    Currency("ARS", "Argentine Peso", "$"),
    Currency("SEK", "Swedish Krona", "kr"),
    Currency("NOK", "Norwegian Krone", "kr"),
    Currency("DKK", "Danish Krone", "kr"),
    Currency("PLN", "Polish Zloty", "zł"),
    Currency("CZK", "Czech Koruna", "Kč"),
    Currency("TRY", "Turkish Lira", "₺"),
    Currency("KRW", "South Korean Won", "₩", 0),
    Currency("THB", "Thai Baht", "฿"),
    Currency("IDR", "Indonesian Rupiah", "Rp"),
    Currency("MYR", "Malaysian Ringgit", "RM"),
    Currency("PHP", "Philippine Peso", "₱"),
    Currency("KWD", "Kuwaiti Dinar", "KD", 3),
    Currency("BHD", "Bahraini Dinar", "BD", 3),
)

_BY_CODE = {c.code: c for c in CURRENCIES}
SUPPORTED_CODES = frozenset(_BY_CODE)


def get_currency(code: str) -> Currency | None:
    return _BY_CODE.get((code or "").upper())


def is_supported(code: str) -> bool:
    return (code or "").upper() in SUPPORTED_CODES
