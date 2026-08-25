"""Recurring-transaction engine: create schedules, and materialize the ones
that are due into real Transactions.

Materialization is idempotent per (template, scheduled_date): the derived
journal-entry idempotency key means re-running the beat task — or catching up
several missed days at once — never double-posts. A template can generate
several occurrences in one run if it fell behind (e.g. the worker was down),
walking forward one period at a time until it reaches today.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone

from . import services
from .models import Frequency, RecurringTransaction, RecurringType, TransactionSource
from .schedule import nth_occurrence


class RecurringError(services.FinanceError): ...


@transaction.atomic
def set_recurring_active(*, rec: RecurringTransaction, active: bool) -> RecurringTransaction:
    """Pause (active=False) or resume (active=True) a schedule. Pausing stops
    future materialization without touching transactions already posted from it —
    the template is a plan, not ledger history."""
    if rec.is_active != active:
        rec.is_active = active
        rec.save(update_fields=["is_active", "updated_at"])
    return rec


@transaction.atomic
def cancel_recurring(*, rec: RecurringTransaction) -> None:
    """Cancel a schedule entirely (soft delete). Posted transactions remain;
    only the template goes away, so it stops charging and leaves the list."""
    rec.is_active = False
    rec.save(update_fields=["is_active", "updated_at"])
    rec.delete()


#: Fields a caller may change on an existing template. `txn_type`, `currency`
#: and `financial_account` are deliberately absent: every occurrence already
#: posted is denominated in that currency, signed by that type and booked
#: against that account, so changing one reinterprets history instead of
#: correcting the plan. Those are a cancel-and-recreate, which leaves the
#: posted transactions visibly attached to the old template.
EDITABLE_FIELDS = frozenset(
    {
        "amount_minor",
        "category",
        "counter_account",
        "payee",
        "memo",
        "frequency",
        "interval",
        "starts_on",
        "ends_on",
        "next_run_on",
        "max_occurrences",
    }
)


@transaction.atomic
def update_recurring_transaction(*, rec: RecurringTransaction, **changes) -> RecurringTransaction:
    """Edit a schedule going forward, leaving what it already posted alone.

    The template is a plan, not ledger history — the same separation
    ``IncomeSource`` keeps from ``IncomeReceipt``. Correcting the rent you pay
    must change what gets posted next month, never rewrite the twelve months
    already in the books.

    Changing the cadence or the anchor recomputes ``next_run_on`` from the
    anchor via ``nth_occurrence`` rather than nudging the stored date. Nudging
    would drift: a schedule moved from monthly to quarterly after nine
    occurrences must land a quarter after the *ninth* occurrence's anchor, not
    a quarter after whatever date happened to be sitting in the column.

    An explicit ``next_run_on`` is the next due date, not a new anchor. The
    edit form used to send that date as ``starts_on``, which made projections
    treat an already-running charge as not yet started.
    """
    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        raise RecurringError(f"Cannot change {', '.join(sorted(unknown))} on an existing schedule.")

    explicit_next = "next_run_on" in changes
    for field, value in changes.items():
        setattr(rec, field, value)

    if rec.amount_minor <= 0:
        raise RecurringError("Recurring amount must be positive.")
    if rec.interval < 1:
        raise RecurringError("Interval must be at least 1.")
    if rec.frequency not in Frequency.values:
        raise RecurringError(f"Unknown frequency {rec.frequency!r}.")
    if rec.txn_type == RecurringType.TRANSFER and rec.counter_account_id is None:
        raise RecurringError("A recurring transfer needs a counter_account.")
    if rec.txn_type == RecurringType.TRANSFER and rec.financial_account_id == rec.counter_account_id:
        raise RecurringError("Cannot transfer to the same account.")
    if (
        rec.txn_type == RecurringType.TRANSFER
        and rec.financial_account.currency != rec.counter_account.currency
    ):
        raise RecurringError("Transfer accounts must use the same currency.")
    if rec.txn_type in (RecurringType.INCOME, RecurringType.EXPENSE) and rec.category_id is None:
        raise RecurringError(f"A recurring {rec.txn_type} needs a category.")
    if rec.ends_on is not None and rec.ends_on < rec.starts_on:
        raise RecurringError("End date cannot be before the start date.")

    # Re-anchor the next run whenever the cadence or the anchor moved. Counting
    # from `occurrences_created` keeps every occurrence already posted valid and
    # places the next one where the new schedule says it belongs.
    if {"frequency", "interval", "starts_on"} & set(changes) and not explicit_next:
        rec.next_run_on = nth_occurrence(
            starts_on=rec.starts_on,
            frequency=rec.frequency,
            interval=rec.interval,
            n=rec.occurrences_created,
        )

    # A schedule edited past its own end date is finished, not merely overdue.
    if rec.ends_on is not None and rec.next_run_on > rec.ends_on:
        rec.is_active = False
    if rec.max_occurrences is not None and rec.occurrences_created >= rec.max_occurrences:
        rec.is_active = False

    rec.save()
    return rec


@transaction.atomic
def create_recurring_transaction(
    *,
    txn_type: str,
    financial_account,
    amount_minor: int,
    currency: str,
    frequency: str,
    starts_on: date,
    interval: int = 1,
    category=None,
    counter_account=None,
    payee=None,
    memo: str = "",
    ends_on: date | None = None,
    max_occurrences: int | None = None,
) -> RecurringTransaction:
    if amount_minor <= 0:
        raise RecurringError("Recurring amount must be positive.")
    if interval < 1:
        raise RecurringError("Interval must be at least 1.")
    if frequency not in Frequency.values:
        raise RecurringError(f"Unknown frequency {frequency!r}.")
    if txn_type == RecurringType.TRANSFER and counter_account is None:
        raise RecurringError("A recurring transfer needs a counter_account.")
    if txn_type == RecurringType.TRANSFER and financial_account.id == counter_account.id:
        raise RecurringError("Cannot transfer to the same account.")
    if txn_type == RecurringType.TRANSFER and financial_account.currency != counter_account.currency:
        raise RecurringError("Transfer accounts must use the same currency.")
    if txn_type in (RecurringType.INCOME, RecurringType.EXPENSE) and category is None:
        raise RecurringError(f"A recurring {txn_type} needs a category.")

    return RecurringTransaction.objects.create(
        txn_type=txn_type,
        financial_account=financial_account,
        counter_account=counter_account,
        category=category,
        payee=payee,
        amount_minor=amount_minor,
        currency=currency,
        memo=memo,
        frequency=frequency,
        interval=interval,
        starts_on=starts_on,
        ends_on=ends_on,
        max_occurrences=max_occurrences,
        next_run_on=starts_on,  # first run is the anchor date itself
    )


def _post_one(rec: RecurringTransaction, scheduled_on: date):
    """Post the single occurrence for `scheduled_on`. The idempotency key is
    deterministic, so this is safe to call again for the same date."""
    occurred_at = timezone.make_aware(
        timezone.datetime(scheduled_on.year, scheduled_on.month, scheduled_on.day)
    )
    idem = f"recurring:{rec.id}:{scheduled_on.isoformat()}"

    if rec.txn_type == RecurringType.EXPENSE:
        return services.record_expense(
            financial_account=rec.financial_account,
            category=rec.category,
            amount_minor=rec.amount_minor,
            occurred_at=occurred_at,
            memo=rec.memo,
            payee=rec.payee,
            source=TransactionSource.RECURRING,
            idempotency_key=idem,
        )
    if rec.txn_type == RecurringType.INCOME:
        return services.record_income(
            financial_account=rec.financial_account,
            category=rec.category,
            amount_minor=rec.amount_minor,
            occurred_at=occurred_at,
            memo=rec.memo,
            payee=rec.payee,
            source=TransactionSource.RECURRING,
            idempotency_key=idem,
        )
    return services.record_transfer(
        from_account=rec.financial_account,
        to_account=rec.counter_account,
        amount_minor=rec.amount_minor,
        occurred_at=occurred_at,
        memo=rec.memo,
        source=TransactionSource.RECURRING,
        idempotency_key=idem,
    )


@transaction.atomic
def run_due_template(rec: RecurringTransaction, *, today: date | None = None) -> int:
    """Materialize every occurrence of one template that is due on/before
    `today`, advancing its schedule. Returns how many were posted. Locks the
    row so two concurrent beat runs can't both post the same occurrence."""
    today = today or timezone.localdate()
    rec = RecurringTransaction.objects.select_for_update().get(pk=rec.pk)
    posted = 0

    while rec.is_active and rec.next_run_on <= today:
        if rec.ends_on is not None and rec.next_run_on > rec.ends_on:
            rec.is_active = False
            break
        if rec.max_occurrences is not None and rec.occurrences_created >= rec.max_occurrences:
            rec.is_active = False
            break

        _post_one(rec, rec.next_run_on)
        posted += 1
        rec.occurrences_created += 1
        rec.last_run_at = timezone.now()
        rec.next_run_on = nth_occurrence(
            starts_on=rec.starts_on,
            frequency=rec.frequency,
            interval=rec.interval,
            n=rec.occurrences_created,
        )
        # deactivate if we've now walked past the configured end
        if rec.max_occurrences is not None and rec.occurrences_created >= rec.max_occurrences:
            rec.is_active = False
        if rec.ends_on is not None and rec.next_run_on > rec.ends_on:
            rec.is_active = False

    rec.save(update_fields=["occurrences_created", "last_run_at", "next_run_on", "is_active", "updated_at"])
    return posted


