"""Cash flow calendar projection.

The tests that matter most here are the ones guarding against *manufactured*
figures: an internal transfer counted as an outflow, or an overdraft warning
raised for a dip that never happens. A false overdraft warning is the most
damaging thing this feature could produce — it would train users to ignore the
real ones.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.finance import cashflow_calendar as cc
from apps.finance import services as finance_services
from apps.finance.bills import create_bill
from apps.finance.models import AccountType, CategoryKind, Frequency, RecurringType
from apps.finance.recurring import create_recurring_transaction as create_recurring
from apps.income.models import IncomeKind, IncomeReceipt, IncomeSource, Reliability
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return uuid.uuid4()


def _today() -> date:
    return timezone.localdate()


def _account(name: str, *, opening: int = 0, account_type: str = AccountType.CHECKING, currency="USD"):
    return finance_services.create_financial_account(
        name=name, account_type=account_type, currency=currency, opening_balance_minor=opening
    )


def _source(
    recurring,
    *,
    kind: str,
    net_minor: int,
    currency: str = "USD",
    reliability: str = Reliability.FIXED,
):
    """Attach an income source to a schedule template."""
    return IncomeSource.objects.create(
        name=recurring.memo or "Income",
        kind=kind,
        currency=currency,
        net_minor=net_minor,
        reliability=reliability,
        frequency="monthly",
        starts_on=recurring.starts_on,
        recurring_transaction=recurring,
    )


def _category(name: str, kind: str = CategoryKind.EXPENSE):
    return finance_services.create_category(name=name, kind=kind, currency="USD")


def _recur(**kwargs):
    """create_recurring_transaction with a category supplied by default.

    Income and expense templates must post to a category's ledger account, so
    every call needs one; defaulting it keeps each test focused on the
    projection behaviour it actually exercises.
    """
    if kwargs.get("txn_type") != RecurringType.TRANSFER and "category" not in kwargs:
        kind = CategoryKind.INCOME if kwargs["txn_type"] == RecurringType.INCOME else CategoryKind.EXPENSE
        suffix = kwargs.get("memo") or "Auto"
        kwargs["category"] = _category(f"{suffix} category", kind)
    return create_recurring(**kwargs)


# ------------------------------------------------------------------ basics
def test_returns_none_without_any_liquid_account(tenant):
    with tenant_scope(tenant):
        # An empty calendar would imply a zero balance — a claim, not an absence.
        assert cc.cashflow_calendar() is None


def test_projection_starts_from_the_actual_liquid_balance(tenant):
    with tenant_scope(tenant):
        _account("Checking", opening=2_500_00)
        cal = cc.cashflow_calendar(days=7)

        assert cal is not None
        assert cal.currency == "USD"
        assert cal.opening_balance_minor == 2_500_00
        # Day one is fact; nothing scheduled means the line stays flat.
        assert cal.days[0].opening_minor == 2_500_00
        assert cal.closing_balance_minor == 2_500_00
        assert len(cal.days) == 7


def test_horizon_is_clamped_to_a_defensible_ceiling(tenant):
    with tenant_scope(tenant):
        _account("Checking", opening=100_00)
        cal = cc.cashflow_calendar(days=5_000)
        assert cal is not None
        # Beyond a year a projection from today's schedule is fiction.
        assert len(cal.days) == cc.MAX_HORIZON_DAYS


# ------------------------------------------------------- recurring movements
def test_recurring_income_raises_the_running_balance_on_its_day(tenant):
    with tenant_scope(tenant):
        account = _account("Checking", opening=100_00)
        payday = _today() + timedelta(days=3)
        _recur(
            txn_type=RecurringType.INCOME,
            financial_account=account,
            amount_minor=2_000_00,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=payday,
            memo="Salary",
        )

        cal = cc.cashflow_calendar(days=7)
        assert cal is not None
        day = next(d for d in cal.days if d.day == payday)
        assert day.inflow_minor == 2_000_00
        assert day.closing_minor == 2_100_00
        # Balance carries forward, not just on the day itself.
        assert cal.days[-1].closing_minor == 2_100_00


def test_salary_is_marked_distinctly_from_other_income(tenant):
    """Payday is marked from the income source's kind, not from its memo."""
    with tenant_scope(tenant):
        account = _account("Checking", opening=0)
        salary = _recur(
            txn_type=RecurringType.INCOME,
            financial_account=account,
            amount_minor=3_000_00,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=_today() + timedelta(days=1),
            memo="Monthly salary",
        )
        rent = _recur(
            txn_type=RecurringType.INCOME,
            financial_account=account,
            amount_minor=50_00,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=_today() + timedelta(days=2),
            memo="Interest",
        )
        _source(salary, kind=IncomeKind.EMPLOYMENT, net_minor=3_000_00)
        _source(rent, kind=IncomeKind.INVESTMENT, net_minor=50_00)

        cal = cc.cashflow_calendar(days=7)
        sources = {e.source for d in cal.days for e in d.events}
        # "Can I make it to payday?" is the question users navigate by.
        assert cc.EventSource.SALARY in sources
        assert cc.EventSource.INCOME in sources


