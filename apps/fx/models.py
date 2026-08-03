"""Exchange rates: global reference data (not tenant-scoped).

Every rate is timestamped and attributed to a source so historical conversions
are reproducible and auditable. Cross-currency journal entries reference the
rate used at posting time.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel


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
