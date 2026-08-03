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
