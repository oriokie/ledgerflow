"""Bill tracking — money owed with a due date, marked paid explicitly.

A bill never posts to the ledger by itself. `mark_bill_paid` optionally records
the settling expense through the normal finance service (so the money movement
is a real, audited transaction), links it, and — if the bill recurs — spawns the
next occurrence. This keeps the invariant that money only ever moves through
`record_expense`/`post_journal_entry`, never as a side effect of a status flip.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from .models import Bill, BillStatus
from .schedule import add_period  # reuse the recurring-schedule date math


class BillError(Exception): ...


@transaction.atomic
def create_bill(
    *,
    name: str,
    amount_minor: int,
    currency: str,
    due_on: date,
    payee=None,
    category=None,
    recurrence_frequency: str = "",
    recurrence_interval: int = 1,
    autopay_account=None,
    notes: str = "",
) -> Bill:
    if amount_minor <= 0:
        raise BillError("Bill amount must be positive.")
    return Bill.objects.create(
        name=name,
        amount_minor=amount_minor,
        currency=currency.upper(),
        due_on=due_on,
        payee=payee,
        category=category,
        recurrence_frequency=recurrence_frequency,
        recurrence_interval=recurrence_interval or 1,
        autopay_account=autopay_account,
        notes=notes,
    )


@transaction.atomic
def mark_bill_paid(
    *,
    bill: Bill,
    from_account=None,
    amount_minor: int | None = None,
    occurred_at=None,
    record_expense: bool = True,
) -> tuple[Bill, object | None]:
    """Mark a bill paid. If `record_expense` and an account + category are
    available, post the settling expense and link it. Spawns the next
    occurrence for a recurring bill. Returns (bill, settling_transaction|None).
    """
    if bill.status == BillStatus.PAID:
        return bill, None

    from . import services as finance_services

    settling_txn = None
    account = from_account or bill.autopay_account
    pay_amount = amount_minor or bill.amount_minor
    if record_expense and account is not None and bill.category is not None:
        settling_txn = finance_services.record_expense(
            financial_account=account,
            category=bill.category,
            amount_minor=pay_amount,
            occurred_at=occurred_at or timezone.now(),
            memo=f"Bill payment: {bill.name}",
            payee=bill.payee,
        )

    bill.status = BillStatus.PAID
    bill.paid_at = timezone.now()
    bill.paid_transaction = settling_txn
    bill.save(update_fields=["status", "paid_at", "paid_transaction", "updated_at"])

    if bill.recurrence_frequency:
        _spawn_next(bill)

    return bill, settling_txn


def _spawn_next(paid_bill: Bill) -> Bill:
    """Create the next occurrence of a recurring bill from the one just paid."""
    next_due = add_period(paid_bill.due_on, paid_bill.recurrence_frequency, paid_bill.recurrence_interval)
    return Bill.objects.create(
        name=paid_bill.name,
        amount_minor=paid_bill.amount_minor,
        currency=paid_bill.currency,
        due_on=next_due,
        payee=paid_bill.payee,
        category=paid_bill.category,
        recurrence_frequency=paid_bill.recurrence_frequency,
        recurrence_interval=paid_bill.recurrence_interval,
        autopay_account=paid_bill.autopay_account,
        notes=paid_bill.notes,
    )


@transaction.atomic
def cancel_bill(*, bill: Bill) -> Bill:
    bill.status = BillStatus.CANCELLED
    bill.save(update_fields=["status", "updated_at"])
    return bill


def mark_overdue(*, as_of: date | None = None) -> int:
    """Flip upcoming bills whose due date has passed to OVERDUE. Returns the
    count updated. Intended to run from a daily beat task."""
    as_of = as_of or timezone.localdate()
    return Bill.objects.filter(status=BillStatus.UPCOMING, due_on__lt=as_of).update(status=BillStatus.OVERDUE)


# --------------------------------------------------------------------- reads
@dataclass(frozen=True, slots=True)
class UpcomingBill:
    bill: Bill
    days_until_due: int


def upcoming_bills(*, within_days: int = 30, as_of: date | None = None) -> list[UpcomingBill]:
    """Bills due within `within_days`, soonest first — the "due soon" view and
    the recommender's `upcoming_bills` input (previously always empty)."""
    as_of = as_of or timezone.localdate()
    horizon = as_of + timedelta(days=within_days)
    rows = Bill.objects.filter(
        status__in=[BillStatus.UPCOMING, BillStatus.OVERDUE], due_on__lte=horizon
    ).order_by("due_on")
    return [UpcomingBill(bill=b, days_until_due=(b.due_on - as_of).days) for b in rows]


def list_bills(*, status: str | None = None):
    qs = Bill.objects.all()
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("due_on")
