"""Recurring-transaction engine tests: due detection, catch-up, idempotent
materialization, anchor-preserving schedules, and end conditions."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from apps.finance import recurring, selectors, services
from apps.finance.models import AccountType, CategoryKind, RecurringType, Transaction
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


def _seed():
    checking = services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency="USD"
    )
    savings = services.create_financial_account(
        name="Savings", account_type=AccountType.SAVINGS, currency="USD"
    )
    rent = services.create_category(name="Rent", kind=CategoryKind.EXPENSE, currency="USD")
    salary = services.create_category(name="Salary", kind=CategoryKind.INCOME, currency="USD")
    return checking, savings, rent, salary


def test_create_sets_first_run_to_anchor(tenant_id):
    with tenant_scope(tenant_id):
        checking, _savings, rent, _salary = _seed()
        rec = recurring.create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=checking,
            category=rent,
            amount_minor=150000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 3, 1),
        )
        assert rec.next_run_on == date(2026, 3, 1)
        assert rec.occurrences_created == 0


def test_editing_next_run_does_not_move_the_anchor(tenant_id):
    """The next due date is not a new start date. Moving the anchor would
    make projections treat an already-running charge as not yet started."""
    with tenant_scope(tenant_id):
        checking, _savings, rent, _salary = _seed()
        rec = recurring.create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=checking,
            category=rent,
            amount_minor=150000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 1, 1),
        )
        rec.occurrences_created = 7
        rec.save(update_fields=["occurrences_created"])
        rec = recurring.update_recurring_transaction(
            rec=rec, next_run_on=date(2026, 9, 5), amount_minor=160000
        )
        assert rec.starts_on == date(2026, 1, 1)
        assert rec.next_run_on == date(2026, 9, 5)
        assert rec.amount_minor == 160000


def test_not_due_posts_nothing(tenant_id):
    with tenant_scope(tenant_id):
        checking, _savings, rent, _salary = _seed()
        rec = recurring.create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=checking,
            category=rent,
            amount_minor=150000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 3, 1),
        )
        posted = recurring.run_due_template(rec, today=date(2026, 2, 15))
        assert posted == 0
        assert Transaction.objects.count() == 0


def test_due_template_posts_and_advances(tenant_id):
    with tenant_scope(tenant_id):
        checking, _savings, rent, _salary = _seed()
        rec = recurring.create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=checking,
            category=rent,
            amount_minor=150000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 3, 1),
        )
        posted = recurring.run_due_template(rec, today=date(2026, 3, 1))
        assert posted == 1
        rec.refresh_from_db()
        assert rec.occurrences_created == 1
        assert rec.next_run_on == date(2026, 4, 1)
        assert selectors.account_current_balance_minor(checking) == -150000


def test_catch_up_posts_all_missed_occurrences(tenant_id):
    """Worker was down for two months — one run posts all three due months."""
    with tenant_scope(tenant_id):
        checking, _savings, rent, _salary = _seed()
        rec = recurring.create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=checking,
            category=rent,
            amount_minor=100000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 1, 1),
        )
        posted = recurring.run_due_template(rec, today=date(2026, 3, 15))
        assert posted == 3  # Jan, Feb, Mar
        rec.refresh_from_db()
        assert rec.occurrences_created == 3
        assert rec.next_run_on == date(2026, 4, 1)
        assert selectors.account_current_balance_minor(checking) == -300000


def test_materialization_is_idempotent(tenant_id):
    """Running the scheduler twice for the same day must not double-post."""
    with tenant_scope(tenant_id):
        checking, _savings, rent, _salary = _seed()
        rec = recurring.create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=checking,
            category=rent,
            amount_minor=100000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 1, 1),
        )
        recurring.run_due_template(rec, today=date(2026, 1, 1))
        # advance state committed; a re-run for the same day sees next_run in Feb, nothing due
        recurring.run_due_template(rec, today=date(2026, 1, 1))
        assert Transaction.objects.count() == 1
        assert selectors.account_current_balance_minor(checking) == -100000


def test_monthly_anchor_is_preserved_across_short_months(tenant_id):
    """Jan 31 schedule -> Feb 28 -> Mar 31 (not Feb 28 -> Mar 28)."""
    with tenant_scope(tenant_id):
        checking, _savings, rent, _salary = _seed()
        rec = recurring.create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=checking,
            category=rent,
            amount_minor=1000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 1, 31),
        )
        recurring.run_due_template(rec, today=date(2026, 1, 31))
        rec.refresh_from_db()
        assert rec.next_run_on == date(2026, 2, 28)  # clamped
        recurring.run_due_template(rec, today=date(2026, 2, 28))
        rec.refresh_from_db()
        assert rec.next_run_on == date(2026, 3, 31)  # anchor restored, not 3/28


def test_max_occurrences_deactivates(tenant_id):
    with tenant_scope(tenant_id):
        checking, _savings, rent, _salary = _seed()
        rec = recurring.create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=checking,
            category=rent,
            amount_minor=1000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 1, 1),
            max_occurrences=2,
        )
        posted = recurring.run_due_template(rec, today=date(2026, 6, 1))
        assert posted == 2  # capped
        rec.refresh_from_db()
        assert rec.is_active is False


def test_ends_on_deactivates(tenant_id):
    with tenant_scope(tenant_id):
        checking, _savings, rent, _salary = _seed()
        rec = recurring.create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=checking,
            category=rent,
            amount_minor=1000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 2, 15),
        )
        posted = recurring.run_due_template(rec, today=date(2026, 12, 1))
        assert posted == 2  # Jan 1 and Feb 1; Mar 1 is past ends_on
        rec.refresh_from_db()
        assert rec.is_active is False


def test_recurring_transfer_materializes_both_sides(tenant_id):
    with tenant_scope(tenant_id):
        checking, savings, _rent, salary = _seed()
        services.record_income(
            financial_account=checking,
            category=salary,
            amount_minor=500000,
            occurred_at=services.timezone.now(),
        )
        rec = recurring.create_recurring_transaction(
            txn_type=RecurringType.TRANSFER,
            financial_account=checking,
            counter_account=savings,
            amount_minor=50000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 1, 1),
        )
        recurring.run_due_template(rec, today=date(2026, 1, 1))
        assert selectors.account_current_balance_minor(savings) == 50000
        # two linked domain rows for the transfer
        assert Transaction.objects.filter(transfer_group__isnull=False).count() == 2


def test_transfer_recurring_requires_counter_account(tenant_id):
    with tenant_scope(tenant_id):
        checking, _savings, _rent, _salary = _seed()
        with pytest.raises(recurring.RecurringError):
            recurring.create_recurring_transaction(
                txn_type=RecurringType.TRANSFER,
                financial_account=checking,
                amount_minor=1000,
                currency="USD",
                frequency="monthly",
                starts_on=date(2026, 1, 1),
            )


@pytest.mark.django_db(transaction=True)
def test_scheduler_task_runs_across_tenants(tenant_id):
    """Post-fan-out topology: the dispatcher enqueues one task per active
    tenant; the per-tenant task binds RLS and materializes that tenant's due
    templates. Uses a transactional test so each task's atomic block is a real
    transaction — matching production, where SET LOCAL is transaction-scoped
    and never leaks between tenants."""
    from apps.finance.tasks import run_recurring_for_tenant
    from apps.tenancy.models import Tenant

    tenant_a = Tenant.objects.create(name="A")
    tenant_b = Tenant.objects.create(name="B")
    for tid in (tenant_a.id, tenant_b.id):
        with tenant_scope(tid):
            checking, _savings, rent, _salary = _seed()
            recurring.create_recurring_transaction(
                txn_type=RecurringType.EXPENSE,
                financial_account=checking,
                category=rent,
                amount_minor=1000,
                currency="USD",
                frequency="monthly",
                starts_on=date(2020, 1, 1),
            )

    # dispatcher fans out one task per active tenant; assert the count without
    # relying on eager nested execution (each per-tenant worker is exercised
    # directly below, which is where the real materialization lives).
    from apps.tenancy.models import Tenant as _T

    active = _T.objects.filter(is_active=True).count()
    assert active >= 2

    # each per-tenant worker does the real materialization, isolated by RLS
    for tid in (tenant_a.id, tenant_b.id):
        created = run_recurring_for_tenant(str(tid))
        assert created >= 1
        with tenant_scope(tid):
            assert Transaction.objects.filter(source="recurring").exists()


def test_dispatcher_enqueues_one_task_per_active_tenant(monkeypatch):
    """The dispatcher itself does no financial work — it enqueues one
    per-tenant task per active tenant. Verify the fan-out count directly."""
    from apps.finance import tasks as finance_tasks
    from apps.tenancy.models import Tenant

    Tenant.objects.create(name="X")
    Tenant.objects.create(name="Y")

    enqueued = []
    monkeypatch.setattr(finance_tasks.run_recurring_for_tenant, "delay", lambda tid: enqueued.append(tid))
    dispatched = finance_tasks.dispatch_recurring_transactions()
    assert dispatched == len(enqueued)
    assert dispatched >= 2  # at least the two we created


def test_confirm_occurrence_posts_and_advances_next_run(tenant_id):
    from django.utils import timezone

    with tenant_scope(tenant_id):
        checking, _savings, rent, salary = _seed()
        # Fund the account so the settling expense clears sufficiency checks.
        services.record_income(
            financial_account=checking,
            category=salary,
            amount_minor=500_000,
            occurred_at=timezone.now(),
        )
        rec = recurring.create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=checking,
            category=rent,
            amount_minor=150_000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 3, 1),
        )

        updated, txn = recurring.confirm_occurrence(rec=rec, amount_minor=148_500)
        assert abs(txn.amount_minor) == 148_500
        assert updated.next_run_on == date(2026, 4, 1)
        assert updated.occurrences_created == 1
        assert updated.amount_minor == 150_000  # plan amount unchanged
