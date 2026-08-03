"""Debt term management.

Terms are contract metadata, not financial events, so nothing here posts to the
ledger. Recording a 24% APR doesn't move money; it records what the lender
charges. Payments are ordinary transactions and go through the finance app like
any other.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.finance.models import AccountType, FinancialAccount

from .models import DebtKind, DebtProfile


class DebtError(Exception): ...


#: Sensible default classification from the account type, so a user who never
#: opens the debt kind picker still gets a usable label.
_DEFAULT_KIND = {
    AccountType.CREDIT_CARD: DebtKind.CREDIT_CARD,
    AccountType.LOAN: DebtKind.PERSONAL_LOAN,
}


@transaction.atomic
def set_debt_terms(
    *,
    financial_account: FinancialAccount,
    apr: Decimal | float | str | None = None,
    minimum_payment_minor: int | None = None,
    debt_kind: str | None = None,
    payment_day: int | None = None,
    original_principal_minor: int | None = None,
    opened_on: date | None = None,
    promotional_apr: Decimal | float | str | None = None,
    promotional_apr_until: date | None = None,
    custom_priority: int | None = None,
    include_in_payoff: bool | None = None,
    compounding: str | None = None,
    monthly_fee_minor: int | None = None,
    annual_fee_minor: int | None = None,
    annual_fee_month: int | None = None,
    origination_fee_minor: int | None = None,
    notes: str | None = None,
) -> DebtProfile:
    """Create or update the repayment terms for a liability account.

    Only liability accounts can carry terms: an APR on a savings account is
    meaningless here, and allowing it would put nonsense into payoff plans.
    """
    if financial_account.account_type not in (AccountType.CREDIT_CARD, AccountType.LOAN):
        raise DebtError("Only credit card and loan accounts can have debt terms.")

    # `all_objects` includes soft-deleted rows. Without this, re-adding terms
    # after clearing them would collide with the one-to-one constraint on a row
    # the user can no longer see — so clearing terms would be irreversible.
    profile = DebtProfile.all_objects.filter(financial_account=financial_account).first()
    if profile is None:
        profile = DebtProfile(
            financial_account=financial_account,
            debt_kind=_DEFAULT_KIND.get(financial_account.account_type, DebtKind.OTHER),
        )
    elif profile.deleted_at is not None:
        # Revived, and reset to defaults — stale terms from before the clear
        # would be worse than starting fresh.
        profile.deleted_at = None
        profile.deleted_by_id = None
        profile.apr = Decimal("0")
        profile.minimum_payment_minor = 0

    if apr is not None:
        value = Decimal(str(apr))
        if value < 0:
            raise DebtError("APR cannot be negative.")
        # A rate above 100% is almost always a data-entry slip (a decimal typed
        # as a percentage, or the reverse). Catching it here beats producing a
        # payoff plan nobody can act on.
        if value > 100:
            raise DebtError("APR looks wrong — enter it as a percentage, e.g. 19.9 for 19.9%.")
        profile.apr = value

    if minimum_payment_minor is not None:
        if minimum_payment_minor < 0:
            raise DebtError("Minimum payment cannot be negative.")
        profile.minimum_payment_minor = minimum_payment_minor

    if debt_kind is not None:
        if debt_kind not in DebtKind.values:
            raise DebtError(f"Unknown debt kind {debt_kind!r}.")
        profile.debt_kind = debt_kind

    if payment_day is not None:
        if not (1 <= payment_day <= 28):
            # Capped at 28 so the day exists in February — same reasoning as
            # goal auto-contributions.
            raise DebtError("Payment day must be between 1 and 28.")
        profile.payment_day = payment_day

    if original_principal_minor is not None:
        if original_principal_minor < 0:
            raise DebtError("Original principal cannot be negative.")
        profile.original_principal_minor = original_principal_minor

    if promotional_apr is not None:
        promo = Decimal(str(promotional_apr))
        if promo < 0:
            raise DebtError("Promotional APR cannot be negative.")
        profile.promotional_apr = promo

    if promotional_apr_until is not None:
        profile.promotional_apr_until = promotional_apr_until

    # A promotional rate with no end date would apply forever, which is never
    # what a promotion is.
    if profile.promotional_apr is not None and profile.promotional_apr_until is None:
        raise DebtError("A promotional rate needs an end date.")

    if compounding is not None:
        from .models import Compounding

        if compounding not in Compounding.values:
            raise DebtError(f"Unknown compounding frequency {compounding!r}.")
        profile.compounding = compounding

    # Fees are a cost of borrowing, never a repayment, so a negative one is
    # meaningless rather than merely unusual.
    for field_name, value in (
        ("monthly_fee_minor", monthly_fee_minor),
        ("annual_fee_minor", annual_fee_minor),
        ("origination_fee_minor", origination_fee_minor),
    ):
        if value is not None:
            if value < 0:
                raise DebtError("Fees cannot be negative.")
            setattr(profile, field_name, value)

    if annual_fee_month is not None:
        if not (1 <= annual_fee_month <= 12):
            raise DebtError("Annual fee month must be between 1 and 12.")
        profile.annual_fee_month = annual_fee_month

    if opened_on is not None:
        profile.opened_on = opened_on
    if custom_priority is not None:
        profile.custom_priority = custom_priority
    if include_in_payoff is not None:
        profile.include_in_payoff = include_in_payoff
    if notes is not None:
        profile.notes = notes

    profile.save()
    return profile


@transaction.atomic
def clear_debt_terms(*, financial_account: FinancialAccount) -> None:
    """Remove the terms. The account and its history are untouched — you stop
    planning, you don't stop owing."""
    DebtProfile.objects.filter(financial_account=financial_account).delete()


