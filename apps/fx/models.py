"""FX reference data: the currency catalog and timestamped exchange rates.

Neither table is tenant-scoped. Operators maintain the catalog; every workspace
reads the same list and the same rates. Historical conversions stay reproducible
because every rate is attributed to a source and an as-of time.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel


class Currency(TimeStampedModel):
    """An ISO 4217 code the product is willing to book in.

    `code` is the identity — there is no surrogate key — so a row for KES is
    the same row everywhere, and deactivating it hides it from pickers without
    rewriting anyone's existing books.
    """

    code = models.CharField(max_length=3, primary_key=True)
    name = models.CharField(max_length=64)
    symbol = models.CharField(max_length=12)
    digits = models.PositiveSmallIntegerField(default=2)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["sort_order", "code"]
        constraints = [
            models.CheckConstraint(condition=models.Q(code__regex=r"^[A-Z]{3}$"), name="fx_currency_iso4217"),
            models.CheckConstraint(condition=models.Q(digits__lte=4), name="fx_currency_digits_range"),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.name})"


class ExchangeRate(UUIDModel, TimeStampedModel):
    base_currency = models.CharField(max_length=3)
    quote_currency = models.CharField(max_length=3)
    rate = models.DecimalField(max_digits=24, decimal_places=12)  # 1 base = <rate> quote
    as_of = models.DateTimeField(db_index=True)
    source = models.CharField(max_length=40)  # e.g. "ecb", "openexchangerates"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["base_currency", "quote_currency", "as_of", "source"],
                name="uniq_rate_pair_time_source",
            ),
            models.CheckConstraint(condition=models.Q(rate__gt=0), name="rate_positive"),
        ]
        indexes = [models.Index(fields=["base_currency", "quote_currency", "-as_of"])]

    def __str__(self) -> str:
        return f"{self.base_currency}/{self.quote_currency}={self.rate} @{self.as_of:%Y-%m-%d}"
