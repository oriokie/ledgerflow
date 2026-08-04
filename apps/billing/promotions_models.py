"""Coupons and promotional campaigns.

One model covers percentage discounts, fixed discounts, free months and trial
extensions rather than four models with a shared base. They differ only in how
`value` is interpreted (basis points / minor units / months / days) and share
every other concern — eligibility windows, redemption limits, plan and country
restrictions, campaign reporting. Four tables would duplicate all of that and
make "how did the spring campaign perform" a four-way union.

The cost of the single-table choice is that `value` is polymorphic, so it is
never read directly: `discount_for()` in `promotions.py` is the only place
that interprets it.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel, UUIDModel


class CouponKind(models.TextChoices):
    PERCENT = "percent", "Percentage off"
    FIXED = "fixed", "Fixed amount off"
    FREE_MONTHS = "free_months", "Free months"
    TRIAL_EXTENSION = "trial_extension", "Trial extension"


class CouponDuration(models.TextChoices):
    ONCE = "once", "Once"
    REPEATING = "repeating", "Repeating"
    FOREVER = "forever", "Forever"


class Coupon(UUIDModel, TimeStampedModel):
    """A redeemable promotion.

    Global (not tenant-scoped) — a coupon is part of the platform's commercial
    catalog, like `Plan`, and restricting which tenants may use it is done via
    the eligibility fields rather than by ownership.
    """

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True, default="")

    kind = models.CharField(max_length=20, choices=CouponKind.choices)
    #: Interpretation depends on `kind`:
    #:   PERCENT         -> basis points (2500 = 25%)
    #:   FIXED           -> minor units of `currency`
    #:   FREE_MONTHS     -> whole months
    #:   TRIAL_EXTENSION -> days
    #: Never read directly; go through `promotions.discount_for()`.
    value = models.PositiveIntegerField()
    #: Only meaningful for FIXED. A fixed discount is inherently currency-bound
    #: — "$10 off" cannot be applied to a KES invoice — so a FIXED coupon that
    #: doesn't match the invoice currency is rejected rather than converted, to
    #: avoid an FX rate silently changing a promised discount.
    currency = models.CharField(max_length=3, blank=True, default="")

    duration = models.CharField(max_length=12, choices=CouponDuration.choices, default=CouponDuration.ONCE)
    duration_in_months = models.PositiveSmallIntegerField(null=True, blank=True)

    # Eligibility
    applies_to_plans = models.ManyToManyField(
        "billing.Plan", blank=True, related_name="coupons"
    )  # empty = every plan
    allowed_countries = models.JSONField(default=list, blank=True)  # empty = everywhere; ISO-3166 alpha-2
    starts_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    # Limits
    max_redemptions = models.PositiveIntegerField(null=True, blank=True)  # null = unlimited
    max_redemptions_per_tenant = models.PositiveSmallIntegerField(default=1)
    redemption_count = models.PositiveIntegerField(default=0)

    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="coupons_created",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_active", "-created_at"]),
            models.Index(fields=["kind"]),
        ]

    def __str__(self) -> str:
        return self.code

    def save(self, *args, **kwargs):
        # Codes are matched case-insensitively by customers typing them in;
        # normalising on write keeps the unique constraint meaningful rather
        # than letting SAVE20 and save20 both exist.
        if self.code:
            self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    @property
    def is_exhausted(self) -> bool:
        return self.max_redemptions is not None and self.redemption_count >= self.max_redemptions

    @property
    def is_live(self) -> bool:
        now = timezone.now()
        if not self.is_active or self.is_exhausted:
            return False
        if self.starts_at and now < self.starts_at:
            return False
        return not (self.expires_at and now >= self.expires_at)


class CouponRedemption(UUIDModel, TimeStampedModel):
    """One tenant's use of one coupon. The unit of campaign reporting."""

    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name="redemptions")
    tenant_id = models.UUIDField(db_index=True)
    subscription = models.ForeignKey(
        "billing.Subscription", null=True, blank=True, on_delete=models.SET_NULL, related_name="redemptions"
    )
    invoice = models.ForeignKey(
        "billing.Invoice", null=True, blank=True, on_delete=models.SET_NULL, related_name="redemptions"
    )
    #: What the discount was actually worth, in the invoice's currency. Stored
    #: because campaign ROI has to be answerable without re-deriving every
    #: historical discount from a coupon whose terms may since have changed.
    discount_minor = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, blank=True, default="")
    #: For REPEATING coupons: how many billing periods this redemption has
    #: already discounted, so it stops after `duration_in_months`.
    periods_applied = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["coupon", "-created_at"]),
            models.Index(fields=["tenant_id", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.coupon_id} redeemed by {self.tenant_id}"
