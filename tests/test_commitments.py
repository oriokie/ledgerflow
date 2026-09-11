"""Bills and recurring templates are the same obligation when they match.

A household often records rent twice: as a due-date reminder and as the
standing payment that actually posts. Counting both invents an overdraft.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.finance import bills as bills_service
from apps.finance import cashflow_calendar as cc
from apps.finance import services as finance_services
from apps.finance.commitments import link_matching_commitments
from apps.finance.models import AccountType, Bill, BillStatus, CategoryKind, Frequency, RecurringType
from apps.finance.recurring import create_recurring_transaction
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


def _today():
    return timezone.localdate()


def test_a_linked_bill_is_not_counted_twice():
    """The template already posts the money. The bill must not add a second rent."""
    tid = uuid.uuid4()
    due = _today() + timedelta(days=3)
    with tenant_scope(tid):
        account = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=5_000_00,
        )
        category = finance_services.create_category(name="Rent", kind=CategoryKind.EXPENSE, currency="USD")
        template = create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=account,
            category=category,
            amount_minor=1_200_00,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=due,
            memo="Rent",
        )
        bill = bills_service.create_bill(
            name="Rent",
            amount_minor=1_200_00,
            currency="USD",
            due_on=due,
            category=category,
            recurrence_frequency=Frequency.MONTHLY,
        )
        bill.refresh_from_db()
        assert bill.recurring_transaction_id == template.id

        cal = cc.cashflow_calendar(days=10)
        assert cal is not None
        day = next(d for d in cal.days if d.day == due)
        assert day.outflow_minor == 1_200_00
        assert len([e for e in day.events if e.amount_minor < 0]) == 1


def test_matching_commitments_link_idempotently_after_the_fact():
    tid = uuid.uuid4()
    due = _today() + timedelta(days=2)
    with tenant_scope(tid):
        account = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=1_000_00,
        )
        category = finance_services.create_category(
            name="Internet", kind=CategoryKind.EXPENSE, currency="USD"
        )
        bill = Bill.objects.create(
            name="Internet",
            amount_minor=30_00,
            currency="USD",
            due_on=due,
            category=category,
            recurrence_frequency=Frequency.MONTHLY,
        )
        create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=account,
            category=category,
            amount_minor=30_00,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=due,
            memo="Internet",
        )
        assert bill.recurring_transaction_id is None
        assert link_matching_commitments() == 1
        assert link_matching_commitments() == 0
        bill.refresh_from_db()
        assert bill.recurring_transaction_id is not None


def test_paying_a_linked_bill_moves_the_identity_onto_the_next_occurrence():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        account = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=5_000_00,
        )
        category = finance_services.create_category(name="Rent", kind=CategoryKind.EXPENSE, currency="USD")
        template = create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=account,
            category=category,
            amount_minor=1_200_00,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=_today(),
            memo="Rent",
        )
        bill = bills_service.create_bill(
            name="Rent",
            amount_minor=1_200_00,
            currency="USD",
            due_on=_today(),
            category=category,
            recurrence_frequency=Frequency.MONTHLY,
            recurring_transaction=template,
        )
        bills_service.mark_bill_paid(bill=bill, from_account=account, record_expense=False)
        bill.refresh_from_db()
        assert bill.status == BillStatus.PAID
        assert bill.recurring_transaction_id is None
        nxt = Bill.objects.exclude(id=bill.id).get()
        assert nxt.status == BillStatus.UPCOMING
        assert nxt.recurring_transaction_id == template.id