@transaction.atomic
def record_rate_change(
    *,
    financial_account: FinancialAccount,
    apr: Decimal | float | str,
    effective_from: date,
    source: str = "manual",
    notes: str = "",
):
    """Add a rate to a debt's timeline.

    Append-only by intent: recording a change never edits an earlier entry, so
    a projection run last March still uses the rate that was in force then.
    Re-recording the *same* date updates that entry rather than creating a
    second rate for one morning, which would have no meaning.

    Future dates are allowed and are the point — a lender notifying a rise in
    three months lets the plan account for it now.
    """
    from .models import DebtRateHistory

    profile = DebtProfile.objects.filter(financial_account=financial_account).first()
    if profile is None:
        raise DebtError("Set the debt's terms before recording rate changes.")

    value = Decimal(str(apr))
    if value < 0:
        raise DebtError("APR cannot be negative.")
    if value > 100:
        raise DebtError("APR looks wrong — enter it as a percentage, e.g. 19.9 for 19.9%.")

    entry, _ = DebtRateHistory.objects.update_or_create(
        profile=profile,
        effective_from=effective_from,
        defaults={"apr": value, "source": source, "notes": notes},
    )
    return entry


@transaction.atomic
def set_offset_accounts(*, financial_account: FinancialAccount, account_ids: list) -> DebtProfile:
    """Link accounts whose balances reduce the interest charged.

    Offsetting changes no balance on either side — it is an arrangement with
    the lender about how interest is computed, not a transfer. Nothing is
    posted to the ledger here.

    Only asset accounts qualify: offsetting a debt against another debt is not
    a thing, and allowing it would reduce interest on the strength of money
    that doesn't exist.
    """
    from apps.finance.models import AccountType

    profile = DebtProfile.objects.filter(financial_account=financial_account).first()
    if profile is None:
        raise DebtError("Set the debt's terms before linking offset accounts.")

    accounts = list(FinancialAccount.objects.filter(id__in=account_ids))
    for account in accounts:
        if account.account_type in (AccountType.CREDIT_CARD, AccountType.LOAN):
            raise DebtError("Only asset accounts can offset a debt.")
        if account.currency != financial_account.currency:
            raise DebtError("Offset accounts must be in the same currency as the debt.")

    profile.offset_accounts.set(accounts)
    return profile
