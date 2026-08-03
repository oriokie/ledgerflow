"""Write operations on income.

Validation that the database cannot express lives here; validation it *can*
express stays in the constraints, deliberately duplicated only where the error
message is worth the duplication. A user who types a net above their gross
should read "net cannot exceed gross", not an IntegrityError.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction

from .models import (
    DEFAULT_RELIABILITY_BY_KIND,
    PAYMENTS_PER_YEAR,
    IncomeDeduction,
    IncomeFrequency,
    IncomeKind,
    IncomeReceipt,
    IncomeSource,
    Reliability,
)


class IncomeError(ValueError):
    """A write that would produce an income record the product cannot defend."""


#: Cadences that land on a numbered day of the month rather than an interval
#: counted from an anchor date.
DAY_OF_MONTH_CADENCES = frozenset(
    {
        IncomeFrequency.SEMI_MONTHLY,
        IncomeFrequency.MONTHLY,
        IncomeFrequency.QUARTERLY,
        IncomeFrequency.ANNUAL,
    }
)


def _validate(
    *,
    net_minor: int,
    gross_minor: int | None,
    frequency: str,
    pay_day: int | None,
    second_pay_day: int | None,
    starts_on: date,
    ends_on: date | None,
) -> None:
    if net_minor <= 0:
        raise IncomeError("Net amount must be greater than zero.")
    if gross_minor is not None:
        if gross_minor <= 0:
            raise IncomeError("Gross amount must be greater than zero.")
        if net_minor > gross_minor:
            raise IncomeError("Net cannot exceed gross — deductions only ever reduce pay.")
    if ends_on is not None and ends_on < starts_on:
        raise IncomeError("End date cannot be before the start date.")

    for label, day in (("Pay day", pay_day), ("Second pay day", second_pay_day)):
        if day is not None and not 1 <= day <= 28:
            # Capped at 28 rather than 31 so the schedule fires in February.
            # A "pay day" that silently skips a month is worse than one the
            # user had to nudge earlier by three days.
            raise IncomeError(f"{label} must be between 1 and 28.")

    if second_pay_day is not None and frequency != IncomeFrequency.SEMI_MONTHLY:
        raise IncomeError("A second pay day only applies to income paid twice a month.")
    if frequency == IncomeFrequency.SEMI_MONTHLY and (pay_day is None or second_pay_day is None):
        raise IncomeError("Income paid twice a month needs both pay days.")
    if pay_day is not None and frequency not in DAY_OF_MONTH_CADENCES:
        raise IncomeError("A pay day only applies to income paid on a day of the month.")


@transaction.atomic
def create_source(
    *,
    name: str,
    currency: str,
    net_minor: int,
    starts_on: date,
    kind: str = IncomeKind.EMPLOYMENT,
    payer: str = "",
    gross_minor: int | None = None,
    reliability: str | None = None,
    frequency: str = IncomeFrequency.MONTHLY,
    pay_day: int | None = None,
    second_pay_day: int | None = None,
    ends_on: date | None = None,
    deposit_account=None,
    recurring_transaction=None,
    notes: str = "",
) -> IncomeSource:
    """Record an arrangement that pays money in.

    An omitted ``reliability`` is filled from the kind rather than defaulting
    to ``FIXED``. Defaulting everything to fixed would let the projection draw
    a confident line through freelance income nobody promised, which is the
    error this model exists to stop.
    """
    _validate(
        net_minor=net_minor,
        gross_minor=gross_minor,
        frequency=frequency,
        pay_day=pay_day,
        second_pay_day=second_pay_day,
        starts_on=starts_on,
        ends_on=ends_on,
    )
    return IncomeSource.objects.create(
        name=name,
        kind=kind,
        payer=payer,
        currency=currency.upper(),
        net_minor=net_minor,
        gross_minor=gross_minor,
        reliability=reliability or DEFAULT_RELIABILITY_BY_KIND.get(kind, Reliability.VARIABLE),
        frequency=frequency,
        pay_day=pay_day,
        second_pay_day=second_pay_day,
        starts_on=starts_on,
        ends_on=ends_on,
        deposit_account=deposit_account,
        recurring_transaction=recurring_transaction,
        notes=notes,
    )


@transaction.atomic
def update_source(*, source: IncomeSource, **fields) -> IncomeSource:
    """Edit the plan.

    ``currency`` is not editable, matching the same refusal on savings goals:
    every receipt already recorded is denominated in the original currency, and
    switching it would silently reinterpret history rather than correct it.
    """
    fields.pop("currency", None)
    for key, value in fields.items():
        setattr(source, key, value)

    _validate(
        net_minor=source.net_minor,
        gross_minor=source.gross_minor,
        frequency=source.frequency,
        pay_day=source.pay_day,
        second_pay_day=source.second_pay_day,
        starts_on=source.starts_on,
        ends_on=source.ends_on,
    )
    source.save()
    return source


@transaction.atomic
def add_deduction(
    *,
    source: IncomeSource,
    kind: str,
    label: str = "",
    amount_minor: int | None = None,
    percent_bp: int | None = None,
) -> IncomeDeduction:
    """Add one line of the gross→net gap.

    Exactly one basis, and a percentage needs a gross to be a share *of*. A
    percentage deduction on a source with no gross would resolve to nothing and
    quietly report the user's take-home rate as 100%.
    """
    if (amount_minor is None) == (percent_bp is None):
        raise IncomeError("A deduction is either a fixed amount or a percentage, not both.")
    if amount_minor is not None and amount_minor <= 0:
        raise IncomeError("Deduction amount must be greater than zero.")
    if percent_bp is not None:
        if not 0 < percent_bp <= 10000:
            raise IncomeError("Deduction percentage must be above 0 and at most 100%.")
        if source.gross_minor is None:
            raise IncomeError(
                "Add the gross amount before a percentage deduction — a percentage needs "
                "something to be a percentage of."
            )
    return IncomeDeduction.objects.create(
        source=source,
        kind=kind,
        label=label,
        amount_minor=amount_minor,
        percent_bp=percent_bp,
    )


@transaction.atomic
def record_receipt(
    *,
    source: IncomeSource,
    occurred_on: date,
    net_minor: int,
    gross_minor: int | None = None,
    transaction_ref=None,
    memo: str = "",
) -> IncomeReceipt:
    """Record money that actually arrived.

    Deliberately does not post to the ledger. A receipt is a *record about* an
    arrival, and the arrival itself is a transaction the user records normally
    — the same separation the goals module keeps between a contribution and the
    transfer that funded it. Posting here would double-count every paycheque
    against the account it landed in.
    """
    if net_minor <= 0:
        raise IncomeError("Received amount must be greater than zero.")
    if gross_minor is not None:
        if gross_minor <= 0:
            raise IncomeError("Gross amount must be greater than zero.")
        if net_minor > gross_minor:
            raise IncomeError("Net cannot exceed gross.")
    return IncomeReceipt.objects.create(
        source=source,
        occurred_on=occurred_on,
        net_minor=net_minor,
        gross_minor=gross_minor,
        transaction=transaction_ref,
        memo=memo,
    )


def annualised_minor(source: IncomeSource) -> int | None:
    """What this source is worth over a year, or ``None`` for ad-hoc cadence."""
    per_year = PAYMENTS_PER_YEAR.get(source.frequency)
    return None if per_year is None else source.net_minor * per_year
