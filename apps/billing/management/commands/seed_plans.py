"""Create or update the plan catalogue from `plan_catalogue.py`.

Idempotent and safe to re-run after a pricing change: plans are matched on
(tier, interval, currency) — the same key the unique constraint uses — so a
re-run updates prices and features rather than creating duplicates.

Existing subscriptions are untouched. A customer on Plus stays on Plus and
inherits whatever Plus now includes, which is the behaviour you want when
adding a feature and the behaviour you must think carefully about when removing
one. Removing a feature from a tier silently downgrades every customer on it,
so the command reports what it changed rather than doing it quietly.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.billing.models import BillingInterval, Plan
from apps.billing.plan_catalogue import (
    TIER_LIMITS,
    TIER_PITCH,
    TIER_PRICING_USD,
    features_for,
)

#: Annual is ten months' price — the conventional "two months free", and the
#: arithmetic is obvious enough to state on a pricing page without a footnote.
ANNUAL_MONTHS_CHARGED = 10


class Command(BaseCommand):
    help = "Create or update subscription plans from the catalogue."

    def add_arguments(self, parser):
        parser.add_argument("--currency", default="USD")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )

    def handle(self, *args, **options):
        currency = options["currency"].upper()
        dry_run = options["dry_run"]
        created = updated = 0

        for order, (tier, monthly) in enumerate(TIER_PRICING_USD.items()):
            limits = TIER_LIMITS[tier]
            features = sorted(str(f) for f in features_for(tier))
            # Note `features_for` is consulted for `ai_insights` below, but the
            # row's own `features` list is seeded EMPTY: the tier map is the
            # single source of truth and the row list is an override for
            # one-off deals. Copying the map into every row made each row a
            # stale snapshot of it — the console showed every plan as "11
            # features · 11 extra", and a feature later added to a tier would
            # not have reached any seeded plan.

            intervals = [(BillingInterval.MONTHLY, monthly)]
            # A free tier has no meaningful annual variant — an annual £0 plan
            # is a second row that can only cause confusion at renewal.
            if monthly > 0:
                intervals.append((BillingInterval.YEARLY, monthly * ANNUAL_MONTHS_CHARGED))

            for interval, price in intervals:
                label = tier.title() + (" (annual)" if interval == BillingInterval.YEARLY else "")
                defaults = {
                    "name": label,
                    "description": TIER_PITCH[tier],
                    "price_minor": price,
                    "max_members": limits["max_members"],
                    "max_accounts": limits["max_accounts"],
                    "ai_insights": "ai_insights" in features,
                    "features": [],
                    "is_active": True,
                    "sort_order": order,
                }

                existing = Plan.objects.filter(
                    tier=tier, interval=interval, currency=currency
                ).first()

                if existing is None:
                    if not dry_run:
                        Plan.objects.create(
                            tier=tier, interval=interval, currency=currency, **defaults
                        )
                    created += 1
                    self.stdout.write(f"  + {label:18} {currency} {price / 100:>8.2f}")
                    continue

                changes = [
                    field
                    for field, value in defaults.items()
                    if getattr(existing, field) != value
                ]
                if not changes:
                    continue
                if not dry_run:
                    for field, value in defaults.items():
                        setattr(existing, field, value)
                    existing.save()
                updated += 1
                # Naming the changed fields matters: removing a feature from a
                # tier downgrades every customer already on it, and that should
                # never scroll past unnoticed.
                self.stdout.write(f"  ~ {label:18} {', '.join(changes)}")

        verb = "would be" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(f"\n{created} created, {updated} updated {verb}".strip())
        )
        if not dry_run and updated:
            self.stdout.write(
                "Existing subscriptions keep their tier and inherit its new contents."
            )
