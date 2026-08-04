"""The Financial Review: the advisor's sit-down, composed from real selectors.

What matters most here is composition honesty — every section traceable to the
module that computed it, completed periods only, and absence rendered as
absence rather than as zeroes wearing authority.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from apps.finance import services as finance_services
from apps.finance.models import AccountType, CategoryKind
from apps.intelligence import review
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db

AS_OF = date(2026, 8, 4)


# ------------------------------------------------------------------ periods
def test_the_default_period_is_the_last_complete_month():
    period = review.parse_period(None, as_of=AS_OF)
    assert period.start == date(2026, 7, 1)
    assert period.end == date(2026, 7, 31)
    assert period.label == "July 2026"


def test_a_quarter_parses_to_its_calendar_bounds():
    period = review.parse_period("2026-Q1", as_of=AS_OF)
    assert (period.start, period.end) == (date(2026, 1, 1), date(2026, 3, 31))
    assert period.label == "Q1 2026"


def test_an_unfinished_period_is_refused():
    """A review of a month in progress would present half-formed figures with
    the authority of a document — the dashboard covers the present tense."""
    with pytest.raises(review.ReviewError, match="isn't finished"):
        review.parse_period("2026-08", as_of=AS_OF)
    with pytest.raises(review.ReviewError):
        review.parse_period("2026-Q3", as_of=AS_OF)


def test_gibberish_periods_fail_with_the_expected_shape_named():
    with pytest.raises(review.ReviewError, match="YYYY-MM or YYYY-Qn"):
        review.parse_period("last tuesday", as_of=AS_OF)


# ------------------------------------------------------------- composition
def _seed(months_of_history: int = 3):
    account = finance_services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency="USD", opening_balance_minor=1_000_000
    )
    salary = finance_services.create_category(name="Salary", kind=CategoryKind.INCOME, currency="USD")
    groceries = finance_services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
    dining = finance_services.create_category(name="Dining out", kind=CategoryKind.EXPENSE, currency="USD")
    for n in range(1, months_of_history + 1):
        month = AS_OF.month - n
        year = AS_OF.year
        while month <= 0:
            month, year = month + 12, year - 1
        at = datetime(year, month, 15, 12, tzinfo=UTC)
        finance_services.record_income(
            financial_account=account, category=salary, amount_minor=500_000, occurred_at=at
        )
        finance_services.record_expense(
            financial_account=account, category=groceries, amount_minor=200_000, occurred_at=at
        )
        # Dining doubles in the most recent month — the mover the review
        # exists to point at.
        finance_services.record_expense(
            financial_account=account,
            category=dining,
            amount_minor=100_000 if n > 1 else 200_000,
            occurred_at=at,
        )
    return account


def test_the_review_reports_the_period_cashflow():
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        _seed()
        document = review.compose(period_raw="2026-07", as_of=AS_OF)

    cashflow = document.sections["cashflow"]
    assert cashflow["inflow_minor"] == 500_000
    assert cashflow["outflow_minor"] == 400_000
    assert cashflow["savings_rate_pct"] == 20.0
    assert cashflow["previous_savings_rate_pct"] == 40.0


def test_movers_are_ranked_by_absolute_delta_not_percentage():
    """A 400% jump in a tiny category is trivia; the absolute shillings moved
    are the story. Dining +100k must lead the increases."""
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        _seed()
        document = review.compose(period_raw="2026-07", as_of=AS_OF)

    increases = document.sections["movers"]["increases"]
    assert increases[0]["category_name"] == "Dining out"
    assert increases[0]["delta_minor"] == 100_000


def test_absent_domains_render_as_absence_not_zeroes():
    """No debts and no goals must appear as nothing-to-report, never as a
    zero-balance debt section wearing the authority of a document."""
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        _seed()
        document = review.compose(period_raw="2026-07", as_of=AS_OF)

    assert document.sections["debt"] is None
    assert document.sections["goals"] == []


def test_net_worth_is_marked_approximate():
    """The report reconstructs history from flows — exact today, approximate
    backwards. The review must inherit the caveat, not launder it away."""
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        _seed()
        document = review.compose(period_raw="2026-07", as_of=AS_OF)

    assert document.sections["net_worth"]["approximate"] is True


def test_the_fi_section_degrades_to_none_on_thin_history():
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        _seed(months_of_history=1)
        document = review.compose(period_raw="2026-07", as_of=AS_OF)

    assert document.sections["fi"] is None


# ------------------------------------------------------------------- API
def test_api_returns_the_document(tenant_context):
    membership, client = tenant_context
    with tenant_scope(membership.tenant_id):
        _seed()

    body = client.get("/api/v1/intelligence/review/?period=2026-07").data
    assert body["period"]["label"] == "July 2026"
    assert body["sections"]["cashflow"]["inflow_minor"] == 500_000
    assert "actions" in body["sections"]


def test_api_refuses_an_unfinished_period_with_a_readable_reason(tenant_context):
    _, client = tenant_context
    resp = client.get("/api/v1/intelligence/review/?period=2099-01")
    assert resp.status_code == 400
    assert "finished" in resp.data["detail"]


# ------------------------------------------------------- subscriptions & fees
def test_the_fee_audit_annualises_standing_orders():
    """1,200/mo does not feel like a decision; 14,400/yr does. The section
    exists to perform that conversion."""
    from apps.finance.recurring import create_recurring_transaction

    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        account = _seed()
        streaming = finance_services.create_category(
            name="Streaming", kind=CategoryKind.EXPENSE, currency="USD"
        )
        create_recurring_transaction(
            txn_type="expense",
            financial_account=account,
            category=streaming,
            amount_minor=1_200,
            currency="USD",
            frequency="monthly",
            starts_on=AS_OF,
            memo="Streaming service",
        )
        document = review.compose(period_raw="2026-07", as_of=AS_OF)

    section = document.sections["subscriptions"]
    assert section is not None
    assert section["count"] == 1
    assert section["annual_total_minor"] == 14_400
    assert section["top"][0]["name"] == "Streaming service"


def test_no_standing_orders_and_no_rises_is_absence_not_a_zero():
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        _seed()
        document = review.compose(period_raw="2026-07", as_of=AS_OF)

    assert document.sections["subscriptions"] is None


def test_price_rises_reuse_the_coachs_definition():
    """Two definitions of "price rise" in one product would eventually
    disagree in public. The section must carry the coach's comparison, not a
    second one — pinned structurally rather than re-tested behaviourally,
    since the coach's own tests already cover the comparison."""
    from pathlib import Path

    source = Path("apps/intelligence/review.py").read_text()
    section = source[source.index("def _subscriptions_section") :]
    assert "_merchant_changes" in section.split("def _fi_section")[0]
