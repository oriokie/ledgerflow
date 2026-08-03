"""Seed a working platform admin plus enough data to exercise the console.

Purpose
-------
A freshly bootstrapped platform workspace is correct but empty: every chart
reads zero and every table says "nothing here", which makes it impossible to
tell a working console from a broken one. This command creates a signed-in-able
admin and a small, deliberately varied customer base — healthy accounts, a
trial about to lapse, a past-due account already in dunning, a suspended one —
so every screen has something real to render.

Safety
------
Refuses to run when `DEBUG` is off unless `--i-know-this-is-not-production` is
passed. Seeding fake customers into a production database would corrupt every
revenue figure the console reports, and those figures get quoted to boards.

Idempotent: re-running updates the admin's password and tops up missing demo
data rather than duplicating it.

Usage
-----
    python manage.py seed_platform_demo
    python manage.py seed_platform_demo --email me@example.com --password '…'
    python manage.py seed_platform_demo --admin-only
"""

from __future__ import annotations

import random
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.billing import dunning, invoicing
from apps.billing.invoicing_models import InvoiceStatus
from apps.billing.models import (
    BillingInterval,
    Payment,
    PaymentMethod,
    PaymentMethodKind,
    PaymentStatus,
    Plan,
    PlanTier,
    Subscription,
    SubscriptionStatus,
)
from apps.billing.promotions_models import Coupon, CouponDuration, CouponKind
from apps.platform_admin.models import PlatformStaff
from apps.platform_admin.rbac import PlatformRole
from apps.platform_admin.services import staff as staff_service
from apps.tenancy.models import Membership, Role, Tenant, TenantType
from apps.users.models import User

DEFAULT_EMAIL = "admin@ledgerflow.test"
DEFAULT_PASSWORD = "PlatformAdmin!2026"  # noqa: S105 — a seeded dev credential, printed on stdout

#: (workspace, owner email, country, currency, locale, tenant type)
DEMO_TENANTS = [
    ("The Otieno Household", "amina@example.test", "KE", "KES", "en-KE", TenantType.HOUSEHOLD),
    ("Nakamura Family", "yuki@example.test", "JP", "USD", "en-US", TenantType.HOUSEHOLD),
    ("Silva Personal", "bruno@example.test", "BR", "USD", "en-US", TenantType.PERSONAL),
    ("Okonkwo & Partners", "chidi@example.test", "NG", "USD", "en-US", TenantType.ORGANIZATION),
    ("Dubois Ménage", "claire@example.test", "FR", "USD", "fr-FR", TenantType.HOUSEHOLD),
    ("Patel Household", "riya@example.test", "IN", "USD", "en-IN", TenantType.HOUSEHOLD),
    ("Hansen Personal", "lars@example.test", "DK", "USD", "en-US", TenantType.PERSONAL),
    ("Mwangi Household", "grace@example.test", "KE", "KES", "en-KE", TenantType.HOUSEHOLD),
    ("Ferreira Family", "ana@example.test", "PT", "USD", "en-US", TenantType.HOUSEHOLD),
    ("Bakker Personal", "sven@example.test", "NL", "USD", "en-US", TenantType.PERSONAL),
]


