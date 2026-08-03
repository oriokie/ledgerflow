"""Money value object.

Design rules (non-negotiable):
  * Amounts are ALWAYS stored/transported as integer minor units (cents, pence,
    yen has 0 minor units, etc.). Never float. Never a display string.
  * An amount is meaningless without its currency, so the two travel together
    as one immutable value object.
  * Cross-currency arithmetic is forbidden. Converting requires an explicit,
    timestamped FX rate carried by the caller (handled in a future `fx` context).

This lives in `common` because every context that touches money reuses it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

# ISO-4217 minor-unit exponents for the currencies we format at the edge.
# Config-over-hardcode: the authoritative table is loaded from settings; this is
# only the fallback used when a currency is not explicitly configured.
_DEFAULT_MINOR_UNITS: dict[str, int] = {
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "JPY": 0,
    "KWD": 3,
    "BHD": 3,
    "CLF": 4,
}


class CurrencyMismatchError(Exception):
    """Raised when two Money values of different currencies are combined."""


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str  # ISO-4217 alpha-3, upper-cased

    def __post_init__(self) -> None:
        if not isinstance(self.amount_minor, int):
            raise TypeError("amount_minor must be an int (minor units)")
        if len(self.currency) != 3 or not self.currency.isupper():
            raise ValueError(f"currency must be ISO-4217 alpha-3 upper: {self.currency!r}")

    # -- construction -------------------------------------------------------
    @classmethod
    def from_decimal(cls, value: Decimal | str, currency: str) -> Money:
        exponent = _DEFAULT_MINOR_UNITS.get(currency, 2)
        quant = Decimal(1).scaleb(-exponent)
        minor = int((Decimal(value).quantize(quant, rounding=ROUND_HALF_EVEN)) * (10**exponent))
        return cls(minor, currency)

    # -- arithmetic (same-currency only) ------------------------------------
    def _assert_same(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(f"{self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._assert_same(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._assert_same(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount_minor, self.currency)

    # -- presentation (only at the boundary) --------------------------------
    def to_decimal(self) -> Decimal:
        exponent = _DEFAULT_MINOR_UNITS.get(self.currency, 2)
        return Decimal(self.amount_minor).scaleb(-exponent)

    def __str__(self) -> str:
        return f"{self.to_decimal()} {self.currency}"
