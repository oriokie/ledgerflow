"""The four reports added to the platform.

Each is registered rather than bespoke, so these also serve as a check that the
registry contract still holds: a report that returns the standard shape gets
export, caching and a frontend renderer for free.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.analytics.filters import ReportFilters
from apps.analytics.reports import REPORT_META, REPORTS, run_report
from apps.finance import services as finance_services
from apps.finance.models import AccountType, TransactionSource
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


def _account(opening=5000_00):
    account = finance_services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency="USD"
    )
    finance_services.set_opening_balance(financial_account=account, amount_minor=opening)
    return account


def _expense(account, category, amount_minor, when, source=TransactionSource.MANUAL):
    return finance_services.record_expense(
        financial_account=account,
        category=category,
        amount_minor=amount_minor,
        occurred_at=when,
        source=source,
    )


def _category(name="Groceries", kind="expense"):
    return finance_services.create_category(name=name, kind=kind, currency="USD")


# --------------------------------------------------------------- registry
def test_every_registered_report_has_presentation_meta():
    """A report without meta would run but never appear in the UI."""
    assert set(REPORTS) == set(REPORT_META)


def test_new_reports_are_registered():
    for slug in (
        "category_movers",
        "spending_by_weekday",
        "committed_vs_discretionary",
        "income_stability",
    ):
        assert slug in REPORTS
        assert REPORT_META[slug]["group"] in {"position", "flow", "spending", "compare"}


def test_every_report_runs_on_an_empty_workspace():
    """A new workspace opening /reports must not hit an exception anywhere.

    Not asserting `is_empty` across the board: net_worth legitimately emits a
    flat series reconstructed from a zero position, and calling that a bug
    would be this test inventing a rule the platform never had.
    """
    tid = uuid.uuid4()
    with tenant_scope(tid):
        for slug in REPORTS:
            result = run_report(slug, ReportFilters(currency="USD"))
            assert result.slug == slug


def test_the_new_reports_report_nothing_on_an_empty_workspace():
    """Each of these should be an absence, not a claim about zero."""
    tid = uuid.uuid4()
    with tenant_scope(tid):
        for slug in (
            "category_movers",
            "spending_by_weekday",
            "committed_vs_discretionary",
            "income_stability",
        ):
            assert run_report(slug, ReportFilters(currency="USD")).is_empty


# ------------------------------------------------------- spending_by_weekday
def test_weekday_report_buckets_by_day_and_splits_the_weekend():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        account, groceries = _account(), _category()
        # Find a known Saturday inside the default window.
        today = timezone.localtime(timezone.now())
        saturday = today - timedelta(days=(today.weekday() - 5) % 7)
        _expense(account, groceries, 60_00, saturday)

        result = run_report("spending_by_weekday", ReportFilters(currency="USD"))
        by_label = {d["label"]: d for d in result.series}

        assert len(result.series) == 7
        assert by_label["Sat"]["amount_minor"] == 60_00
        assert result.totals["weekend_minor"] == 60_00
        assert result.totals["weekday_minor"] == 0
        assert result.totals["weekend_share"] == 100.0


def test_weekday_report_averages_over_occurrences_not_transactions():
    """A window with more Mondays than Fridays must not make Mondays look bigger."""
    tid = uuid.uuid4()
    with tenant_scope(tid):
        account, groceries = _account(), _category()
        today = timezone.localtime(timezone.now())
        monday = today - timedelta(days=today.weekday())
        _expense(account, groceries, 100_00, monday)

        result = run_report("spending_by_weekday", ReportFilters(currency="USD"))
        mon = next(d for d in result.series if d["label"] == "Mon")
        # Total is the raw sum; average divides by how many Mondays the window held.
        assert mon["amount_minor"] == 100_00
        assert mon["average_minor"] <= mon["amount_minor"]
        assert mon["count"] == 1


# ------------------------------------------------- committed_vs_discretionary
def test_committed_split_counts_only_recurring_posted_spend():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        account = _account()
        rent = _category("Rent")
        fun = _category("Fun")
        now = timezone.now()
        _expense(account, rent, 900_00, now, source=TransactionSource.RECURRING)
        _expense(account, fun, 100_00, now, source=TransactionSource.MANUAL)

        result = run_report("committed_vs_discretionary", ReportFilters(currency="USD"))
        assert result.totals["total_minor"] == 1000_00
        assert result.totals["committed_minor"] == 900_00
        assert result.totals["discretionary_minor"] == 100_00
        assert result.totals["committed_share"] == 90.0


def test_committed_split_survives_a_workspace_with_no_recurring_spend():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        account, fun = _account(), _category("Fun")
        _expense(account, fun, 250_00, timezone.now())

        result = run_report("committed_vs_discretionary", ReportFilters(currency="USD"))
        assert result.totals["committed_minor"] == 0
        assert result.totals["committed_share"] == 0.0
        assert result.totals["discretionary_minor"] == 250_00


# ------------------------------------------------------------ income_stability
def test_income_stability_reports_the_worst_month_not_just_the_average():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        account = _account()
        salary = _category("Salary", kind="income")
        now = timezone.now()
        finance_services.record_income(
            financial_account=account, category=salary, amount_minor=3000_00, occurred_at=now
        )
        finance_services.record_income(
            financial_account=account,
            category=salary,
            amount_minor=1000_00,
            occurred_at=now - timedelta(days=40),
        )

        result = run_report("income_stability", ReportFilters(currency="USD"))
        assert result.totals["highest_minor"] == 3000_00
        assert result.totals["lowest_minor"] == 1000_00
        # The gap between the average and the worst month is the buffer needed.
        assert result.totals["shortfall_minor"] > 0
        assert result.totals["variation"] > 0


def test_income_stability_ignores_months_with_no_income_at_all():
    """A window opening before the account existed must not fake a collapse."""
    tid = uuid.uuid4()
    with tenant_scope(tid):
        account = _account()
        salary = _category("Salary", kind="income")
        finance_services.record_income(
            financial_account=account,
            category=salary,
            amount_minor=2000_00,
            occurred_at=timezone.now(),
        )

        result = run_report("income_stability", ReportFilters(currency="USD"))
        assert result.totals["months_counted"] == 1
        assert result.totals["average_minor"] == 2000_00
        assert result.totals["variation"] == 0.0


# ------------------------------------------------------------ category_movers
def test_category_movers_ranks_by_absolute_swing():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        account = _account()
        fun = _category("Fun")
        today = timezone.localtime(timezone.now()).date()
        last_month_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        prior_month_start = (last_month_start - timedelta(days=1)).replace(day=1)

        _expense(
            account,
            fun,
            500_00,
            timezone.make_aware(timezone.datetime.combine(last_month_start, timezone.datetime.min.time()))
            + timedelta(days=2),
        )
        _expense(
            account,
            fun,
            100_00,
            timezone.make_aware(timezone.datetime.combine(prior_month_start, timezone.datetime.min.time()))
            + timedelta(days=2),
        )

        result = run_report("category_movers", ReportFilters(currency="USD"))
        row = next(r for r in result.rows if r["label"] == "Fun")
        assert row["amount_minor"] == 500_00
        assert row["previous_minor"] == 100_00
        assert row["change_minor"] == 400_00
        assert row["change_percent"] == 400.0


def test_category_movers_calls_a_brand_new_category_new_rather_than_infinite():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        account = _account()
        fun = _category("Fun")
        today = timezone.localtime(timezone.now()).date()
        last_month_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        _expense(
            account,
            fun,
            300_00,
            timezone.make_aware(timezone.datetime.combine(last_month_start, timezone.datetime.min.time()))
            + timedelta(days=2),
        )

        result = run_report("category_movers", ReportFilters(currency="USD"))
        row = next(r for r in result.rows if r["label"] == "Fun")
        assert row["previous_minor"] == 0
        # Dividing by a zero baseline would be an infinite percentage increase.
        assert row["change_percent"] is None
