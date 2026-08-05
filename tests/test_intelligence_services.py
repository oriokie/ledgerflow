"""Intelligence service tests (DB + RLS): the advisory suggestion lifecycle and
rule-based automation, applied through the real finance service layer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from django.test import override_settings

from apps.finance import services as finance_services
from apps.finance.models import AccountType, CategoryKind
from apps.finance.payees import create_payee
from apps.intelligence import services
from apps.intelligence.models import AutomationRule, CategorizationSuggestion, SuggestionStatus
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


def _now():
    return datetime.now(UTC)


def _seed():
    checking = finance_services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency="USD"
    )
    groceries = finance_services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
    dining = finance_services.create_category(name="Dining out", kind=CategoryKind.EXPENSE, currency="USD")
    misc = finance_services.create_category(name="Uncategorized", kind=CategoryKind.EXPENSE, currency="USD")
    return checking, groceries, dining, misc


def _uncategorized_expense(checking, placeholder, *, amount_minor, payee):
    """record_expense requires a category; to get an uncategorized transaction
    (the state the AI categorizes) we post through a placeholder expense
    category then clear it via the finance service."""
    txn = finance_services.record_expense(
        financial_account=checking,
        category=placeholder,
        amount_minor=amount_minor,
        occurred_at=_now(),
        payee=payee,
    )
    return finance_services.update_transaction(txn=txn, category=None)


# --------------------------------------------------------------- suggestion flow
def test_suggest_stores_pending_advisory_suggestion(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _dining, misc = _seed()
        payee = create_payee(name="Whole Foods Market")
        # give the payee history so merchant-memory can suggest groceries
        finance_services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=5000,
            occurred_at=_now(),
            payee=payee,
        )
        txn = _uncategorized_expense(checking, groceries, amount_minor=4000, payee=payee)
        suggestion = services.suggest_category(txn)
        assert suggestion.status == SuggestionStatus.PENDING
        assert suggestion.suggested_category_id == groceries.id
        assert suggestion.provider == "RuleBasedCategorizer"
        assert suggestion.confidence >= 0.9
        # advisory: the transaction itself is NOT yet categorized
        txn.refresh_from_db()
        assert txn.category_id is None


def test_accept_suggestion_applies_via_finance_service(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _dining, misc = _seed()
        payee = create_payee(name="Whole Foods")
        finance_services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=5000,
            occurred_at=_now(),
            payee=payee,
        )
        txn = _uncategorized_expense(checking, groceries, amount_minor=4000, payee=payee)
        suggestion = services.suggest_category(txn)
        services.accept_suggestion(suggestion)

        txn.refresh_from_db()
        suggestion.refresh_from_db()
        assert txn.category_id == groceries.id
        assert suggestion.status == SuggestionStatus.ACCEPTED
        assert suggestion.decided_at is not None


def test_reject_suggestion_leaves_transaction_uncategorized(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _dining, misc = _seed()
        payee = create_payee(name="Whole Foods")
        finance_services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=5000,
            occurred_at=_now(),
            payee=payee,
        )
        txn = _uncategorized_expense(checking, groceries, amount_minor=4000, payee=payee)
        suggestion = services.suggest_category(txn)
        services.reject_suggestion(suggestion)
        txn.refresh_from_db()
        suggestion.refresh_from_db()
        assert txn.category_id is None
        assert suggestion.status == SuggestionStatus.REJECTED


@override_settings(INTELLIGENCE_AUTO_ACCEPT_CONFIDENCE=0.9)
def test_high_confidence_auto_applies(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _dining, misc = _seed()
        payee = create_payee(name="Whole Foods")
        finance_services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=5000,
            occurred_at=_now(),
            payee=payee,
        )
        txn = _uncategorized_expense(checking, groceries, amount_minor=4000, payee=payee)
        # merchant-memory yields 0.95 >= 0.9 threshold -> auto-applied
        services.suggest_and_maybe_apply(txn)
        txn.refresh_from_db()
        assert txn.category_id == groceries.id


@override_settings(INTELLIGENCE_AUTO_ACCEPT_CONFIDENCE=0.99)
def test_below_threshold_stays_pending(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _dining, misc = _seed()
        payee = create_payee(name="Whole Foods")
        finance_services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=5000,
            occurred_at=_now(),
            payee=payee,
        )
        txn = _uncategorized_expense(checking, groceries, amount_minor=4000, payee=payee)
        suggestion = services.suggest_and_maybe_apply(txn)  # 0.95 < 0.99
        txn.refresh_from_db()
        assert txn.category_id is None
        assert suggestion.status == SuggestionStatus.PENDING


# --------------------------------------------------------------- automation
def test_automation_rule_sets_category_and_tag(tenant_id):
    with tenant_scope(tenant_id):
        checking, _groceries, dining, misc = _seed()
        payee = create_payee(name="Blue Bottle Coffee")
        AutomationRule.objects.create(
            name="Coffee is dining",
            priority=10,
            conditions={"all": [{"field": "payee_normalized", "op": "contains", "value": "coffee"}]},
            actions=[
                {"type": "set_category", "category_id": str(dining.id)},
                {"type": "add_tag", "name": "coffee-run"},
            ],
        )
        txn = _uncategorized_expense(checking, misc, amount_minor=480, payee=payee)
        effects = services.run_automation(txn)
        txn.refresh_from_db()
        assert txn.category_id == dining.id
        assert {link.tag.name for link in txn.tag_links.all()} == {"coffee-run"}
        assert any("category" in e for e in effects)


def test_automation_no_match_no_effect(tenant_id):
    with tenant_scope(tenant_id):
        checking, _groceries, dining, misc = _seed()
        AutomationRule.objects.create(
            name="Netflix only",
            priority=10,
            conditions={"all": [{"field": "payee_normalized", "op": "contains", "value": "netflix"}]},
            actions=[{"type": "set_category", "category_id": str(dining.id)}],
        )
        payee = create_payee(name="Whole Foods")
        txn = _uncategorized_expense(checking, misc, amount_minor=4000, payee=payee)
        effects = services.run_automation(txn)
        txn.refresh_from_db()
        assert effects == []
        assert txn.category_id is None


def test_automation_priority_and_stop(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, dining, misc = _seed()
        payee = create_payee(name="Corner Cafe")
        # high-priority rule stops processing; lower rule must not run
        AutomationRule.objects.create(
            name="Cafe -> dining, stop",
            priority=10,
            conditions={"all": [{"field": "payee_normalized", "op": "contains", "value": "cafe"}]},
            actions=[{"type": "set_category", "category_id": str(dining.id)}],
            stop_processing=True,
        )
        AutomationRule.objects.create(
            name="Everything -> groceries",
            priority=20,
            conditions={"any": [{"field": "amount_minor", "op": "lte", "value": 0}]},
            actions=[{"type": "set_category", "category_id": str(groceries.id)}],
        )
        txn = _uncategorized_expense(checking, misc, amount_minor=600, payee=payee)
        services.run_automation(txn)
        txn.refresh_from_db()
        assert txn.category_id == dining.id  # first rule won and stopped the chain


def test_suggestions_are_tenant_isolated():
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    with tenant_scope(tenant_a):
        checking, groceries, _dining, misc = _seed()
        payee = create_payee(name="Whole Foods")
        finance_services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=5000,
            occurred_at=_now(),
            payee=payee,
        )
        txn = _uncategorized_expense(checking, groceries, amount_minor=4000, payee=payee)
        services.suggest_category(txn)
        assert CategorizationSuggestion.objects.count() == 1
    with tenant_scope(tenant_b):
        # RLS: tenant B sees none of tenant A's suggestions
        assert CategorizationSuggestion.objects.count() == 0


# --------------------------------------------------------------- health inputs
def test_a_workspace_with_income_but_no_spending_has_no_measurable_savings_rate():
    """The reported bug: a 100% savings rate with nothing actually saved.

    `(income - expense) / income` returns 1.0 whenever expenses are zero — and
    for a workspace that has only ever recorded a payslip, zero expenses means
    "we haven't been told", not "nothing was spent". Same for the emergency
    fund, which used to divide assets by `expense or 1` and score full marks
    against a denominator of one cent.
    """
    from apps.intelligence.selectors import build_health_inputs

    with tenant_scope(uuid.uuid4()):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        salary = finance_services.create_category(
            name="Salary", kind=CategoryKind.INCOME, currency="USD"
        )
        # Two completed months of salary, no spending recorded at all.
        for month in (5, 6):
            finance_services.record_income(
                financial_account=checking,
                category=salary,
                amount_minor=500_000,
                occurred_at=datetime(2026, month, 1, tzinfo=UTC),
            )

        inputs = build_health_inputs(as_of=datetime(2026, 7, 15, tzinfo=UTC).date())

    assert inputs.savings_rate is None, "no spending on record means the rate is unmeasured"
    assert inputs.essential_coverage_months is None, "no spending means no runway to measure"
    assert inputs.budget_adherence is None, "no budgets means nothing to adhere to"


def test_savings_rate_is_measured_once_both_halves_exist():
    """With real income and real spending, the rate is a genuine measurement."""
    from apps.intelligence.selectors import build_health_inputs

    with tenant_scope(uuid.uuid4()):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        salary = finance_services.create_category(
            name="Salary", kind=CategoryKind.INCOME, currency="USD"
        )
        groceries = finance_services.create_category(
            name="Groceries", kind=CategoryKind.EXPENSE, currency="USD"
        )
        finance_services.record_income(
            financial_account=checking,
            category=salary,
            amount_minor=1_000_000,
            occurred_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        for day in (3, 10, 17, 24):
            finance_services.record_expense(
                financial_account=checking,
                category=groceries,
                amount_minor=50_000,
                occurred_at=datetime(2026, 6, day, tzinfo=UTC),
            )

        inputs = build_health_inputs(as_of=datetime(2026, 7, 15, tzinfo=UTC).date())

    # Kept 800,000 of 1,000,000.
    assert inputs.savings_rate == 0.8
    # 800,000 of liquid cash against 200,000 spent over a 3-month window
    # (66,666.67 a month) is about 12 months of runway.
    assert inputs.essential_coverage_months == pytest.approx(12.0, abs=0.1)


def test_the_current_partial_month_cannot_inflate_the_savings_rate():
    """Month-to-date was the other half of the bug.

    Salary lands on the 1st and spending accumulates over the following weeks,
    so a month-to-date rate read near 100% every month and fell as the month
    went on. The window is whole months only, so today's payslip changes
    nothing.
    """
    from apps.intelligence.selectors import build_health_inputs

    as_of = datetime(2026, 7, 3, tzinfo=UTC).date()
    with tenant_scope(uuid.uuid4()):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        salary = finance_services.create_category(
            name="Salary", kind=CategoryKind.INCOME, currency="USD"
        )
        groceries = finance_services.create_category(
            name="Groceries", kind=CategoryKind.EXPENSE, currency="USD"
        )
        finance_services.record_income(
            financial_account=checking,
            category=salary,
            amount_minor=400_000,
            occurred_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        for day in (5, 12, 19):
            finance_services.record_expense(
                financial_account=checking,
                category=groceries,
                amount_minor=100_000,
                occurred_at=datetime(2026, 6, day, tzinfo=UTC),
            )
        before = build_health_inputs(as_of=as_of).savings_rate

        # July's salary arrives, and nothing has been spent out of it yet.
        finance_services.record_income(
            financial_account=checking,
            category=salary,
            amount_minor=400_000,
            occurred_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
        after = build_health_inputs(as_of=as_of).savings_rate

    assert before == 0.25
    assert after == before, "an unfinished month must not move a rate"
