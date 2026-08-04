"""SaaS metrics.

Definitions are stated explicitly because these numbers get quoted to boards
and investors, and "our MRR" means nothing without saying which convention
produced it. The conventions used here:

* **MRR** is normalised recurring revenue: an annual plan contributes
  ``price / 12`` every month, not its full value in the month it bills. Without
  normalising, MRR spikes and collapses on the annual renewal cycle and stops
  being a run-rate at all.
* **Complimentary subscriptions are excluded.** A comped account is real usage
  but zero revenue; counting it would inflate the one number that must not be
  inflated. `Subscription.metadata["complimentary"]` marks these.
* **Trialing subscriptions are excluded from MRR** and counted separately.
  Trial revenue is not revenue until it converts.
* **Churn** is customer churn over a window: subscriptions that were current at
  the start and are not at the end, over the count at the start.
* **LTV** is ``ARPA / monthly churn rate``, the standard simplification. It is
  reported as null rather than infinity when churn is zero, because a
  divide-by-zero dressed up as a number is worse than an honest absence.

Everything is computed on demand from `Subscription` and `Payment`. Nothing is
persisted, so a definition change takes effect everywhere at once instead of
leaving a stale aggregate table disagreeing with the live one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.billing.invoicing_models import Refund, RefundStatus
from apps.billing.models import (
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionStatus,
)
from apps.tenancy.models import Tenant

from .cache import cached_platform

#: Subscription states that represent a paying customer right now.
CURRENT_STATUSES = (SubscriptionStatus.ACTIVE,)
#: States that represent a live relationship, paying or not.
LIVE_STATUSES = (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING)


def _monthly_minor(price_minor: int, interval: str) -> int:
    return round(price_minor / 12) if interval == "yearly" else price_minor


def _revenue_subscriptions():
    """Current subscriptions that actually bill.

    Excludes comps and zero-price plans. A free-plan user is a customer for
    engagement purposes and contributes nothing to revenue, so including them
    would drag ARPA toward zero and make it meaningless.
    """
    # NOTE: `.exclude(metadata__complimentary=True)` looks equivalent and is
    # not. For a row whose JSON has no `complimentary` key at all — which is
    # every ordinary subscription — the path lookup yields SQL NULL, so
    # `NOT (... = true)` evaluates to NULL rather than TRUE and Postgres drops
    # the row. That silently returned an empty set and reported zero MRR for
    # the whole platform. Excluding by an explicit id subquery keeps the
    # three-valued logic inside the subquery, where a missing key correctly
    # means "not complimentary".
    comped = Subscription.objects.filter(metadata__complimentary=True).values("id")
    return (
        Subscription.objects.filter(status__in=CURRENT_STATUSES, plan__price_minor__gt=0)
        .exclude(id__in=comped)
        .select_related("plan")
    )


# ------------------------------------------------------------------ headline
@dataclass(frozen=True)
class RecurringRevenue:
    mrr_minor: int
    arr_minor: int
    paying_customers: int
    arpa_minor: int
    currency: str


def recurring_revenue(*, currency: str = "USD") -> RecurringRevenue:
    """MRR/ARR/ARPA for one currency.

    Single-currency by design. Summing across currencies needs an FX rate, and
    baking today's rate into a historical series would make last quarter's MRR
    change every time the rate moves. Callers that want a consolidated figure
    convert deliberately, at a rate they choose.
    """
    subs = _revenue_subscriptions().filter(plan__currency=currency.upper())

    mrr = 0
    count = 0
    for sub in subs:
        mrr += _monthly_minor(sub.plan.price_minor, sub.plan.interval)
        count += 1

    return RecurringRevenue(
        mrr_minor=mrr,
        arr_minor=mrr * 12,
        paying_customers=count,
        arpa_minor=round(mrr / count) if count else 0,
        currency=currency.upper(),
    )


def collected_revenue(*, start: datetime, end: datetime, currency: str = "USD") -> dict:
    """Cash actually collected in a window, net of refunds.

    Distinct from MRR: MRR is a run-rate, this is money that moved. Refunds are
    subtracted because a refunded payment is not revenue, and reporting gross
    collections as revenue is how a business talks itself into a hole.
    """
    currency = currency.upper()
    gross = (
        Payment.objects.filter(
            status__in=(PaymentStatus.SUCCEEDED, PaymentStatus.REFUNDED),
            currency=currency,
            created_at__gte=start,
            created_at__lt=end,
        ).aggregate(total=Sum("amount_minor"))["total"]
        or 0
    )
    refunded = (
        Refund.objects.filter(
            status=RefundStatus.SUCCEEDED,
            currency=currency,
            completed_at__gte=start,
            completed_at__lt=end,
        ).aggregate(total=Sum("amount_minor"))["total"]
        or 0
    )
    return {
        "gross_minor": gross,
        "refunded_minor": refunded,
        "net_minor": gross - refunded,
        "currency": currency,
    }


def lifetime_revenue(*, currency: str = "USD") -> dict:
    epoch = datetime(1970, 1, 1, tzinfo=timezone.get_current_timezone())
    return collected_revenue(start=epoch, end=timezone.now(), currency=currency)


# --------------------------------------------------------------------- churn
def churn(*, days: int = 30) -> dict:
    """Customer churn over the trailing `days`.

    Cancellations are located by `canceled_at`, and the denominator is
    reconstructed as "current at the window's start" — subscriptions live now
    that predate the window, plus those cancelled inside it. That avoids
    needing a historical snapshot table while still producing the standard
    ratio.
    """
    now = timezone.now()
    start = now - timedelta(days=days)

    churned = Subscription.objects.filter(
        status=SubscriptionStatus.CANCELED,
        canceled_at__gte=start,
        canceled_at__lte=now,
        plan__price_minor__gt=0,
    ).count()

    still_paying = Subscription.objects.filter(
        status__in=CURRENT_STATUSES, plan__price_minor__gt=0, created_at__lt=start
    ).count()

    base = still_paying + churned
    rate = (churned / base) if base else 0.0
    return {
        "window_days": days,
        "churned": churned,
        "base": base,
        "rate": round(rate, 4),
        "retention_rate": round(1 - rate, 4) if base else None,
    }


def lifetime_value(*, currency: str = "USD", churn_days: int = 30) -> dict:
    """ARPA divided by monthly churn rate.

    Returns `ltv_minor: None` when churn is zero rather than an infinity or a
    silently huge number — "we have not lost a paying customer in 30 days" is
    the honest reading, and a fabricated LTV would be quoted as if it meant
    something.
    """
    revenue = recurring_revenue(currency=currency)
    churn_stats = churn(days=churn_days)
    rate = churn_stats["rate"]

    # Normalise the churn rate to a monthly basis before dividing.
    monthly_rate = rate * (30 / churn_days) if churn_days else rate
    ltv = round(revenue.arpa_minor / monthly_rate) if monthly_rate > 0 else None

    return {
        "arpa_minor": revenue.arpa_minor,
        "monthly_churn_rate": round(monthly_rate, 4),
        "ltv_minor": ltv,
        "currency": revenue.currency,
    }


# ------------------------------------------------------------------ customers
def customer_counts() -> dict:
    """Tenant and subscription counts by lifecycle state."""
    now = timezone.now()
    tenants = Tenant.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
        suspended=Count("id", filter=Q(is_active=False)),
    )
    subs = Subscription.objects.aggregate(
        active=Count("id", filter=Q(status=SubscriptionStatus.ACTIVE)),
        trialing=Count("id", filter=Q(status=SubscriptionStatus.TRIALING)),
        past_due=Count("id", filter=Q(status=SubscriptionStatus.PAST_DUE)),
        canceled=Count("id", filter=Q(status=SubscriptionStatus.CANCELED)),
        incomplete=Count("id", filter=Q(status=SubscriptionStatus.INCOMPLETE)),
    )
    expired_trials = Subscription.objects.filter(
        status=SubscriptionStatus.TRIALING, trial_end__lt=now
    ).count()

    return {
        "tenants_total": tenants["total"],
        "tenants_active": tenants["active"],
        "tenants_suspended": tenants["suspended"],
        "subscriptions_active": subs["active"],
        "subscriptions_trialing": subs["trialing"],
        "subscriptions_past_due": subs["past_due"],
        "subscriptions_canceled": subs["canceled"],
        "subscriptions_incomplete": subs["incomplete"],
        "trials_expired": expired_trials,
    }


def signups(*, days: int = 30) -> dict:
    now = timezone.now()
    start = now - timedelta(days=days)
    previous_start = start - timedelta(days=days)

    current = Tenant.objects.filter(created_at__gte=start).count()
    previous = Tenant.objects.filter(created_at__gte=previous_start, created_at__lt=start).count()
    growth = ((current - previous) / previous) if previous else None

    return {
        "window_days": days,
        "signups": current,
        "previous": previous,
        "growth_rate": round(growth, 4) if growth is not None else None,
    }


def trial_conversion(*, days: int = 90) -> dict:
    """Share of trials started in the window that became paying customers.

    A trial is "converted" if its subscription is now ACTIVE on a paid plan.
    Trials still running are excluded from the denominator — counting a trial
    that has three days left as a failure understates conversion.
    """
    now = timezone.now()
    start = now - timedelta(days=days)

    started = Subscription.objects.filter(trial_end__isnull=False, created_at__gte=start)
    concluded = started.filter(trial_end__lt=now)
    converted = concluded.filter(status=SubscriptionStatus.ACTIVE, plan__price_minor__gt=0).count()
    total = concluded.count()

    return {
        "window_days": days,
        "trials_concluded": total,
        "converted": converted,
        "still_running": started.filter(trial_end__gte=now).count(),
        "conversion_rate": round(converted / total, 4) if total else None,
    }


# ---------------------------------------------------------------- breakdowns
def revenue_by(dimension: str, *, currency: str = "USD") -> list[dict]:
    """MRR split along one dimension: plan, country, currency or provider.

    A single function rather than four near-identical ones — they differ only
    in the grouping key, and four copies would drift the moment the comp
    exclusion rule changed.
    """
    subs = _revenue_subscriptions()
    if dimension != "currency":
        subs = subs.filter(plan__currency=currency.upper())

    if dimension == "country":
        tenant_country = dict(
            Tenant.objects.filter(id__in=[s.tenant_id for s in subs]).values_list("id", "country")
        )
        locales = dict(
            Tenant.objects.filter(id__in=[s.tenant_id for s in subs]).values_list("id", "default_locale")
        )

    buckets: dict[str, dict] = {}
    for sub in subs:
        if dimension == "plan":
            key = sub.plan.name
        elif dimension == "currency":
            key = sub.plan.currency
        elif dimension == "provider":
            key = sub.provider or "none"
        elif dimension == "country":
            key = (tenant_country.get(sub.tenant_id) or "").upper()
            if not key:
                locale = locales.get(sub.tenant_id) or ""
                region = locale.rsplit("-", 1)[-1] if "-" in locale else ""
                key = region.upper() if len(region) == 2 else "unknown"
        else:
            raise ValueError(f"Unknown revenue dimension {dimension!r}.")

        bucket = buckets.setdefault(key, {"key": key, "mrr_minor": 0, "customers": 0})
        bucket["mrr_minor"] += _monthly_minor(sub.plan.price_minor, sub.plan.interval)
        bucket["customers"] += 1

    return sorted(buckets.values(), key=lambda b: b["mrr_minor"], reverse=True)


def payment_success_rate(*, days: int = 30) -> dict:
    now = timezone.now()
    start = now - timedelta(days=days)
    rows = Payment.objects.filter(created_at__gte=start).aggregate(
        total=Count("id"),
        succeeded=Count("id", filter=Q(status=PaymentStatus.SUCCEEDED)),
        failed=Count("id", filter=Q(status=PaymentStatus.FAILED)),
        pending=Count("id", filter=Q(status=PaymentStatus.PENDING)),
    )
    total = rows["total"] or 0
    return {
        "window_days": days,
        "total": total,
        "succeeded": rows["succeeded"],
        "failed": rows["failed"],
        "pending": rows["pending"],
        "success_rate": round(rows["succeeded"] / total, 4) if total else None,
    }


def monthly_revenue_series(*, months: int = 12, currency: str = "USD") -> list[dict]:
    """Net collected revenue per calendar month, oldest first.

    The final point is always the *current* month, which on any day but the last
    is a partial period. Plotted without a flag it reads as a collapse — on the
    3rd of the month the chart showed revenue falling from its peak to nearly
    zero, which is the same defect already fixed twice in this product (the MRR
    delta on this dashboard, and "expenses ↘ 97%" on customer Analytics).

    So each point says whether it is complete, and the client renders the
    incomplete one as unsettled rather than drawing it like a fact.
    """
    now = timezone.now()
    current_month = date(now.year, now.month, 1)
    series = []
    cursor = current_month

    for _ in range(months):
        start = datetime(cursor.year, cursor.month, 1, tzinfo=now.tzinfo)
        end = (
            datetime(cursor.year + 1, 1, 1, tzinfo=now.tzinfo)
            if cursor.month == 12
            else datetime(cursor.year, cursor.month + 1, 1, tzinfo=now.tzinfo)
        )
        totals = collected_revenue(start=start, end=end, currency=currency)
        series.append({"month": cursor.isoformat(), "partial": cursor == current_month, **totals})
        cursor = date(cursor.year - 1, 12, 1) if cursor.month == 1 else date(cursor.year, cursor.month - 1, 1)

    return list(reversed(series))


def cohort_retention(*, months: int = 6) -> list[dict]:
    """Signup cohorts and how many of each still hold a live subscription.

    Deliberately simple — retention by cohort month, not a full triangular
    cohort matrix. The triangle needs historical state snapshots to be honest;
    reconstructing it from current rows would silently attribute today's status
    to every past period.
    """
    now = timezone.now()
    cohorts: list[dict] = []
    cursor = date(now.year, now.month, 1)

    for _ in range(months):
        start = datetime(cursor.year, cursor.month, 1, tzinfo=now.tzinfo)
        end = (
            datetime(cursor.year + 1, 1, 1, tzinfo=now.tzinfo)
            if cursor.month == 12
            else datetime(cursor.year, cursor.month + 1, 1, tzinfo=now.tzinfo)
        )
        tenant_ids = list(
            Tenant.objects.filter(created_at__gte=start, created_at__lt=end).values_list("id", flat=True)
        )
        retained = (
            Subscription.objects.filter(tenant_id__in=tenant_ids, status__in=LIVE_STATUSES).count()
            if tenant_ids
            else 0
        )
        cohorts.append(
            {
                "cohort": cursor.isoformat(),
                "signups": len(tenant_ids),
                "retained": retained,
                "retention_rate": round(retained / len(tenant_ids), 4) if tenant_ids else None,
            }
        )
        cursor = date(cursor.year - 1, 12, 1) if cursor.month == 1 else date(cursor.year, cursor.month - 1, 1)

    return list(reversed(cohorts))


def forecast_revenue(*, months_ahead: int = 6, currency: str = "USD") -> list[dict]:
    """Project MRR forward from current MRR and recent net growth.

    A straight-line projection off the trailing three months, explicitly
    labelled as such. Anything more elaborate would imply a confidence the
    input data does not support, and an operator reading a dashboard deserves
    to know they are looking at an extrapolation rather than a model.
    """
    current = recurring_revenue(currency=currency)
    history = monthly_revenue_series(months=4, currency=currency)

    growths = []
    for previous, following in zip(history, history[1:], strict=False):
        if previous["net_minor"] > 0:
            growths.append((following["net_minor"] - previous["net_minor"]) / previous["net_minor"])
    rate = sum(growths) / len(growths) if growths else 0.0
    # Clamp: a single anomalous month must not project a 400% run-rate.
    rate = max(min(rate, 0.5), -0.5)

    projection = []
    value = current.mrr_minor
    for offset in range(1, months_ahead + 1):
        value = round(value * (1 + rate))
        projection.append(
            {
                "month_offset": offset,
                "projected_mrr_minor": value,
                "currency": current.currency,
                "basis": "linear extrapolation of trailing 3-month net revenue growth",
            }
        )
    return projection


# ------------------------------------------------------------------ dashboard
@cached_platform("dashboard", ttl=120)
def dashboard(*, currency: str = "USD") -> dict:
    """Everything the executive dashboard needs, in one call.

    Cached briefly. The console is polled by several operators at once and
    these aggregates move on the scale of minutes, not seconds; a two-minute
    window removes almost all of the repeated work while keeping the numbers
    current enough to act on.
    """
    now = timezone.now()
    today_start = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
    month_start = datetime(now.year, now.month, 1, tzinfo=now.tzinfo)

    revenue = recurring_revenue(currency=currency)
    return {
        "generated_at": now,
        "currency": currency.upper(),
        "revenue": {
            **asdict(revenue),
            "today": collected_revenue(start=today_start, end=now, currency=currency),
            "month_to_date": collected_revenue(start=month_start, end=now, currency=currency),
            "lifetime": lifetime_revenue(currency=currency),
        },
        "customers": {**customer_counts(), **signups(days=30)},
        "churn": churn(days=30),
        "ltv": lifetime_value(currency=currency),
        "trials": trial_conversion(days=90),
        "payments": payment_success_rate(days=30),
        "by_plan": revenue_by("plan", currency=currency),
        "by_country": revenue_by("country", currency=currency),
        "by_currency": revenue_by("currency"),
        "by_provider": revenue_by("provider", currency=currency),
    }