def test_a_payday_in_another_language_is_still_a_payday(tenant):
    """The regression this whole model exists to prevent.

    The retired implementation searched the memo for the English words
    "salary", "payroll", "wage" and "paycheck". A household paid in KES whose
    memo reads "Mshahara" got no payday marker, on a screen built entirely
    around finding the next payday.
    """
    with tenant_scope(tenant):
        account = _account("Checking", opening=0, currency="KES")
        template = _recur(
            txn_type=RecurringType.INCOME,
            financial_account=account,
            amount_minor=80_000_00,
            currency="KES",
            frequency=Frequency.MONTHLY,
            starts_on=_today() + timedelta(days=1),
            memo="Mshahara",
        )
        _source(template, kind=IncomeKind.EMPLOYMENT, net_minor=80_000_00, currency="KES")

        cal = cc.cashflow_calendar(days=7)
        sources = {e.source for d in cal.days for e in d.events}
        assert cc.EventSource.SALARY in sources


def test_an_english_memo_alone_no_longer_marks_a_payday(tenant):
    """The other half of the same change.

    Without a source attached, "Monthly salary" is now generic income. Guessing
    from a label is what produced the defect above; not guessing has to mean
    not guessing in both directions.
    """
    with tenant_scope(tenant):
        account = _account("Checking", opening=0)
        _recur(
            txn_type=RecurringType.INCOME,
            financial_account=account,
            amount_minor=3_000_00,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=_today() + timedelta(days=1),
            memo="Monthly salary payroll wage paycheck",
        )

        cal = cc.cashflow_calendar(days=7)
        sources = {e.source for d in cal.days for e in d.events}
        assert cc.EventSource.SALARY not in sources
        assert cc.EventSource.INCOME in sources


def test_variable_income_projects_from_receipts_not_the_typed_amount(tenant):
    """A stale form value is the least informed estimate once receipts exist."""
    with tenant_scope(tenant):
        account = _account("Checking", opening=0)
        template = _recur(
            txn_type=RecurringType.INCOME,
            financial_account=account,
            amount_minor=1_000_00,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=_today() + timedelta(days=1),
            memo="Retainer",
        )
        source = _source(
            template,
            kind=IncomeKind.SELF_EMPLOYMENT,
            net_minor=1_000_00,
            reliability=Reliability.VARIABLE,
        )
        # Three months of reality, all well above what the form says.
        for n, amount in enumerate((2_000_00, 2_200_00, 2_400_00), start=1):
            IncomeReceipt.objects.create(
                source=source, occurred_on=_today() - timedelta(days=30 * n), net_minor=amount
            )

        cal = cc.cashflow_calendar(days=7)
        amounts = [e.amount_minor for d in cal.days for e in d.events if e.amount_minor > 0]
        # mean(2000, 2200, 2400) = 2200, not the 1000 on the template.
        assert amounts == [2_200_00]


def test_recurring_expense_lowers_the_balance(tenant):
    with tenant_scope(tenant):
        account = _account("Checking", opening=500_00)
        due = _today() + timedelta(days=2)
        _recur(
            txn_type=RecurringType.EXPENSE,
            financial_account=account,
            amount_minor=120_00,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=due,
            memo="Gym",
        )

        cal = cc.cashflow_calendar(days=5)
        day = next(d for d in cal.days if d.day == due)
        assert day.outflow_minor == 120_00
        assert day.closing_minor == 380_00