class Command(BaseCommand):
    help = "Create a platform admin and demo customer data for testing the console."

    def add_arguments(self, parser):
        parser.add_argument("--email", default=DEFAULT_EMAIL)
        parser.add_argument("--password", default=DEFAULT_PASSWORD)
        parser.add_argument(
            "--admin-only",
            action="store_true",
            help="Create only the platform admin, no demo customers.",
        )
        parser.add_argument(
            "--require-mfa",
            action="store_true",
            help="Keep the 2FA requirement. Off by default so the seeded account is "
            "immediately usable; leave it off only in development.",
        )
        parser.add_argument(
            "--i-know-this-is-not-production",
            action="store_true",
            dest="force",
            help="Required to run with DEBUG off.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "DEBUG is off. Seeding demo customers would corrupt real revenue "
                "figures. Re-run with --i-know-this-is-not-production if you are "
                "certain this is a throwaway environment."
            )

        random.seed(20260726)  # stable output across runs
        admin = self._create_admin(options)

        if options["admin_only"]:
            self._report(admin, options["password"], tenants=0)
            return

        plans = self._ensure_plans()
        self._ensure_coupons()
        created = self._create_customers(plans)
        self._report(admin, options["password"], tenants=created)

    # ------------------------------------------------------------------ admin
    @transaction.atomic
    def _create_admin(self, options) -> PlatformStaff:
        email = options["email"].strip().lower()
        user, _ = User.objects.get_or_create(
            email=email,
            defaults={"first_name": "Platform", "last_name": "Admin", "is_verified": True},
        )
        # Always reset the password: the point of a seed account is that you can
        # sign in, and a forgotten one from a previous run helps nobody.
        user.set_password(options["password"])
        user.is_verified = True
        user.is_active = True
        user.save()

        staff = PlatformStaff.objects.filter(user=user).first()
        if staff is None:
            staff = staff_service.appoint(
                user=user,
                role=PlatformRole.OWNER,
                actor=None,  # bootstrap path — no existing staff to authorise it
                require_mfa=options["require_mfa"],
                note="Seeded for testing by seed_platform_demo.",
            )
        else:
            staff.is_active = True
            staff.role = PlatformRole.OWNER
            staff.require_mfa = options["require_mfa"]
            staff.save(update_fields=["is_active", "role", "require_mfa", "updated_at"])
        return staff

    # ------------------------------------------------------------------ plans
    def _ensure_plans(self) -> dict[str, Plan]:
        """The catalog. Unique on (tier, interval, currency), so one row each."""
        specs = [
            (PlanTier.FREE, BillingInterval.MONTHLY, "USD", 0, "Free", 1, 3),
            (PlanTier.PLUS, BillingInterval.MONTHLY, "USD", 900, "Plus", 3, 25),
            (PlanTier.PLUS, BillingInterval.YEARLY, "USD", 9000, "Plus (annual)", 3, 25),
            (PlanTier.FAMILY, BillingInterval.MONTHLY, "USD", 1900, "Family", 6, 100),
            (PlanTier.BUSINESS, BillingInterval.MONTHLY, "USD", 4900, "Business", 25, 500),
            (PlanTier.PLUS, BillingInterval.MONTHLY, "KES", 129_000, "Plus", 3, 25),
        ]
        plans: dict[str, Plan] = {}
        for order, (tier, interval, currency, price, name, members, accounts) in enumerate(specs):
            plan, _ = Plan.objects.get_or_create(
                tier=tier,
                interval=interval,
                currency=currency,
                defaults={
                    "name": name,
                    "price_minor": price,
                    "max_members": members,
                    "max_accounts": accounts,
                    "ai_insights": tier != PlanTier.FREE,
                    # Catalog position, not price: `sort_order` is a
                    # PositiveSmallIntegerField and a high-denomination currency
                    # (KES 129,000 minor units) overflows smallint.
                    "sort_order": order,
                },
            )
            plans[f"{tier}-{interval}-{currency}"] = plan
        return plans

    def _ensure_coupons(self) -> None:
        now = timezone.now()
        for code, name, kind, value, currency, duration in [
            ("LAUNCH25", "Launch 25% off", CouponKind.PERCENT, 2500, "", CouponDuration.REPEATING),
            ("WELCOME5", "$5 off first month", CouponKind.FIXED, 500, "USD", CouponDuration.ONCE),
            ("EXTRA14", "14 extra trial days", CouponKind.TRIAL_EXTENSION, 14, "", CouponDuration.ONCE),
        ]:
            Coupon.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "kind": kind,
                    "value": value,
                    "currency": currency,
                    "duration": duration,
                    "duration_in_months": 3 if duration == CouponDuration.REPEATING else None,
                    "expires_at": now + timedelta(days=90),
                    "max_redemptions": 500,
                },
            )

    # -------------------------------------------------------------- customers
    def _create_customers(self, plans: dict[str, Plan]) -> int:
        dunning.ensure_default_policy()
        now = timezone.now()
        created = 0

        for index, (name, owner_email, country, currency, locale, kind) in enumerate(DEMO_TENANTS):
            if Tenant.objects.filter(name=name).exists():
                continue

            with transaction.atomic():
                owner, _ = User.objects.get_or_create(
                    email=owner_email,
                    defaults={
                        "first_name": owner_email.split("@")[0].title(),
                        "last_name": name.split()[0],
                        "is_verified": True,
                    },
                )
                owner.set_password(DEFAULT_PASSWORD)
                # Spread last-login across the last few weeks so the "last
                # activity" column is not a wall of identical timestamps.
                owner.last_login_at = now - timedelta(days=random.randint(0, 25))
                owner.save()

                tenant = Tenant.objects.create(
                    name=name,
                    type=kind,
                    base_currency=currency,
                    default_locale=locale,
                    default_timezone="Africa/Nairobi" if country == "KE" else "UTC",
                    country=country,
                    billing_email=owner_email,
                )
                # Backdate creation so the signup-cohort and growth charts have
                # a spread to draw rather than a single spike at seed time.
                Tenant.objects.filter(pk=tenant.pk).update(
                    created_at=now - timedelta(days=random.randint(20, 300))
                )
                tenant.refresh_from_db()

                Membership.objects.create(tenant=tenant, user=owner, role=Role.OWNER)
                self._scenario(index, tenant, owner, plans, currency, now)
                created += 1

        return created

    def _scenario(self, index, tenant, owner, plans, currency, now) -> None:
        """Give each demo workspace a distinct, realistic billing situation."""
        key = f"plus-monthly-{currency}" if currency == "KES" else None
        paid = plans.get(key) or plans["plus-monthly-USD"]
        family = plans["family-monthly-USD"]
        business = plans["business-monthly-USD"]
        annual = plans["plus-yearly-USD"]
        free = plans["free-monthly-USD"]

        scenario = index % 10

        if scenario == 0:  # healthy monthly, invoiced and paid
            sub = self._subscribe(tenant, paid, SubscriptionStatus.ACTIVE, now)
            self._method(tenant, "mpesa" if currency == "KES" else "stripe")
            self._history(tenant, sub, months=4, succeed=True)
        elif scenario == 1:  # healthy annual — exercises MRR normalisation
            sub = self._subscribe(tenant, annual, SubscriptionStatus.ACTIVE, now)
            self._method(tenant, "stripe")
            self._history(tenant, sub, months=1, succeed=True)
        elif scenario == 2:  # trial ending in three days
            self._subscribe(
                tenant, family, SubscriptionStatus.TRIALING, now, trial_end=now + timedelta(days=3)
            )
        elif scenario == 3:  # past due, already in recovery
            sub = self._subscribe(tenant, family, SubscriptionStatus.PAST_DUE, now)
            self._method(tenant, "stripe")
            payment = Payment.objects.create(
                tenant_id=tenant.id,
                subscription=sub,
                amount_minor=family.price_minor,
                currency=family.currency,
                status=PaymentStatus.FAILED,
                provider="stripe",
                provider_ref=f"pi_seed_{tenant.id.hex[:12]}",
                failure_reason="card_declined",
                description=f"{family.name} subscription",
            )
            dunning.on_payment_failed(payment=payment, reason="card_declined")
        elif scenario == 4:  # suspended for abuse
            self._subscribe(tenant, paid, SubscriptionStatus.ACTIVE, now)
            Tenant.objects.filter(pk=tenant.pk).update(is_active=False)
        elif scenario == 5:  # business account with an overdue invoice
            sub = self._subscribe(tenant, business, SubscriptionStatus.ACTIVE, now)
            self._method(tenant, "stripe")
            self._history(tenant, sub, months=2, succeed=True)
            overdue = invoicing.create_invoice(
                tenant_id=tenant.id,
                currency=business.currency,
                line_items=[
                    invoicing.LineItemSpec(
                        description=f"{business.name} subscription",
                        amount_minor=business.price_minor,
                    )
                ],
                subscription=sub,
                issue_date=(now - timedelta(days=40)).date(),
                due_date=(now - timedelta(days=26)).date(),
                tax_rate_bps=2000,
                tax_label="VAT",
                billing_email=tenant.billing_email,
                billing_name=owner.full_name,
                billing_country=tenant.country,
                status=InvoiceStatus.DRAFT,
            )
            invoicing.issue_invoice(invoice=overdue)
            invoicing.mark_overdue()
        elif scenario == 6:  # free tier with account credit
            self._subscribe(tenant, free, SubscriptionStatus.ACTIVE, now)
            invoicing.issue_credit(
                tenant_id=tenant.id,
                amount_minor=1500,
                currency="USD",
                reason="Goodwill after the March sync incident.",
            )
        elif scenario == 7:  # churned
            sub = self._subscribe(tenant, paid, SubscriptionStatus.ACTIVE, now)
            self._history(tenant, sub, months=3, succeed=True)
            Subscription.objects.filter(pk=sub.pk).update(
                status=SubscriptionStatus.CANCELED, canceled_at=now - timedelta(days=8)
            )
        elif scenario == 8:  # trial that converted — the numerator of conversion
            sub = self._subscribe(
                tenant, paid, SubscriptionStatus.ACTIVE, now, trial_end=now - timedelta(days=20)
            )
            self._method(tenant, "stripe")
            self._history(tenant, sub, months=1, succeed=True)
        else:  # trial that lapsed without converting — the denominator
            self._subscribe(
                tenant, family, SubscriptionStatus.TRIALING, now, trial_end=now - timedelta(days=10)
            )

    def _subscribe(self, tenant, plan, status, now, trial_end=None) -> Subscription:
        sub = Subscription.objects.create(
            tenant_id=tenant.id,
            plan=plan,
            status=status,
            current_period_start=now - timedelta(days=5),
            # A concluded trial has already rolled into a paid period, so the
            # period end must still be in the future — only a *running* trial
            # ends when the trial does.
            current_period_end=(
                trial_end if (trial_end and trial_end > now) else now + timedelta(days=25)
            ),
            trial_end=trial_end,
        )
        # Age the subscription to match the workspace it belongs to. Churn's
        # denominator is "subscriptions that predate the window", so leaving
        # every seeded subscription created *now* puts a single cancellation
        # over a base of zero and reports 100% churn — arithmetically correct,
        # and a completely misleading first impression of the console.
        Subscription.objects.filter(pk=sub.pk).update(created_at=tenant.created_at)
        sub.refresh_from_db()
        return sub

    def _method(self, tenant, provider) -> PaymentMethod:
        card = provider == "stripe"
        return PaymentMethod.objects.create(
            tenant_id=tenant.id,
            kind=PaymentMethodKind.CARD if card else PaymentMethodKind.MPESA,
            is_default=True,
            brand="visa" if card else "",
            last4="4242" if card else "",
            exp_month=12 if card else None,
            exp_year=2030 if card else None,
            phone_masked="" if card else "+2547****678",
            provider=provider,
            provider_ref=f"pm_seed_{tenant.id.hex[:12]}",
        )

    def _history(self, tenant, sub, *, months: int, succeed: bool) -> None:
        """Back-fill paid invoices and payments so revenue charts have shape."""
        now = timezone.now()
        # Includes offset 0 — the current month. Without a payment inside the
        # trailing 30 days, `payment_success_rate` sees only the seeded failure
        # and reports 0%, and the current month of the revenue series is empty.
        for offset in range(months - 1, -1, -1):
            issued = (now - timedelta(days=30 * offset)).date()
            invoice = invoicing.create_invoice(
                tenant_id=tenant.id,
                currency=sub.plan.currency,
                line_items=[
                    invoicing.LineItemSpec(
                        description=f"{sub.plan.name} subscription",
                        amount_minor=sub.plan.price_minor,
                    )
                ],
                subscription=sub,
                issue_date=issued,
                due_date=issued + timedelta(days=14),
                billing_email=tenant.billing_email,
                billing_country=tenant.country,
                # Credit is skipped so seeded history stays predictable — a
                # credit consumed here would silently change the totals a
                # later scenario depends on.
                apply_credit=False,
                status=InvoiceStatus.DRAFT,
            )
            invoicing.issue_invoice(invoice=invoice)

            if not succeed:
                continue
            payment = Payment.objects.create(
                tenant_id=tenant.id,
                subscription=sub,
                amount_minor=invoice.total_minor,
                currency=invoice.currency,
                status=PaymentStatus.SUCCEEDED,
                provider=sub.provider or "stripe",
                provider_ref=f"pi_seed_{tenant.id.hex[:8]}_{offset}",
                description=f"{sub.plan.name} subscription",
            )
            # Backdate so the monthly revenue series spreads across months
            # rather than landing entirely in the current one.
            Payment.objects.filter(pk=payment.pk).update(
                created_at=now - timedelta(days=30 * offset)
            )
            invoicing.mark_paid(invoice=invoice, payment=payment)

    # ----------------------------------------------------------------- output
    def _report(self, staff: PlatformStaff, password: str, *, tenants: int) -> None:
        out = self.stdout
        out.write("")
        out.write(self.style.SUCCESS("Platform admin ready."))
        out.write("")
        out.write(f"  Console   {self._console_url()}")
        out.write(f"  Email     {staff.user.email}")
        out.write(f"  Password  {password}")
        out.write(f"  Role      {PlatformRole(staff.role).label}")
        out.write("")

        if staff.require_mfa:
            out.write(
                self.style.WARNING(
                    "  2FA is required on this account. Enrol an authenticator in the\n"
                    "  customer app's security settings before the console will let you in,\n"
                    "  or re-run without --require-mfa."
                )
            )
        else:
            out.write(
                self.style.WARNING(
                    "  2FA is waived on this account — development only. Production staff\n"
                    "  must keep require_mfa on."
                )
            )
        out.write("")

        if tenants:
            out.write(f"  Seeded {tenants} demo workspace(s) covering: healthy monthly and annual")
            out.write("  subscriptions, an expiring trial, an account in dunning, a suspended")
            out.write("  workspace, an overdue invoice, account credit, and a churned customer.")
            out.write(f"  Demo customer logins use the same password: {DEFAULT_PASSWORD}")
            out.write("")
            out.write("  Nothing was written inside any workspace's ledger — the seed creates")
            out.write("  control-plane data only, which is all the platform console can read.")
        out.write("")

    def _console_url(self) -> str:
        origins = getattr(settings, "CORS_ALLOWED_ORIGINS", []) or ["http://localhost:5173"]
        return f"{origins[0]}/admin"
