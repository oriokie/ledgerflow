"""Write operations on receivables.

When a source account is chosen, lending and repayments can post to the
ledger so Transactions reflects money moving out and back. The receivable
itself remains a separate claim record — it does not double-count net worth
because the outflow is real cash leaving the account.
"""

from __future__ import annotations

from datetime import date, datetime, time

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Receivable, ReceivableKind, ReceivableStatus, Repayment


class ReceivableError(ValueError):
    """A write that would produce a claim the product cannot defend."""


def _lazy_category(*, name: str, kind: str, currency: str):
    from apps.finance.quick_add import _lazy_category as lazy

    return lazy(name=name, kind=kind, currency=currency)


def _occurred_at(on: date) -> datetime:
    return timezone.make_aware(datetime.combine(on, time.min))


def outstanding_minor(receivable: Receivable) -> int:
    """What is still owed: principal less everything repaid, floored at zero.

    Floored because an overpayment is a real thing that happens (someone rounds
    up, or pays twice by mistake) and a negative "still owed" reads as the
    household owing money back, which it does not — that would be a different
    record entirely.
    """
    repaid = (
        Repayment.objects.filter(receivable=receivable).aggregate(total=Sum("amount_minor"))["total"] or 0
    )
    return max(0, receivable.principal_minor - repaid)


@transaction.atomic
def create_receivable(
    *,
    counterparty: str,
    currency: str,
    principal_minor: int,
    lent_on: date,
    kind: str = ReceivableKind.PERSONAL,
    description: str = "",
    due_on: date | None = None,
    source_account=None,
    notes: str = "",
    post_to_ledger: bool = True,
) -> Receivable:
    """Record that someone owes you money, optionally posting the outflow."""
    if principal_minor <= 0:
        raise ReceivableError("The amount owed must be greater than zero.")
    if due_on is not None and due_on < lent_on:
        raise ReceivableError("A repayment date cannot be before the money was lent.")
    if not counterparty.strip():
        raise ReceivableError("Say who owes it — a claim against nobody cannot be chased.")
    if post_to_ledger and source_account is None:
        raise ReceivableError("Choose which account the money left so it can appear on Transactions.")

    receivable = Receivable.objects.create(
        counterparty=counterparty.strip(),
        kind=kind,
        description=description,
        currency=currency.upper(),
        principal_minor=principal_minor,
        lent_on=lent_on,
        due_on=due_on,
        source_account=source_account,
        notes=notes,
    )

    if post_to_ledger and source_account is not None:
        from apps.finance import services as finance_services
        from apps.finance.models import CategoryKind, TransactionSource
        from apps.finance.payees import get_or_create_payee

        if source_account.currency != receivable.currency:
            raise ReceivableError(
                f"Account is in {source_account.currency}, but this receivable is in {receivable.currency}."
            )
        payee, _ = get_or_create_payee(name=receivable.counterparty)
        category = _lazy_category(
            name="Loans to others",
            kind=CategoryKind.EXPENSE,
            currency=receivable.currency,
        )
        finance_services.record_expense(
            financial_account=source_account,
            category=category,
            amount_minor=principal_minor,
            occurred_at=_occurred_at(lent_on),
            memo=f"Lent to {receivable.counterparty}" + (f": {description}" if description else ""),
            payee=payee,
            source=TransactionSource.MANUAL,
            idempotency_key=f"receivable-lend:{receivable.id}",
        )

    return receivable


