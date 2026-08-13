"""Find tenants with no Subscription row and put them on the Basic trial.

`tenancy.create_workspace` calls `billing.start_trial` for every new
workspace, but that call is deliberately best-effort (see the comment there):
a billing hiccup must not block someone's first minute in the product, so a
failure is caught, logged, and swallowed rather than raised. The workspace is
created either way — just left "legacy-unmetered", which in the UI means the
sidebar plan card and Upgrade button silently render nothing, forever, with
no error anywhere a user would see it.

This finds every tenant that fell into that gap and retries `start_trial` for
each. Safe to re-run: `start_trial` itself refuses to touch a tenant that
already has a subscription, so this command can never double-enroll anyone —
worst case it repeats a no-op.

A tenant can still come out the other side with no subscription: `start_trial`
returns `None` (and logs a warning) when no active Basic plan exists in the
current currency. That means the plan catalogue was never seeded — run
`seed_plans` first, then re-run this.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.billing.models import Subscription
from apps.billing.services import start_trial
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Back-fill a trial Subscription for tenants that never got one."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-id",
            help="Limit to a single tenant (its UUID). Omit to scan every tenant.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report which tenants are missing a subscription without writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        missing = Tenant.objects.exclude(
            id__in=Subscription.objects.values_list("tenant_id", flat=True)
        ).order_by("created_at")
        if options["tenant_id"]:
            missing = missing.filter(id=options["tenant_id"])

        tenants = list(missing)
        if not tenants:
            self.stdout.write(self.style.SUCCESS("Every tenant already has a subscription. Nothing to do."))
            return

        self.stdout.write(f"{len(tenants)} tenant(s) with no subscription:")

        if dry_run:
            for tenant in tenants:
                self.stdout.write(f"  - {tenant.id}  {tenant.name!r}  (created {tenant.created_at:%Y-%m-%d})")
            self.stdout.write(self.style.WARNING("\nDry run — nothing written."))
            return

        started = skipped = 0
        for tenant in tenants:
            subscription = start_trial(tenant_id=tenant.id)
            if subscription is not None:
                started += 1
                self.stdout.write(
                    f"  + {tenant.id}  {tenant.name!r}  trialing until {subscription.trial_end:%Y-%m-%d}"
                )
            else:
                skipped += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  ! {tenant.id}  {tenant.name!r}  still has no subscription "
                        "(no active Basic plan in its currency — seed the plan catalogue and re-run)"
                    )
                )

        self.stdout.write(self.style.SUCCESS(f"\n{started} started, {skipped} skipped."))
        if skipped:
            self.stdout.write(
                "Skipped tenants need an active Basic plan first: "
                "python manage.py seed_plans --currency=<their currency>"
            )