def test_subscriptions_are_classified_separately_from_other_expenses(tenant):
    with tenant_scope(tenant):
        account = _account("Checking", opening=500_00)
        subs = _category("Subscriptions")
        _recur(
            txn_type=RecurringType.EXPENSE,
            financial_account=account,
            category=subs,
            amount_minor=15_00,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=_today() + timedelta(days=1),
            memo="Streaming",
        )
        cal = cc.cashflow_calendar(days=5)
        sources = {e.source for d in cal.days for e in d.events}
        assert cc.EventSource.SUBSCRIPTION in sources


def test_weekly_recurrence_repeats_across_the_window(tenant):
    with tenant_scope(tenant):
        account = _account("Checking", opening=1_000_00)
        _recur(
            txn_type=RecurringType.EXPENSE,
            financial_account=account,
            amount_minor=20_00,
            currency="USD",
            frequency=Frequency.WEEKLY,
            starts_on=_today(),
            memo="Groceries",
        )
        cal = cc.cashflow_calendar(days=28)
        occurrences = sum(1 for d in cal.days for e in d.events)
        assert occurrences == 4
        assert cal.closing_balance_minor == 1_000_00 - 4 * 20_00


def test_recurrence_stops_at_its_end_date(tenant):
    with tenant_scope(tenant):
        account = _account("Checking", opening=1_000_00)
        _recur(
            txn_type=RecurringType.EXPENSE,
            financial_account=account,
            amount_minor=20_00,
            currency="USD",
            frequency=Frequency.WEEKLY,
            starts_on=_today(),
            ends_on=_today() + timedelta(days=10),
            memo="Short run",
        )
        cal = cc.cashflow_calendar(days=28)
        assert sum(1 for d in cal.days for e in d.events) == 2


# ------------------------------------------------------------------ transfers
def test_internal_transfers_do_not_change_the_projected_balance(tenant):
    """The single most important correctness property in this module.

    Moving money between two counted accounts leaves total cash unchanged;
    counting it would manufacture a dip and, worse, a fake overdraft warning.
    """
    with tenant_scope(tenant):
        checking = _account("Checking", opening=1_000_00)
        savings = _account("Savings", opening=500_00, account_type=AccountType.SAVINGS)
        _recur(
            txn_type=RecurringType.TRANSFER,
            financial_account=checking,
            counter_account=savings,
            amount_minor=200_00,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=_today() + timedelta(days=1),
            memo="To savings",
        )

        cal = cc.cashflow_calendar(days=10)
        assert cal.opening_balance_minor == 1_500_00
        assert cal.closing_balance_minor == 1_500_00
        assert all(not d.has_events for d in cal.days)


def test_a_transfer_leaving_the_projected_set_does_count(tenant):
    """A standing payment to a credit card really does reduce available cash."""
    with tenant_scope(tenant):
        checking = _account("Checking", opening=1_000_00)
        card = _account("Card", account_type=AccountType.CREDIT_CARD)
        _recur(
            txn_type=RecurringType.TRANSFER,
            financial_account=checking,
            counter_account=card,
            amount_minor=300_00,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=_today() + timedelta(days=1),
            memo="Card payment",
        )

        cal = cc.cashflow_calendar(days=10)
        assert cal.closing_balance_minor == 700_00
        sources = {e.source for d in cal.days for e in d.events}
        assert cc.EventSource.TRANSFER_OUT in sources


# ---------------------------------------------------------------------- bills
def test_unpaid_bills_reduce_the_projection(tenant):
    with tenant_scope(tenant):
        _account("Checking", opening=1_000_00)
        due = _today() + timedelta(days=4)
        create_bill(name="Electricity", amount_minor=90_00, currency="USD", due_on=due)

        cal = cc.cashflow_calendar(days=10)
        day = next(d for d in cal.days if d.day == due)
        assert day.outflow_minor == 90_00
        assert cal.closing_balance_minor == 910_00


def test_overdue_bills_are_pulled_into_the_window(tenant):
    """The money hasn't left yet, so it still belongs in the projection.
    Dropping it would overstate the balance."""
    with tenant_scope(tenant):
        _account("Checking", opening=500_00)
        create_bill(
            name="Late rent", amount_minor=200_00, currency="USD", due_on=_today() - timedelta(days=5)
        )

        cal = cc.cashflow_calendar(days=7)
        first = cal.days[0]
        assert first.outflow_minor == 200_00
        assert any(e.is_overdue for e in first.events)


