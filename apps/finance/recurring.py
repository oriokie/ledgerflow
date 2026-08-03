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


def materialize_due(*, today: date | None = None) -> int:
    """Run every active, due template in the CURRENT tenant context. Returns
    total occurrences posted. (Tenant scoping is enforced by RLS; the beat
    task iterates tenants — see tasks.py.)"""
    today = today or timezone.localdate()
    due = RecurringTransaction.objects.filter(is_active=True, next_run_on__lte=today)
    return sum(run_due_template(rec, today=today) for rec in due)
