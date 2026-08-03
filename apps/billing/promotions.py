"""Coupon eligibility and discount arithmetic.

`discount_for()` is the only place in the codebase that interprets
`Coupon.value`, which is what makes the single polymorphic column safe. Adding
a new coupon kind means adding a branch here and nowhere else.

Eligibility returns a *reason* rather than a bool. "This coupon isn't valid" is
a terrible thing to show someone typing a code from an email they received
yesterday; "This coupon expired on 3 March" is actionable, and support can see
the same string the customer saw.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Plan, Subscription
from .promotions_models import Coupon, CouponDuration, CouponKind, CouponRedemption

logger = logging.getLogger("ledgerflow.billing.promotions")


class CouponError(Exception):
    """Raised when a coupon cannot be applied. The message is customer-safe."""


@dataclass(frozen=True)
class Eligibility:
    ok: bool
    reason: str = ""

    def raise_if_bad(self) -> None:
        if not self.ok:
            raise CouponError(self.reason)


def find_coupon(code: str) -> Coupon | None:
    if not code:
        return None
    return Coupon.objects.filter(code=code.strip().upper()).first()


def check_eligibility(
    *,
    coupon: Coupon,
    tenant_id,
    plan: Plan | None = None,
    country: str = "",
    currency: str = "",
) -> Eligibility:
    """Decide whether this tenant may redeem this coupon right now."""
    now = timezone.now()

    if not coupon.is_active:
        return Eligibility(False, "This promotion is no longer running.")
    if coupon.starts_at and now < coupon.starts_at:
        return Eligibility(False, f"This promotion starts on {coupon.starts_at:%-d %B %Y}.")
    if coupon.expires_at and now >= coupon.expires_at:
        return Eligibility(False, f"This promotion expired on {coupon.expires_at:%-d %B %Y}.")
    if coupon.is_exhausted:
        return Eligibility(False, "This promotion has been fully claimed.")

    if coupon.allowed_countries:
        allowed = {str(c).upper() for c in coupon.allowed_countries}
        if (country or "").upper() not in allowed:
            return Eligibility(False, "This promotion isn't available in your country.")

    if (
        plan is not None
        and coupon.applies_to_plans.exists()
        and not coupon.applies_to_plans.filter(pk=plan.pk).exists()
    ):
        return Eligibility(False, f"This promotion doesn't apply to the {plan.name} plan.")

    # A fixed-amount discount is currency-bound; converting it would let an FX
    # move silently change the value of a promise already made to a customer.
    if coupon.kind == CouponKind.FIXED:
        target = (currency or (plan.currency if plan else "")).upper()
        if coupon.currency and target and coupon.currency.upper() != target:
            return Eligibility(False, f"This promotion only applies to {coupon.currency} billing.")

    used = CouponRedemption.objects.filter(coupon=coupon, tenant_id=tenant_id).count()
    if used >= coupon.max_redemptions_per_tenant:
        return Eligibility(False, "You've already used this promotion.")

    return Eligibility(True)


def discount_for(*, coupon: Coupon, amount_minor: int, currency: str = "") -> int:
    """Monetary discount this coupon applies to `amount_minor`.

    Non-monetary kinds (free months, trial extension) return 0: they change the
    subscription's *dates*, not an invoice total, and are applied by
    `apply_to_subscription`. Returning 0 rather than raising keeps callers that
    just want "what comes off this invoice" branch-free.
    """
    if amount_minor <= 0:
        return 0

    if coupon.kind == CouponKind.PERCENT:
        # Round half-up on the discount, which favours the customer by at most
        # one minor unit and never produces a total above the undiscounted one.
        return min(round(amount_minor * coupon.value / 10_000), amount_minor)

    if coupon.kind == CouponKind.FIXED:
        if coupon.currency and currency and coupon.currency.upper() != currency.upper():
            raise CouponError(f"This promotion only applies to {coupon.currency} billing.")
        return min(coupon.value, amount_minor)

    return 0


def bonus_days(*, coupon: Coupon) -> int:
    """Extra trial days a TRIAL_EXTENSION coupon grants."""
    return coupon.value if coupon.kind == CouponKind.TRIAL_EXTENSION else 0


def free_months(*, coupon: Coupon) -> int:
    return coupon.value if coupon.kind == CouponKind.FREE_MONTHS else 0


@transaction.atomic
def redeem(
    *,
    coupon: Coupon,
    tenant_id,
    subscription: Subscription | None = None,
    invoice=None,
    discount_minor: int = 0,
    currency: str = "",
    plan: Plan | None = None,
    country: str = "",
) -> CouponRedemption:
    """Record a redemption and consume one of the coupon's uses.

    Eligibility is re-checked here even when the caller has already checked it.
    Between a quote and a confirmation the coupon may have been exhausted by
    someone else, and the check is cheap relative to honouring a promotion that
    ran out.

    The counter is bumped with an `F()` expression so concurrent redemptions
    increment rather than overwrite each other.
    """
    locked = Coupon.objects.select_for_update().get(pk=coupon.pk)
    check_eligibility(
        coupon=locked, tenant_id=tenant_id, plan=plan, country=country, currency=currency
    ).raise_if_bad()

    redemption = CouponRedemption.objects.create(
        coupon=locked,
        tenant_id=tenant_id,
        subscription=subscription,
        invoice=invoice,
        discount_minor=max(int(discount_minor), 0),
        currency=(currency or "").upper(),
        periods_applied=1 if discount_minor else 0,
    )
    Coupon.objects.filter(pk=locked.pk).update(
        redemption_count=F("redemption_count") + 1, updated_at=timezone.now()
    )
    return redemption


def active_redemption(*, tenant_id, subscription: Subscription | None = None) -> CouponRedemption | None:
    """The redemption that should discount this tenant's next invoice, if any.

    Encodes the duration rules: ONCE is spent after its first period, REPEATING
    lasts `duration_in_months` periods, FOREVER never lapses.
    """
    query = CouponRedemption.objects.filter(tenant_id=tenant_id).select_related("coupon")
    if subscription is not None:
        query = query.filter(subscription=subscription)

    for redemption in query.order_by("-created_at"):
        coupon = redemption.coupon
        if coupon.duration == CouponDuration.FOREVER:
            return redemption
        if coupon.duration == CouponDuration.REPEATING:
            limit = coupon.duration_in_months or 1
            if redemption.periods_applied < limit:
                return redemption
        # ONCE: consumed at redemption time.
    return None


@transaction.atomic
def consume_period(*, redemption: CouponRedemption) -> CouponRedemption:
    """Mark that a repeating redemption discounted one more billing period."""
    redemption.periods_applied = F("periods_applied") + 1
    redemption.save(update_fields=["periods_applied", "updated_at"])
    redemption.refresh_from_db(fields=["periods_applied"])
    return redemption