def test_recurring_bills_project_beyond_their_stored_occurrence(tenant):
    """A recurring bill only spawns its successor when paid, so without this
    the calendar would show rent once and imply rent-free months after."""
    with tenant_scope(tenant):
        _account("Checking", opening=10_000_00)
        create_bill(
            name="Rent",
            amount_minor=1_200_00,
            currency="USD",
            due_on=_today() + timedelta(days=1),
            recurrence_frequency=Frequency.MONTHLY,
        )

        cal = cc.cashflow_calendar(days=95)
        rent_days = [e for d in cal.days for e in d.events if e.description == "Rent"]
        assert len(rent_days) >= 3


# ------------------------------------------------------------------ overdraft
def test_predicted_overdraft_is_reported_with_its_date(tenant):
    with tenant_scope(tenant):
        account = _account("Checking", opening=100_00)
        overdraft_day = _today() + timedelta(days=3)
        _recur(
            txn_type=RecurringType.EXPENSE,
            financial_account=account,
            amount_minor=250_00,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=overdraft_day,
            memo="Insurance",
        )

        cal = cc.cashflow_calendar(days=10)
        assert cal.first_negative_on == overdraft_day
        assert cal.lowest_balance_minor == -150_00
        assert cal.lowest_balance_on == overdraft_day
        assert cal.negative_day_count == 7


def test_no_overdraft_flagged_when_income_lands_first(tenant):
    """Ordering is the whole point: the same two movements are safe or unsafe
    depending on which arrives first."""
    with tenant_scope(tenant):
        account = _account("Checking", opening=100_00)
        _recur(
            txn_type=RecurringType.INCOME,
            financial_account=account,
            amount_minor=500_00,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=_today() + timedelta(days=1),
            memo="Salary",
        )
        _recur(
            txn_type=RecurringType.EXPENSE,
            financial_account=account,
            amount_minor=400_00,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=_today() + timedelta(days=2),
            memo="Rent",
        )

        cal = cc.cashflow_calendar(days=10)
        assert cal.first_negative_on is None
        assert cal.negative_day_count == 0
        assert cal.lowest_balance_minor == 100_00


def test_trough_is_reported_even_when_the_month_ends_healthy(tenant):
    """A month total can look fine while the balance dips below zero mid-month.
    That dip is what actually costs an overdraft fee."""
    with tenant_scope(tenant):
        account = _account("Checking", opening=100_00)
        _recur(
            txn_type=RecurringType.EXPENSE,
            financial_account=account,
            amount_minor=300_00,
            currency="USD",
            frequency=Frequency.YEARLY,
            starts_on=_today() + timedelta(days=1),
            memo="Big bill",
        )
        _recur(
            txn_type=RecurringType.INCOME,
            financial_account=account,
            amount_minor=500_00,
            currency="USD",
            frequency=Frequency.YEARLY,
            starts_on=_today() + timedelta(days=3),
            memo="Salary",
        )

        cal = cc.cashflow_calendar(days=10)
        assert cal.closing_balance_minor == 300_00  # ends healthy
        assert cal.lowest_balance_minor == -200_00  # but dipped
        assert cal.first_negative_on == _today() + timedelta(days=1)


# ------------------------------------------------------------------ day detail
def test_day_detail_carries_the_inherited_running_balance(tenant):
    with tenant_scope(tenant):
        account = _account("Checking", opening=1_000_00)
        target = _today() + timedelta(days=5)
        _recur(
            txn_type=RecurringType.EXPENSE,
            financial_account=account,
            amount_minor=100_00,
            currency="USD",
            frequency=Frequency.YEARLY,
            starts_on=_today() + timedelta(days=2),
            memo="Earlier expense",
        )

        day = cc.cashflow_day(day=target)
        assert day is not None
        # Opening reflects everything between today and then, not just today.
        assert day.opening_minor == 900_00


def test_day_detail_refuses_the_past(tenant):
    with tenant_scope(tenant):
        _account("Checking", opening=100_00)
        # The past is record, not projection — callers should read the ledger.
        assert cc.cashflow_day(day=_today() - timedelta(days=1)) is None


