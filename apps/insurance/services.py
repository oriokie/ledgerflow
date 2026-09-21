"""Write operations on insurance policies.

Nothing here posts to the ledger. A policy is a contract overlay: the premium
that actually leaves an account is a bill or a recurring template, linked
here so the cash-flow stack can refuse to count it twice.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction

from apps.finance.models import AccountType

from .models import InsurancePolicy, PolicyKind, PremiumFrequency

_LIABILITY_TYPES = {AccountType.CREDIT_CARD, AccountType.LOAN}


class InsuranceError(ValueError):
    """A write that would produce a policy the product cannot defend."""


def _validate(*, name: str, premium_minor: int, coverage_minor: int | None, deductible_minor: int | None) -> None:
    if not name.strip():
        raise InsuranceError("A policy needs a name.")
    if premium_minor <= 0:
        raise InsuranceError("A premium must be greater than zero.")
    if coverage_minor is not None and coverage_minor < 0:
        raise InsuranceError("Cover cannot be negative.")
    if deductible_minor is not None and deductible_minor < 0:
        raise InsuranceError("A deductible cannot be negative.")


@transaction.atomic
def create_policy(
    *,
    name: str,
    currency: str,
    premium_minor: int,
    kind: str = PolicyKind.OTHER,
    insurer: str = "",
    coverage_minor: int | None = None,
    deductible_minor: int | None = None,
    premium_frequency: str = PremiumFrequency.ANNUAL,
    renews_on: date | None = None,
    ends_on: date | None = None,
    covers_asset=None,
    covers_account=None,
    bill=None,
    recurring_transaction=None,
    is_active: bool = True,
    notes: str = "",
) -> InsurancePolicy:
    _validate(name=name, premium_minor=premium_minor, coverage_minor=coverage_minor, deductible_minor=deductible_minor)
    if kind not in PolicyKind.values:
        raise InsuranceError(f"Unknown policy kind {kind!r}.")
    if premium_frequency not in PremiumFrequency.values:
        raise InsuranceError(f"Unknown premium frequency {premium_frequency!r}.")
    if covers_account is not None and covers_account.account_type not in _LIABILITY_TYPES:
        raise InsuranceError("A policy can only be written against a loan or a credit account.")
    if ends_on is not None and renews_on is not None and ends_on < renews_on:
        raise InsuranceError("A policy cannot end before it renews.")

    return InsurancePolicy.objects.create(
        name=name.strip(),
        kind=kind,
        insurer=insurer.strip(),
        currency=currency.upper(),
        coverage_minor=coverage_minor,
        deductible_minor=deductible_minor,
        premium_minor=premium_minor,
        premium_frequency=premium_frequency,
        renews_on=renews_on,
        ends_on=ends_on,
        covers_asset=covers_asset,
        covers_account=covers_account,
        bill=bill,
        recurring_transaction=recurring_transaction,
        is_active=is_active,
        notes=notes,
    )


@transaction.atomic
def update_policy(*, policy: InsurancePolicy, **changes) -> InsurancePolicy:
    """Edit a policy. ``currency`` is absent: every figure already recorded is
    denominated in it, so changing it would reinterpret history."""
    allowed = {
        "name",
        "kind",
        "insurer",
        "coverage_minor",
        "deductible_minor",
        "premium_minor",
        "premium_frequency",
        "renews_on",
        "ends_on",
        "covers_asset",
        "covers_account",
        "bill",
        "recurring_transaction",
        "is_active",
        "notes",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise InsuranceError(f"Cannot change {', '.join(sorted(unknown))} on an existing policy.")

    for field, value in changes.items():
        setattr(policy, field, value)

    _validate(
        name=policy.name,
        premium_minor=policy.premium_minor,
        coverage_minor=policy.coverage_minor,
        deductible_minor=policy.deductible_minor,
    )
    if policy.kind not in PolicyKind.values:
        raise InsuranceError(f"Unknown policy kind {policy.kind!r}.")
    if policy.premium_frequency not in PremiumFrequency.values:
        raise InsuranceError(f"Unknown premium frequency {policy.premium_frequency!r}.")
    if policy.covers_account is not None and policy.covers_account.account_type not in _LIABILITY_TYPES:
        raise InsuranceError("A policy can only be written against a loan or a credit account.")
    if policy.ends_on is not None and policy.renews_on is not None and policy.ends_on < policy.renews_on:
        raise InsuranceError("A policy cannot end before it renews.")

    policy.save()
    return policy


@transaction.atomic
def delete_policy(*, policy: InsurancePolicy) -> None:
    """Soft-delete. The linked bill or recurring template is left untouched —
    they are the money movement, and this is only the contract."""
    policy.delete()
