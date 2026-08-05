"""Write operations on receivables.

Nothing here posts to the ledger. Lending someone money already appears there
as cash leaving an account; recording the claim as well would double-count it.
This module remembers *where that money went and whether it came back* — see
the note in `models.py`.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.db.models import Sum

from .models import Receivable, ReceivableKind, ReceivableStatus, Repayment


class ReceivableError(ValueError):
    """A write that would produce a claim the product cannot defend."""


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
) -> Receivable:
    """Record that someone owes you money."""
    if principal_minor <= 0:
        raise ReceivableError("The amount owed must be greater than zero.")
    if due_on is not None and due_on < lent_on:
        raise ReceivableError("A repayment date cannot be before the money was lent.")
    if not counterparty.strip():
        raise ReceivableError("Say who owes it — a claim against nobody cannot be chased.")

    return Receivable.objects.create(
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
    memo: str = "",
) -> Repayment:
    """Record money received against a claim.

    A repayment against a written-off receivable is allowed on purpose: debts
    people had given up on do sometimes get paid, and refusing the entry would
    leave the user unable to record money genuinely in their hand. It simply
    revives the claim.
    """
    if amount_minor <= 0:
        raise ReceivableError("A repayment must be greater than zero.")
    if received_on < receivable.lent_on:
        raise ReceivableError("Money cannot come back before it went out.")

    repayment = Repayment.objects.create(
        receivable=receivable,
        amount_minor=amount_minor,
        received_on=received_on,
        transaction=transaction_ref,
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
