"""Ensure the currency catalog and seed USD rates exist.

Idempotent: adding a new code to `SEED_CURRENCIES` and re-running this is how
an existing database picks it up without a one-off data migration. Live rates
are left alone — this only fills pairs that have never been quoted.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.fx.currencies import SEED_CURRENCIES, SEED_USD_RATES
from apps.fx.models import Currency, ExchangeRate


class Command(BaseCommand):
    help = "Seed the ISO currency catalog and any missing USD reference rates."

    def handle(self, *args, **options):
        created = 0
        for item in SEED_CURRENCIES:
            _, was_created = Currency.objects.get_or_create(
                code=item.code,
                defaults={
                    "name": item.name,
                    "symbol": item.symbol,
                    "digits": item.digits,
                    "is_active": item.is_active,
                    "sort_order": item.sort_order,
                },
            )
            if was_created:
                created += 1

        now = timezone.now()
        rates = 0
        for quote, rate in SEED_USD_RATES.items():
            if ExchangeRate.objects.filter(base_currency="USD", quote_currency=quote).exists():
                continue
            ExchangeRate.objects.create(
                base_currency="USD",
                quote_currency=quote,
                rate=Decimal(rate),
                as_of=now,
                source="seed",
            )
            rates += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Currency catalog ready ({Currency.objects.count()} codes, "
                f"{created} new, {rates} seed rates added)."
            )
        )
