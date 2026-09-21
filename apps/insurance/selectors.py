"""Insurance read side — cover versus what is actually owned, and what is committed.

Nothing here is stored. Cover against a house is the gap between two known
numbers (the policy's sum insured and the asset's latest valuation), and a
cached gap is a gap that silently goes stale the moment either is edited.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.utils import timezone

from .models import PAYMENTS_PER_YEAR, InsurancePolicy


def annual_premium_minor(premium_minor: int, frequency: str) -> int:
    return premium_minor * PAYMENTS_PER_YEAR.get(frequency, 1)


def monthly_premium_minor(premium_minor: int, frequency: str) -> int:
    """Level monthly run-rate. Integer division: a rounding penny a year is
    cheaper than inventing cash-flow precision the premium was never quoted to.
    """
    return annual_premium_minor(premium_minor, frequency) // 12


@dataclass(frozen=True, slots=True)
class PolicyView:
    policy_id: str
    name: str
    kind: str
    insurer: str
    currency: str
    coverage_minor: int | None
    deductible_minor: int | None
    premium_minor: int
    premium_frequency: str
    annual_premium_minor: int
    monthly_premium_minor: int
    renews_on: date | None
    ends_on: date | None
    covers_asset_id: str | None
    covers_asset_name: str | None
    asset_value_minor: int | None
    #: Cover minus asset value. Negative means underinsured. None when either
    #: figure is missing — the product does not invent a gap.
    coverage_gap_minor: int | None
    covers_account_id: str | None
    covers_account_name: str | None
    bill_id: str | None
    recurring_transaction_id: str | None
    premium_in_cashflow: bool
    is_active: bool
    notes: str

    @property
    def underinsured(self) -> bool:
        return self.coverage_gap_minor is not None and self.coverage_gap_minor < 0


def _asset_value_minor(asset) -> int | None:
    if asset is None:
        return None
    latest = asset.valuations.order_by("-as_of").first()
    if latest is None:
        return None
    return latest.value_minor


def policy_views(*, as_of: date | None = None) -> list[PolicyView]:
    as_of = as_of or timezone.localdate()
    rows = InsurancePolicy.objects.select_related(
        "covers_asset", "covers_account", "bill", "recurring_transaction"
    ).prefetch_related("covers_asset__valuations")

    views: list[PolicyView] = []
    for policy in rows:
        asset = policy.covers_asset
        asset_value = _asset_value_minor(asset)
        coverage = policy.coverage_minor
        gap = None
        if coverage is not None and asset_value is not None:
            gap = coverage - asset_value
        linked = policy.bill_id is not None or policy.recurring_transaction_id is not None
        ended = policy.ends_on is not None and policy.ends_on < as_of
        views.append(
            PolicyView(
                policy_id=str(policy.id),
                name=policy.name,
                kind=policy.kind,
                insurer=policy.insurer,
                currency=policy.currency,
                coverage_minor=coverage,
                deductible_minor=policy.deductible_minor,
                premium_minor=policy.premium_minor,
                premium_frequency=policy.premium_frequency,
                annual_premium_minor=annual_premium_minor(policy.premium_minor, policy.premium_frequency),
                monthly_premium_minor=monthly_premium_minor(policy.premium_minor, policy.premium_frequency),
                renews_on=policy.renews_on,
                ends_on=policy.ends_on,
                covers_asset_id=str(asset.id) if asset else None,
                covers_asset_name=asset.name if asset else None,
                asset_value_minor=asset_value,
                coverage_gap_minor=gap,
                covers_account_id=str(policy.covers_account_id) if policy.covers_account_id else None,
                covers_account_name=policy.covers_account.name if policy.covers_account else None,
                bill_id=str(policy.bill_id) if policy.bill_id else None,
                recurring_transaction_id=(
                    str(policy.recurring_transaction_id) if policy.recurring_transaction_id else None
                ),
                premium_in_cashflow=linked or not policy.is_active or ended,
                is_active=policy.is_active and not ended,
                notes=policy.notes,
            )
        )
    views.sort(key=lambda v: (not v.underinsured, -v.annual_premium_minor))
    return views


@dataclass(frozen=True, slots=True)
class InsuranceSummary:
    currency: str
    count: int
    annual_premium_minor: int
    underinsured_count: int
    unlinked_count: int


def summary(*, as_of: date | None = None) -> InsuranceSummary | None:
    """Headline figures, or None when nothing has been recorded."""
    views = policy_views(as_of=as_of)
    if not views:
        return None
    counts: dict[str, int] = {}
    for v in views:
        counts[v.currency] = counts.get(v.currency, 0) + 1
    currency = max(counts.items(), key=lambda kv: kv[1])[0]
    scoped = [v for v in views if v.currency == currency]
    return InsuranceSummary(
        currency=currency,
        count=len(scoped),
        annual_premium_minor=sum(v.annual_premium_minor for v in scoped if v.is_active),
        underinsured_count=sum(1 for v in scoped if v.underinsured),
        unlinked_count=sum(1 for v in scoped if v.is_active and not v.premium_in_cashflow),
    )


def underinsured_gaps(*, as_of: date | None = None) -> tuple[dict, ...]:
    """Policies whose cover is below the linked asset's latest valuation.

    Shape matches what the coach consumes: id, names, figures, currency.
    Empty when nothing is underinsured — the coach then stays silent.
    """
    return tuple(
        {
            "policy_id": v.policy_id,
            "name": v.name,
            "asset_name": v.covers_asset_name,
            "coverage_minor": v.coverage_minor,
            "asset_value_minor": v.asset_value_minor,
            "gap_minor": abs(v.coverage_gap_minor or 0),
            "currency": v.currency,
        }
        for v in policy_views(as_of=as_of)
        if v.underinsured and v.is_active
    )


def unlinked_monthly_premiums(*, currency: str, as_of: date | None = None) -> list[dict]:
    """Active policies whose premium is not already a bill or a recurring
    template, as cash-flow stack lines. Linked premiums are omitted — that is
    the whole point of the link."""
    as_of = as_of or timezone.localdate()
    lines: list[dict] = []
    for view in policy_views(as_of=as_of):
        if view.currency != currency:
            continue
        if not view.is_active or view.premium_in_cashflow:
            continue
        monthly = view.monthly_premium_minor
        if monthly <= 0:
            continue
        lines.append(
            {
                "id": view.policy_id,
                "label": view.name,
                "monthly_minor": monthly,
            }
        )
    return lines