# ------------------------------------------------------------------ currency
def test_projection_stays_within_one_currency(tenant):
    """Inherits the discipline of net_worth and cashflow_statement: silently
    summing currencies is a correctness bug, not a feature."""
    with tenant_scope(tenant):
        _account("USD Checking", opening=1_000_00)
        eur = _account("EUR Checking", opening=5_000_00, currency="EUR")
        _recur(
            txn_type=RecurringType.EXPENSE,
            financial_account=eur,
            amount_minor=100_00,
            currency="EUR",
            frequency=Frequency.MONTHLY,
            starts_on=_today() + timedelta(days=1),
            memo="EUR expense",
        )

        cal = cc.cashflow_calendar(days=10)
        assert cal is not None
        # The EUR movement must not touch a USD projection.
        assert cal.currency == "EUR" or all(e.currency == cal.currency for d in cal.days for e in d.events)
        assert cal.opening_balance_minor in (1_000_00, 5_000_00)


# ---------------------------------------------------------------------- API
def test_calendar_endpoint_returns_the_projection(tenant_context):
    _, client = tenant_context
    client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD", "opening_balance_minor": 100000},
        format="json",
    )

    resp = client.get("/api/v1/finance/cashflow-calendar/?days=14")
    assert resp.status_code == 200, resp.data
    assert resp.data["currency"] == "USD"
    assert resp.data["opening_balance_minor"] == 100000
    assert len(resp.data["days"]) == 14
    # No scheduled movement means no predicted overdraft.
    assert resp.data["first_negative_on"] is None


def test_calendar_endpoint_reports_no_content_without_liquid_accounts(tenant_context):
    _, client = tenant_context
    resp = client.get("/api/v1/finance/cashflow-calendar/")
    # 204, not an empty calendar: a zero balance would be a claim.
    assert resp.status_code == 204


def test_calendar_endpoint_rejects_an_absurd_window(tenant_context):
    _, client = tenant_context
    resp = client.get("/api/v1/finance/cashflow-calendar/?days=9999")
    # A clear 400 beats silently returning a different window than requested.
    assert resp.status_code == 400


def test_day_endpoint_returns_detail_for_a_future_day(tenant_context):
    _, client = tenant_context
    client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD", "opening_balance_minor": 50000},
        format="json",
    )
    target = timezone.localdate() + timedelta(days=3)

    resp = client.get(f"/api/v1/finance/cashflow-calendar/{target.isoformat()}/")
    assert resp.status_code == 200, resp.data
    assert resp.data["day"] == target
    assert resp.data["opening_minor"] == 50000


def test_day_endpoint_refuses_a_past_day(tenant_context):
    _, client = tenant_context
    client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD", "opening_balance_minor": 50000},
        format="json",
    )
    past = (timezone.localdate() - timedelta(days=2)).isoformat()
    assert client.get(f"/api/v1/finance/cashflow-calendar/{past}/").status_code == 404


# =============================================================================
# Everyday spending — the band
# =============================================================================
def _spend(account, category, *, amount: int, days_ago: int, source=None):
    from apps.finance.models import TransactionSource

    return finance_services.record_expense(
        financial_account=account,
        category=category,
        amount_minor=amount,
        occurred_at=timezone.now() - timedelta(days=days_ago),
        source=source or TransactionSource.MANUAL,
    )


def test_projection_without_history_reports_no_band_rather_than_a_flat_one(tenant):
    """An absent band is a true statement about what the product knows. A
    zero-width one would claim the user spends nothing outside their schedule,
    which is a claim about their life rather than about the data."""
    with tenant_scope(tenant):
        _account("Checking", opening=500_00)
        calendar = cc.cashflow_calendar(days=30)
        assert calendar.everyday is None
        assert all(d.expected_minor is None for d in calendar.days)


def test_the_band_is_measured_from_unscheduled_spending(tenant):
    with tenant_scope(tenant):
        account = _account("Checking", opening=1_000_00)
        groceries = _category("Groceries")
        # 60 days of history, spending on every other day.
        for day in range(1, 61):
            if day % 2 == 0:
                _spend(account, groceries, amount=1_000, days_ago=day)

        calendar = cc.cashflow_calendar(days=30)
        assert calendar.everyday is not None
        assert calendar.everyday.active_days == 30
        assert calendar.everyday.observed_days == 90
        # 30 active days of 1,000 over a 90-day window.
        assert calendar.everyday.mean_minor == round(30 * 1_000 / 90)
        # The median day is empty — which is exactly why the median must not be
        # what the projection accumulates. See EverydaySpending.
        assert calendar.everyday.median_minor == 0
        assert calendar.everyday.stdev_minor > 0