@transaction.atomic
def confirm_occurrence(
    *,
    rec: RecurringTransaction,
    amount_minor: int | None = None,
    occurred_on: date | None = None,
) -> tuple[RecurringTransaction, object]:
    """Mark the next occurrence paid/received and advance the schedule.

    Posts one real transaction (income, expense, or transfer) for the template's
    current ``next_run_on``, using ``amount_minor`` when the actual amount
    differs from the plan. Advancing ``next_run_on`` is what stops Celery from
    double-posting the same date, and what makes "next due" move forward in the
    UI after a member taps Mark paid.
    """
    rec = RecurringTransaction.objects.select_for_update().get(pk=rec.pk)
    if not rec.is_active:
        raise RecurringError("Paused schedules cannot be marked paid — resume them first.")

    scheduled_on = occurred_on or rec.next_run_on
    if rec.ends_on is not None and scheduled_on > rec.ends_on:
        raise RecurringError("This schedule has already ended.")
    if rec.max_occurrences is not None and rec.occurrences_created >= rec.max_occurrences:
        raise RecurringError("This schedule has no remaining occurrences.")

    pay_amount = amount_minor if amount_minor is not None else rec.amount_minor
    if pay_amount <= 0:
        raise RecurringError("Amount must be positive.")

    # Post with the confirmed amount without permanently rewriting the plan.
    original_amount = rec.amount_minor
    rec.amount_minor = pay_amount
    try:
        txn = _post_one(rec, scheduled_on)
    finally:
        rec.amount_minor = original_amount

    rec.occurrences_created += 1
    rec.last_run_at = timezone.now()
    # Walk from the scheduled date that was just confirmed so the next due
    # date stays aligned even when the member confirmed early or late.
    if scheduled_on == rec.next_run_on:
        rec.next_run_on = nth_occurrence(
            starts_on=rec.starts_on,
            frequency=rec.frequency,
            interval=rec.interval,
            n=rec.occurrences_created,
        )
    else:
        # Confirmed a different date: advance past the template's stored next
        # run so Celery cannot re-post the outstanding slot.
        rec.next_run_on = nth_occurrence(
            starts_on=rec.starts_on,
            frequency=rec.frequency,
            interval=rec.interval,
            n=rec.occurrences_created,
        )

    if rec.max_occurrences is not None and rec.occurrences_created >= rec.max_occurrences:
        rec.is_active = False
    if rec.ends_on is not None and rec.next_run_on > rec.ends_on:
        rec.is_active = False

    rec.save(
        update_fields=[
            "amount_minor",
            "occurrences_created",
            "last_run_at",
            "next_run_on",
            "is_active",
            "updated_at",
        ]
    )
    return rec, txn


def materialize_due(*, today: date | None = None) -> int:
    """Run every active, due template in the CURRENT tenant context. Returns
    total occurrences posted. (Tenant scoping is enforced by RLS; the beat
    task iterates tenants — see tasks.py.)"""
    today = today or timezone.localdate()
    due = RecurringTransaction.objects.filter(is_active=True, next_run_on__lte=today)
    return sum(run_due_template(rec, today=today) for rec in due)
