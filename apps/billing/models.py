"""
Billing domain.

Design notes
------------
* **Plans** are a *global* platform catalog (not tenant-scoped) — every
  workspace chooses from the same menu. They use plain UUIDModel, no RLS.
* **Subscriptions / PaymentMethods / Payments** belong to a tenant, but unlike
  financial data they must also be reachable from *platform* context — a
  payment-provider webhook arrives with no user and no tenant header, and has
  to locate the subscription by the provider's own reference. So these carry a
  `tenant_id` for scoping in the app UI, but are managed through a dedicated
  service layer that binds tenant context explicitly rather than relying on the
  ambient request tenant.
* Money is integer minor units everywhere, consistent with the rest of the
  product.
* Provider-specific state lives in `provider` + `provider_ref` + `metadata`,
  never in bespoke columns, so adding a provider (Stripe, M-PESA, …) doesn't
  require a schema change.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel


class BillingInterval(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    YEARLY = "yearly", "Yearly"


class PlanTier(models.TextChoices):
    FREE = "free", "Free"
    PLUS = "plus", "Plus"
    FAMILY = "family", "Family"
    BUSINESS = "business", "Business"


class Plan(UUIDModel, TimeStampedModel):
    """A purchasable plan in the platform catalog. Global, not tenant-scoped."""

    tier = models.CharField(max_length=16, choices=PlanTier.choices)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=255, blank=True, default="")
    # Price is per-interval; a plan row exists per (tier, interval, currency).
    price_minor = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="USD")
    interval = models.CharField(max_length=10, choices=BillingInterval.choices, default=BillingInterval.MONTHLY)

    # Entitlements — what the plan unlocks. Kept as explicit columns for the
    # ones the app enforces today; `features` JSON holds display bullet points.
    max_members = models.PositiveSmallIntegerField(default=1)
    max_accounts = models.PositiveSmallIntegerField(default=3)
    ai_insights = models.BooleanField(default=False)
    features = models.JSONField(default=list, blank=True)

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "price_minor"]
        constraints = [
            models.UniqueConstraint(
                fields=["tier", "interval", "currency"],
                name="uniq_plan_tier_interval_currency",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.interval})"


class SubscriptionStatus(models.TextChoices):
    TRIALING = "trialing", "Trialing"
    ACTIVE = "active", "Active"
    PAST_DUE = "past_due", "Past due"
    CANCELED = "canceled", "Canceled"
    INCOMPLETE = "incomplete", "Incomplete"  # awaiting first payment


class Subscription(UUIDModel, TimeStampedModel):
    """One active subscription per tenant. Tenant-scoped by `tenant_id` but
    managed via the billing service (which binds tenant context explicitly)
    so provider webhooks can reach it without a request tenant."""

    tenant_id = models.UUIDField(db_index=True)
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(
        max_length=16, choices=SubscriptionStatus.choices, default=SubscriptionStatus.INCOMPLETE
    )

    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    canceled_at = models.DateTimeField(null=True, blank=True)
    trial_end = models.DateTimeField(null=True, blank=True)

    # Provider linkage (Stripe subscription id, etc.). Null for the free plan
    # which needs no provider.
    provider = models.CharField(max_length=32, blank=True, default="")
    provider_ref = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant_id"], name="uniq_subscription_per_tenant"),
        ]
        indexes = [
            models.Index(fields=["provider", "provider_ref"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id} -> {self.plan_id} ({self.status})"

    @property
    def is_current(self) -> bool:
        return self.status in {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING}


class PaymentMethodKind(models.TextChoices):
    CARD = "card", "Card"
    MPESA = "mpesa", "M-PESA"


class PaymentMethod(UUIDModel, TimeStampedModel):
    """A saved way to pay. We NEVER store raw card numbers/PANs — only the
    provider's token plus safe display fields (brand, last4). PCI scope stays
    with the provider."""

    tenant_id = models.UUIDField(db_index=True)
    kind = models.CharField(max_length=16, choices=PaymentMethodKind.choices)
    is_default = models.BooleanField(default=False)

    # Safe display fields only.
    brand = models.CharField(max_length=32, blank=True, default="")  # e.g. "visa", "mastercard"
    last4 = models.CharField(max_length=4, blank=True, default="")
    exp_month = models.PositiveSmallIntegerField(null=True, blank=True)
    exp_year = models.PositiveSmallIntegerField(null=True, blank=True)
    phone_masked = models.CharField(max_length=20, blank=True, default="")  # for M-PESA, e.g. "+2547****678"

    provider = models.CharField(max_length=32)
    provider_ref = models.CharField(max_length=255)  # provider token / payment-method id
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "is_default"])]

    def __str__(self) -> str:
        if self.kind == PaymentMethodKind.CARD:
            return f"{self.brand} ****{self.last4}"
        return f"M-PESA {self.phone_masked}"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    REFUNDED = "refunded", "Refunded"


class Payment(UUIDModel, TimeStampedModel):
    """A single charge attempt. The immutable audit trail of money the platform
    has (or hasn't) collected from a tenant."""

    tenant_id = models.UUIDField(db_index=True)
    subscription = models.ForeignKey(
        Subscription, null=True, blank=True, on_delete=models.SET_NULL, related_name="payments"
    )
    amount_minor = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)

    provider = models.CharField(max_length=32)
    provider_ref = models.CharField(max_length=255, blank=True, default="")  # charge/intent id
    description = models.CharField(max_length=255, blank=True, default="")
    failure_reason = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant_id", "status"]),
            models.Index(fields=["provider", "provider_ref"]),
        ]

    def __str__(self) -> str:
        return f"{self.amount_minor} {self.currency} [{self.status}]"


class WebhookEvent(UUIDModel, TimeStampedModel):
    """Idempotency + audit for inbound provider webhooks. We record every event
    id we've seen so a provider's at-least-once delivery never double-applies."""

    provider = models.CharField(max_length=32)
    event_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "event_id"], name="uniq_webhook_provider_event"),
        ]
        indexes = [models.Index(fields=["provider", "event_type"])]

    def __str__(self) -> str:
        return f"{self.provider}:{self.event_type}:{self.event_id}"


# Concrete models defined in sibling modules, registered here so migrations
# and `apps.billing.models` imports see one coherent namespace. Same pattern
# as apps/users/models.py.
from .dunning_models import (  # noqa: E402,F401
    DEFAULT_RETRY_OFFSETS,
    DunningAttempt,
    DunningAttemptKind,
    DunningAttemptOutcome,
    DunningCase,
    DunningCaseStatus,
    DunningPolicy,
)
from .invoicing_models import (  # noqa: E402,F401
    Credit,
    CreditApplication,
    CreditKind,
    Invoice,
    InvoiceLineItem,
    InvoiceSequence,
    InvoiceStatus,
    Refund,
    RefundStatus,
)
from .promotions_models import (  # noqa: E402,F401
    Coupon,
    CouponDuration,
    CouponKind,
    CouponRedemption,
)
