"""Financial independence: honest arithmetic about when work becomes optional.

The properties that matter most are the honesty ones: spending-derived rather
than aspiration-derived, a band rather than one falsely precise year, and
"never at this pace" answered with the actionable inverse instead of a shrug.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from django.utils import timezone

from apps.analytics import fi
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


def _workspace(months=6, income=500_000, spend=300_000, opening=2_000_000):
    account = finance_services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency="USD", opening_balance_minor=opening
    )
    salary_cat = finance_services.create_category(name="Salary", kind=CategoryKind.INCOME, currency="USD")
    groceries = finance_services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
    for n in range(1, months + 1):
        when = _month_back(n)
        at = datetime(when.year, when.month, when.day, 12, tzinfo=UTC)
        if income:
            finance_services.record_income(
                financial_account=account, category=salary_cat, amount_minor=income, occurred_at=at
            )
        if spend:
            finance_services.record_expense(
                financial_account=account, category=groceries, amount_minor=spend, occurred_at=at
            )
    return account


# ------------------------------------------------------------- the arithmetic
def test_the_fi_number_is_spending_derived():
    """Independence must cover what is actually spent — 300k/mo at a 4%
    withdrawal is 90M, regardless of what anyone earns or wishes."""
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        _workspace(spend=300_000)
        projection = fi.project()

    assert projection.monthly_spending_minor == 300_000
    assert projection.fi_number_minor == round(300_000 * 12 / 0.04)


def test_the_answer_is_a_band_not_a_year():
    """4% vs 6% real return is routinely a decade of someone's life. One
    figure would be a lie of precision; three with assumptions attached is a
    forecast a person can argue with."""
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        _workspace()
        projection = fi.project()

    returns = [point.real_return for point in projection.band]
    assert returns == [0.04, 0.05, 0.06]
    years = [point.years for point in projection.band]
    assert all(y is not None for y in years)
    # Higher assumed return can never mean a later date.
    assert sorted(years, reverse=True) == years


def test_a_saver_reaches_the_number_and_a_bigger_pot_reaches_it_sooner():
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    with tenant_scope(tenant_a):
        _workspace(opening=2_000_000)
        modest = fi.project()
    with tenant_scope(tenant_b):
        _workspace(opening=50_000_000)
        substantial = fi.project()

    middle = len(modest.band) // 2
    assert substantial.band[middle].years < modest.band[middle].years
    assert substantial.progress_pct > modest.progress_pct


def test_never_at_current_pace_answers_with_the_required_monthly():
    """An advisor who said "never" and stopped would be fired. The projection
    converts the dead end into the monthly saving that reaches the number in
    fifteen years."""
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        _workspace(income=300_000, spend=300_000, opening=100_000)  # saves nothing
        projection = fi.project()

    assert projection.never_at_current_pace is True
    assert projection.required_monthly_for_horizon_minor is not None
    assert projection.required_monthly_for_horizon_minor > 0

    # And the offered figure must actually work: saving it for the horizon at
    # the middle return reaches the number.
    months = fi._months_to_target(
        projection.net_worth_minor,
        projection.required_monthly_for_horizon_minor,
        projection.fi_number_minor,
        fi.RETURN_BAND[len(fi.RETURN_BAND) // 2],
    )
    assert months is not None
    assert months <= fi.FALLBACK_HORIZON_YEARS * 12 + 1


def test_already_there_reads_zero_years_not_an_error():
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        _workspace(spend=100_000, opening=100_000 * 400)  # pot far beyond the number
        projection = fi.project()

    assert all(point.years == 0.0 for point in projection.band)
    assert projection.progress_pct >= 100


# ---------------------------------------------------------------- the honesty
def test_thin_history_refuses_rather_than_guessing():
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        _workspace(months=1)
        with pytest.raises(fi.NotEnoughHistoryError):
            fi.project()


def test_partial_history_is_flagged_in_the_caveats():
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        _workspace(months=3)
        projection = fi.project()

    assert projection.months_measured == 3
    assert any("3 complete months" in caveat for caveat in projection.caveats)


def test_income_free_history_is_flagged_not_silently_zeroed():
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        _workspace(income=0, opening=10_000_000)
        projection = fi.project()

    assert projection.monthly_savings_minor == 0
    assert any("saving rate is treated as zero" in caveat for caveat in projection.caveats)


# ---------------------------------------------------------------------- API
def test_api_returns_the_projection(tenant_context):
    membership, client = tenant_context
    with tenant_scope(membership.tenant_id):
        _workspace()

    body = client.get("/api/v1/analytics/financial-independence/").data
    assert body["fi_number_minor"] > 0
    assert len(body["band"]) == 3
    assert body["swr"] == 0.04


def test_api_with_no_history_is_a_404_with_an_explanation(tenant_context):
    _, client = tenant_context
    resp = client.get("/api/v1/analytics/financial-independence/")
    assert resp.status_code == 404
    assert "months" in resp.data["detail"]
