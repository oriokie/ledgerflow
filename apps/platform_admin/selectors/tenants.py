"""Read-side queries for the tenant directory.

The directory is the busiest screen in the console and the easiest place to
write an accidental N+1: every row wants a member count, an owner, a plan, a
last-payment date and a usage figure, and fetching those per row turns a
50-row page into 250 queries.

Everything here is therefore built from annotations and one bulk map lookup per
related dataset, so listing N tenants costs a fixed handful of queries
regardless of N. `search_tenants` is written to stay index-friendly at
thousands of tenants; it does not use `icontains` on a joined table.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.utils import timezone

from apps.billing.models import Payment, PaymentStatus, Subscription, SubscriptionStatus
from apps.tenancy.models import Membership, Role, Tenant

from ..models import TenantUsageSnapshot

#: Fields the directory can be ordered by, mapped to real ORM expressions.
#: An allowlist rather than passing the client's string to `order_by` — that
#: would let a caller order by an unindexed column and table-scan production.
SORTABLE = {
    "name": "name",
    "created_at": "created_at",
    "members": "member_count",
    "last_activity": "last_activity",
}


def tenant_queryset():
    """Base directory queryset with the per-row aggregates annotated."""
    return Tenant.objects.annotate(
        member_count=Count("memberships", distinct=True),
        last_activity=Max("memberships__user__last_login_at"),
    )


def search_tenants(
    *,
    query: str = "",
    status: str = "",
    plan_id=None,
    country: str = "",
    subscription_status: str = "",
    created_after=None,
    created_before=None,
    order_by: str = "-created_at",
):
    """Filtered, annotated tenant list.

    `status` covers the lifecycle states an operator thinks in terms of
    (active / suspended / trialing / past_due), which do not map to a single
    column — suspension lives on the tenant, trial state on the subscription.
    Resolving that here keeps the API layer from assembling filters by hand.
    """
    qs = tenant_queryset()

    if query:
        term = query.strip()
        qs = qs.filter(
            Q(name__icontains=term)
            | Q(billing_email__icontains=term)
            | Q(memberships__user__email__icontains=term)
        ).distinct()

    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "suspended":
        qs = qs.filter(is_active=False)

    if country:
        qs = qs.filter(country__iexact=country)

    if created_after:
        qs = qs.filter(created_at__gte=created_after)
    if created_before:
        qs = qs.filter(created_at__lte=created_before)

    if plan_id or subscription_status:
        sub_filter = Subscription.objects.filter(tenant_id=OuterRef("id"))
        if plan_id:
            sub_filter = sub_filter.filter(plan_id=plan_id)
        if subscription_status:
            sub_filter = sub_filter.filter(status=subscription_status)
        qs = qs.filter(id__in=Subquery(sub_filter.values("tenant_id")))

    direction = "-" if order_by.startswith("-") else ""
    key = order_by.lstrip("-")
    field = SORTABLE.get(key, "created_at")
    return qs.order_by(f"{direction}{field}", "-created_at")


# --------------------------------------------------------------- bulk lookups
def subscriptions_by_tenant(tenant_ids) -> dict:
    return {
        sub.tenant_id: sub
        for sub in Subscription.objects.filter(tenant_id__in=tenant_ids).select_related("plan")
    }


def owners_by_tenant(tenant_ids) -> dict:
    """First owner per tenant. One query, not one per row."""
    owners: dict = {}
    rows = (
        Membership.objects.filter(tenant_id__in=tenant_ids, role=Role.OWNER)
        .select_related("user")
        .order_by("tenant_id", "created_at")
    )
    for membership in rows:
        owners.setdefault(membership.tenant_id, membership.user)
    return owners


def last_payment_by_tenant(tenant_ids) -> dict:
    rows = (
        Payment.objects.filter(tenant_id__in=tenant_ids, status=PaymentStatus.SUCCEEDED)
        .values("tenant_id")
        .annotate(last_at=Max("created_at"))
    )
    return {row["tenant_id"]: row["last_at"] for row in rows}


def latest_usage_by_tenant(tenant_ids) -> dict:
    """Most recent usage snapshot per tenant.

    A subquery on `captured_at` rather than a Python-side "sort and take the
    first", so the database returns one row per tenant instead of every
    snapshot ever taken.
    """
    newest = TenantUsageSnapshot.objects.filter(tenant_id=OuterRef("tenant_id")).order_by("-captured_at")
    rows = TenantUsageSnapshot.objects.filter(
        tenant_id__in=tenant_ids,
        captured_at=Subquery(newest.values("captured_at")[:1]),
    )
    return {row.tenant_id: row for row in rows}


def directory_page(tenants) -> list[dict]:
    """Assemble the display rows for a page of tenants.

    Takes an already-sliced list so pagination happens in the database. Four
    bulk queries follow, regardless of page size.
    """
    tenant_ids = [t.id for t in tenants]
    subs = subscriptions_by_tenant(tenant_ids)
    owners = owners_by_tenant(tenant_ids)
    payments = last_payment_by_tenant(tenant_ids)
    usage = latest_usage_by_tenant(tenant_ids)

    rows = []
    for tenant in tenants:
        sub = subs.get(tenant.id)
        owner = owners.get(tenant.id)
        snapshot = usage.get(tenant.id)
        rows.append(
            {
                "id": str(tenant.id),
                "name": tenant.name,
                "type": tenant.type,
                "is_active": tenant.is_active,
                "country": tenant.resolved_country,
                "timezone": tenant.default_timezone,
                "currency": tenant.base_currency,
                "locale": tenant.default_locale,
                "billing_email": tenant.billing_email,
                "owner_email": owner.email if owner else "",
                "owner_name": owner.full_name if owner else "",
                "member_count": getattr(tenant, "member_count", 0),
                "plan_name": sub.plan.name if sub else "",
                "plan_id": str(sub.plan_id) if sub else None,
                "subscription_status": sub.status if sub else "",
                "trial_ends_at": sub.trial_end if sub else None,
                "current_period_end": sub.current_period_end if sub else None,
                "mrr_minor": _mrr_minor(sub),
                "created_at": tenant.created_at,
                "last_activity": getattr(tenant, "last_activity", None),
                "last_payment_at": payments.get(tenant.id),
                "storage_bytes": snapshot.storage_bytes if snapshot else 0,
                "transaction_count": snapshot.transaction_count if snapshot else 0,
            }
        )
    return rows


def _mrr_minor(sub: Subscription | None) -> int:
    """Normalise a subscription's price to a monthly figure.

    Annual plans are divided by 12 rather than counted at full value in the
    month they are billed, which is what makes MRR a smooth series instead of
    one with a spike every January.
    """
    if sub is None or not sub.is_current:
        return 0
    price = sub.plan.price_minor
    return round(price / 12) if sub.plan.interval == "yearly" else price


# ------------------------------------------------------------------- detail
def tenant_detail(tenant: Tenant) -> dict:
    """The full record for one workspace.

    Note what is absent: any financial content. Balances, transactions and
    account names are RLS-protected and stay that way. The console shows who
    the customer is and what they pay, never what they spend — seeing that
    requires an audited impersonation grant.
    """
    sub = Subscription.objects.filter(tenant_id=tenant.id).select_related("plan").first()
    members = list(Membership.objects.filter(tenant=tenant).select_related("user").order_by("created_at"))
    snapshot = TenantUsageSnapshot.objects.filter(tenant_id=tenant.id).order_by("-captured_at").first()

    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "type": tenant.type,
        "is_active": tenant.is_active,
        "ai_enabled": tenant.ai_enabled,
        "country": tenant.resolved_country,
        "timezone": tenant.default_timezone,
        "locale": tenant.default_locale,
        "currency": tenant.base_currency,
        "billing_email": tenant.billing_email,
        "created_at": tenant.created_at,
        "subscription": _subscription_dict(sub),
        "members": [
            {
                "id": str(m.id),
                "user_id": str(m.user_id),
                "email": m.user.email,
                "name": m.user.full_name,
                "role": m.role,
                "last_login_at": m.user.last_login_at,
                "is_active": m.user.is_active,
                "joined_at": m.created_at,
            }
            for m in members
        ],
        "usage": {
            "captured_at": snapshot.captured_at if snapshot else None,
            "member_count": len(members),
            "account_count": snapshot.account_count if snapshot else 0,
            "transaction_count": snapshot.transaction_count if snapshot else 0,
            "attachment_count": snapshot.attachment_count if snapshot else 0,
            "storage_bytes": snapshot.storage_bytes if snapshot else 0,
        },
    }


def _subscription_dict(sub: Subscription | None) -> dict | None:
    if sub is None:
        return None
    return {
        "id": str(sub.id),
        "plan_id": str(sub.plan_id),
        "plan_name": sub.plan.name,
        "plan_tier": sub.plan.tier,
        "interval": sub.plan.interval,
        "price_minor": sub.plan.price_minor,
        "currency": sub.plan.currency,
        "status": sub.status,
        "trial_end": sub.trial_end,
        "current_period_start": sub.current_period_start,
        "current_period_end": sub.current_period_end,
        "cancel_at_period_end": sub.cancel_at_period_end,
        "canceled_at": sub.canceled_at,
        "provider": sub.provider,
        "mrr_minor": _mrr_minor(sub),
    }


def expiring_trials(*, within_days: int = 7):
    """Trials ending soon — the input to both a dashboard card and a save play."""
    now = timezone.now()
    return (
        Subscription.objects.filter(
            status=SubscriptionStatus.TRIALING,
            trial_end__gte=now,
            trial_end__lte=now + timedelta(days=within_days),
        )
        .select_related("plan")
        .order_by("trial_end")
    )