@transaction.atomic
def update_receivable(*, receivable: Receivable, **changes) -> Receivable:
    """Edit a claim.

    ``currency`` is absent by design, the same refusal income sources and
    savings goals make: every repayment already recorded is denominated in the
    original currency, so changing it would reinterpret history rather than
    correct it.
    """
    allowed = {
        "counterparty",
        "kind",
        "description",
        "principal_minor",
        "lent_on",
        "due_on",
        "source_account",
        "notes",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise ReceivableError(f"Cannot change {', '.join(sorted(unknown))} on an existing receivable.")

    for field, value in changes.items():
        setattr(receivable, field, value)

    if receivable.principal_minor <= 0:
        raise ReceivableError("The amount owed must be greater than zero.")
    if receivable.due_on is not None and receivable.due_on < receivable.lent_on:
        raise ReceivableError("A repayment date cannot be before the money was lent.")
    if not receivable.counterparty.strip():
        raise ReceivableError("Say who owes it — a claim against nobody cannot be chased.")

    receivable.save()
    _resettle(receivable)
    return receivable


@transaction.atomic
def delete_receivable(*, receivable: Receivable) -> None:
    """Remove a claim entirely. Soft-deleted, so a mis-keyed entry can be
    reversed without punching a hole in the history."""
    receivable.delete()


@transaction.atomic
def record_repayment(
    *,
    receivable: Receivable,
    amount_minor: int,
    received_on: date,
    transaction_ref=None,
    deposit_account=None,
    post_to_ledger: bool = True,
    memo: str = "",
) -> Repayment:
    """Record money received against a claim, optionally posting the inflow."""
    if amount_minor <= 0:
        raise ReceivableError("A repayment must be greater than zero.")
    if received_on < receivable.lent_on:
        raise ReceivableError("Money cannot come back before it went out.")

    posted = transaction_ref
    account = deposit_account or receivable.source_account
    if posted is None and post_to_ledger:
        if account is None:
            raise ReceivableError(
                "Choose which account this repayment landed in so it can appear on Transactions."
            )
        if account.currency != receivable.currency:
            raise ReceivableError(
                f"Account is in {account.currency}, but this receivable is in {receivable.currency}."
            )
        from apps.finance import services as finance_services
        from apps.finance.models import CategoryKind, TransactionSource
        from apps.finance.payees import get_or_create_payee

        payee, _ = get_or_create_payee(name=receivable.counterparty)
        category = _lazy_category(
            name="Loan repayment",
            kind=CategoryKind.INCOME,
            currency=receivable.currency,
        )
        posted = finance_services.record_income(
            financial_account=account,
            category=category,
            amount_minor=amount_minor,
            occurred_at=_occurred_at(received_on),
            memo=memo or f"Repayment from {receivable.counterparty}",
            payee=payee,
            source=TransactionSource.MANUAL,
            idempotency_key=f"receivable-repay:{receivable.id}:{received_on.isoformat()}:{amount_minor}",
        )

    repayment = Repayment.objects.create(
        receivable=receivable,
        amount_minor=amount_minor,
        received_on=received_on,
        transaction=posted,
        memo=memo,
    )
    _resettle(receivable)
    return repayment


@transaction.atomic
def write_off(*, receivable: Receivable) -> Receivable:
    """Give up on the outstanding balance.

    Kept rather than deleted: that a loan was never repaid is a fact worth
    remembering, both for the user and for anyone deciding whether to lend to
    that person again.
    """
    if outstanding_minor(receivable) <= 0:
        raise ReceivableError("Nothing is outstanding on this — there is nothing to write off.")
    receivable.status = ReceivableStatus.WRITTEN_OFF
    receivable.save(update_fields=["status", "updated_at"])
    return receivable


def _resettle(receivable: Receivable) -> None:
    """Keep `status` agreeing with the sums beneath it.

    Status is derived here rather than set by callers, because a status that
    can disagree with its own repayments is a status nobody can trust. A
    written-off claim that later gets paid comes back to life.
    """
    settled = outstanding_minor(receivable) <= 0
    target = ReceivableStatus.SETTLED if settled else ReceivableStatus.OUTSTANDING
    if receivable.status == ReceivableStatus.WRITTEN_OFF and not settled:
        # Only a repayment can revive a write-off, and `record_repayment` is
        # the only caller that reaches here with money having arrived.
        target = ReceivableStatus.OUTSTANDING
    if receivable.status != target:
        receivable.status = target
        receivable.save(update_fields=["status", "updated_at"])
