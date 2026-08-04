"""What-if scenarios: the modelling session, against the real projections.

The load-bearing property: baseline and scenario run the same arithmetic, so
the comparison cannot be flattered by a hand-derived adjustment. And the FI
leg must show the double effect of a spending cut — more saved, smaller
target — which is the one thing an advisor's modelling session teaches that
people do not already intuit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from django.utils import timezone

from apps.analytics import scenarios
from apps.finance import services as finance_services
from apps.finance.models import AccountType, CategoryKind
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return uuid.uuid4()


def _month_back(n: int) -> date:
    today = timezone.localdate()
    month, year = today.month - n, today.year
    while month <= 0:
        month, year = month + 12, year - 1
    return date(year, month, 15)


def _seed(income=500_000, spend=300_000, opening=1_000_000):
    account = finance_services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency="USD", opening_balance_minor=opening
    )
    salary = finance_services.create_category(name="Salary", kind=CategoryKind.INCOME, currency="USD")
    groceries = finance_services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
    for n in range(1, 7):
        when = _month_back(n)
        at = datetime(when.year, when.month, when.day, 12, tzinfo=UTC)
        finance_services.record_income(
            financial_account=account, category=salary, amount_minor=income, occurred_at=at
        )
        finance_services.record_expense(
            financial_account=account, category=groceries, amount_minor=spend, occurred_at=at
        )
    return account


def test_a_null_scenario_equals_the_baseline(tenant):
    """Zero deltas through the scenario path must reproduce the baseline
    exactly — any drift means the two legs run different arithmetic, which is
    precisely the bug rule one exists to prevent."""
    with tenant_scope(tenant):
        _seed()
        result = scenarios.preview()

    assert result.scenario == result.baseline


def test_extra_income_raises_the_trough_and_never_lowers_it(tenant):
    with tenant_scope(tenant):
        _seed()
        result = scenarios.preview(monthly_income_delta_minor=100_000)

    assert result.scenario.safe_to_spend_minor >= result.baseline.safe_to_spend_minor


def test_a_rent_rise_can_surface_a_first_negative_the_baseline_did_not_have(tenant):
    """The question people actually bring: "can I afford this flat?" — the
    honest answer sometimes being a date their balance now crosses zero."""
    with tenant_scope(tenant):
        # The seeded history itself moves the balance: 120k opening plus six
        # months of (500k in, 300k out) leaves ~1.32M today. The rise has to
        # outrun that within the 35-day window to surface a crossing.
        _seed(opening=120_000)
        result = scenarios.preview(monthly_expense_delta_minor=1_500_000)

    assert result.baseline.first_negative_on is None
    assert result.scenario.first_negative_on is not None
    assert result.scenario.safe_to_spend_minor == 0


def test_a_spending_cut_counts_twice_for_independence(tenant):
    """Cut 100k/mo: more saved every month AND the number itself shrinks by
    the cut times twelve over the withdrawal rate. Both must show."""
    with tenant_scope(tenant):
        _seed()
        result = scenarios.preview(monthly_expense_delta_minor=-100_000)

    assert result.scenario.fi_number_minor < result.baseline.fi_number_minor
    assert result.scenario.fi_years < result.baseline.fi_years
    # The number moves by exactly the arithmetic, not an approximation of it.
    expected_shrink = round(100_000 * 12 / 0.04)
    assert result.baseline.fi_number_minor - result.scenario.fi_number_minor == expected_shrink
    assert any("count twice" in note for note in result.notes)


def test_the_smoothing_caveat_is_always_stated(tenant):
    with tenant_scope(tenant):
        _seed()
        result = scenarios.preview(monthly_expense_delta_minor=50_000)

    assert any("evenly across the projection" in note for note in result.notes)


def test_no_liquid_accounts_degrades_the_cashflow_leg_not_the_whole_answer(tenant):
    with tenant_scope(tenant):
        result = scenarios.preview(monthly_income_delta_minor=100_000)

    assert result.baseline.safe_to_spend_minor is None
    assert any("No liquid accounts" in note for note in result.notes)


# ------------------------------------------------------------------- API
def test_api_previews_a_scenario(tenant_context):
    membership, client = tenant_context
    with tenant_scope(membership.tenant_id):
        _seed()

    body = client.post(
        "/api/v1/analytics/scenarios/preview/",
        {"monthly_expense_delta_minor": -100_000},
        format="json",
    ).data
    assert body["scenario"]["fi_years"] < body["baseline"]["fi_years"]
    assert body["notes"]


def test_api_rejects_a_non_numeric_delta_with_a_readable_reason(tenant_context):
    _, client = tenant_context
    resp = client.post(
        "/api/v1/analytics/scenarios/preview/",
        {"monthly_expense_delta_minor": "ten grand"},
        format="json",
    )
    assert resp.status_code == 400
    assert "integer amount" in resp.data["detail"]