def test_scheduled_spending_is_not_counted_twice(tenant):
    """A recurring charge is already in the projection as an event. Counting it
    again in the band would subtract it from the balance twice."""
    from apps.finance.models import TransactionSource

    with tenant_scope(tenant):
        account = _account("Checking", opening=1_000_00)
        rent = _category("Rent")
        for day in range(1, 61):
            _spend(account, rent, amount=5_000, days_ago=day, source=TransactionSource.RECURRING)

        calendar = cc.cashflow_calendar(days=30)
        assert calendar.everyday is None


def test_the_band_only_ever_sits_below_the_scheduled_line(tenant):
    """Everyday spending takes money out. The schedule-only projection is
    therefore the optimistic edge of the range, never the middle of it —
    getting this backwards would make the calendar *more* reassuring than the
    version that ignored spending entirely."""
    with tenant_scope(tenant):
        account = _account("Checking", opening=1_000_00)
        groceries = _category("Groceries")
        for day in range(1, 61):
            _spend(account, groceries, amount=2_000, days_ago=day)

        calendar = cc.cashflow_calendar(days=30)
        future = [d for d in calendar.days if d.day > _today()]
        assert future, "expected projected days beyond today"
        for day in future:
            assert day.expected_minor <= day.closing_minor
            assert day.expected_low_minor <= day.expected_minor <= day.expected_high_minor

        # And it widens with distance: uncertainty about next month is not the
        # same size as uncertainty about tomorrow.
        first, last = future[0], future[-1]
        assert (last.expected_high_minor - last.expected_low_minor) >= (
            first.expected_high_minor - first.expected_low_minor
        )


def test_an_internal_transfer_is_not_everyday_spending(tenant):
    """Same discipline the projection itself applies: money moved between two
    projected accounts never left, so it must not widen the band."""
    with tenant_scope(tenant):
        checking = _account("Checking", opening=1_000_00)
        savings = _account("Savings", opening=500_00, account_type=AccountType.SAVINGS)
        for day in range(1, 61):
            finance_services.record_transfer(
                from_account=checking,
                to_account=savings,
                amount_minor=1_000,
                occurred_at=timezone.now() - timedelta(days=day),
            )

        calendar = cc.cashflow_calendar(days=30)
        assert calendar.everyday is None


def test_the_projection_accumulates_the_mean_not_the_median(tenant):
    """The correctness of the band, in one test.

    Spending is bursty: this user spends on one day in five. The median day is
    therefore zero, and a projection accumulating the median would draw a
    "likely" line sitting exactly on the scheduled one — silently reinstating
    the optimism the band exists to correct. The expected total over k days is
    `k x mean`.
    """
    with tenant_scope(tenant):
        account = _account("Checking", opening=10_000_00)
        groceries = _category("Groceries")
        for day in range(1, 91):
            if day % 5 == 0:
                _spend(account, groceries, amount=5_000, days_ago=day)

        calendar = cc.cashflow_calendar(days=30)
        everyday = calendar.everyday
        assert everyday.median_minor == 0, "precondition: a bursty spender"
        assert everyday.mean_minor > 0

        future = [d for d in calendar.days if d.day > _today()]
        # The median would have left this identical to the scheduled line.
        assert future[-1].expected_minor < future[-1].closing_minor
        expected_drift = everyday.mean_minor * len(future)
        assert future[-1].closing_minor - future[-1].expected_minor == expected_drift


def test_uncertainty_grows_with_the_square_root_of_the_horizon(tenant):
    """Independent daily variation partly cancels over a window, so summing a
    high day 45 times describes something far more extreme than a high 45-day
    total. Doubling the horizon widens the band by ~sqrt(2), not 2."""
    with tenant_scope(tenant):
        account = _account("Checking", opening=10_000_00)
        groceries = _category("Groceries")
        for day in range(1, 91):
            _spend(account, groceries, amount=1_000 if day % 3 else 9_000, days_ago=day)

        calendar = cc.cashflow_calendar(days=61)
        future = [d for d in calendar.days if d.day > _today()]
        width = lambda d: d.expected_high_minor - d.expected_low_minor  # noqa: E731

        at_15, at_60 = future[14], future[59]
        ratio = width(at_60) / width(at_15)
        # sqrt(60/15) == 2. Linear growth would give 4.
        assert 1.8 < ratio < 2.2, ratio
