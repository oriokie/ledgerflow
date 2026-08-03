"""Quick Add — fast entry that still goes through the normal posting path.

The property tested hardest: Quick Add's category inference reads the exact
same learned store the automation engine's review queue does, so the two
surfaces can never disagree about what a merchant "usually is".
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.finance import quick_add
from apps.finance import services as finance_services
from apps.finance.models import Transaction
from apps.finance.payees import get_or_create_payee
from apps.finance.models import AccountType, CategoryKind
from apps.intelligence import automation_services
from apps.ledger.models import LedgerLine
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return uuid.uuid4()


def _account(name="Checking", currency="USD", opening=500_000):
    return finance_services.create_financial_account(
        name=name, account_type=AccountType.CHECKING, currency=currency, opening_balance_minor=opening
    )


def _category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD"):
    return finance_services.create_category(name=name, kind=kind, currency=currency)


def test_a_bare_amount_and_merchant_is_enough_to_post(tenant):
    with tenant_scope(tenant):
        _account()
        result = quick_add.quick_add(amount_minor=1_250, merchant="Corner Shop")
        assert result.transaction.amount_minor == -1_250
        assert result.transaction.payee.name == "Corner Shop"


def test_the_amount_must_be_positive(tenant):
    with tenant_scope(tenant):
        _account()
        with pytest.raises(quick_add.QuickAddError):
            quick_add.quick_add(amount_minor=0, merchant="Shop")


def test_a_blank_merchant_is_refused(tenant):
    with tenant_scope(tenant):
        _account()
        with pytest.raises(quick_add.QuickAddError):
            quick_add.quick_add(amount_minor=1_000, merchant="   ")


def test_without_any_account_quick_add_fails_clearly(tenant):
    with tenant_scope(tenant):
        with pytest.raises(quick_add.QuickAddError, match="Add an account"):
            quick_add.quick_add(amount_minor=1_000, merchant="Shop")


def test_the_account_defaults_to_the_most_recently_used_one(tenant):
    with tenant_scope(tenant):
        old = _account(name="Old Card")
        new = _account(name="New Card")
        finance_services.record_expense(
            financial_account=new,
            category=_category(),
            amount_minor=500,
            occurred_at=timezone.now(),
        )
        result = quick_add.quick_add(amount_minor=1_000, merchant="Shop")
        assert result.transaction.financial_account_id == new.id
        assert result.account_was_inferred is True


def test_an_explicit_account_is_never_overridden(tenant):
    with tenant_scope(tenant):
        default_account = _account(name="Default")
        finance_services.record_expense(
            financial_account=default_account, category=_category(), amount_minor=500,
            occurred_at=timezone.now(),
        )
        chosen = _account(name="Chosen")
        result = quick_add.quick_add(
            amount_minor=1_000, merchant="Shop", financial_account=chosen
        )
        assert result.transaction.financial_account_id == chosen.id
        assert result.account_was_inferred is False


def test_category_is_inferred_from_the_same_store_the_automation_engine_reads(tenant):
    """Quick Add and the review queue can never disagree about what a merchant
    usually is, because both read `merchant_stats()`."""
    with tenant_scope(tenant):
        account = _account()
        groceries = _category(name="Groceries")
        payee, _ = get_or_create_payee(name="Corner Shop")
        for _ in range(3):
            txn = finance_services.record_expense(
                financial_account=account, category=groceries, amount_minor=2_000,
                occurred_at=timezone.now(), payee=payee,
            )
            automation_services.learn_from_transaction(txn)

        result = quick_add.quick_add(amount_minor=1_500, merchant="Corner Shop")
        assert result.transaction.category_id == groceries.id
        assert result.category_was_inferred is True
        assert result.category_confidence >= 0.6


def test_a_never_seen_merchant_falls_back_to_uncategorised(tenant):
    with tenant_scope(tenant):
        _account()
        result = quick_add.quick_add(amount_minor=1_000, merchant="Brand New Place")
        assert result.category_was_inferred is False
        assert result.transaction.category.name == "Uncategorized"


def test_a_split_history_does_not_force_a_guess(tenant):
    """A coin toss presented as a recommendation is worse than silence — the
    same rule the automation engine's own category suggester follows."""
    with tenant_scope(tenant):
        account = _account()
        a = _category(name="A")
        b = _category(name="B", currency="USD")
        for category in (a, b, a, b):
            txn = finance_services.record_expense(
                financial_account=account, category=category, amount_minor=1_000,
                occurred_at=timezone.now(),
            )
            automation_services.learn_from_transaction(txn)

        result = quick_add.quick_add(amount_minor=900, merchant="Corner Shop")
        assert result.category_was_inferred is False


def test_an_explicit_category_is_never_overridden_by_inference(tenant):
    with tenant_scope(tenant):
        account = _account()
        groceries = _category(name="Groceries")
        household = _category(name="Household")
        for _ in range(3):
            txn = finance_services.record_expense(
                financial_account=account, category=groceries, amount_minor=1_000,
                occurred_at=timezone.now(),
            )
            automation_services.learn_from_transaction(txn)

        result = quick_add.quick_add(
            amount_minor=800, merchant="Corner Shop", category=household
        )
        assert result.transaction.category_id == household.id
        assert result.category_was_inferred is False


def test_an_explicitly_typed_category_teaches_the_learning_store(tenant):
    """A category the user picked directly is a real signal, same as any other
    categorised transaction."""
    with tenant_scope(tenant):
        from apps.intelligence.models import MerchantProfile

        account = _account()
        category = _category()
        quick_add.quick_add(
            amount_minor=1_000, merchant="Fresh Merchant", financial_account=account,
            category=category,
        )
        assert MerchantProfile.objects.filter(display_name="Fresh Merchant").exists()


def test_an_inferred_category_does_not_double_count_its_own_evidence(tenant):
    """Learning from a guess would let the engine's own inference vote for
    itself, growing artificially more confident with every quick add."""
    with tenant_scope(tenant):
        from apps.intelligence.models import MerchantProfile

        account = _account()
        groceries = _category(name="Groceries")
        payee, _ = get_or_create_payee(name="Corner Shop")
        for _ in range(3):
            txn = finance_services.record_expense(
                financial_account=account, category=groceries, amount_minor=1_000,
                occurred_at=timezone.now(), payee=payee,
            )
            automation_services.learn_from_transaction(txn)
        before = MerchantProfile.objects.get(display_name__iexact="Corner Shop").category_counts

        quick_add.quick_add(amount_minor=1_200, merchant="Corner Shop")

        after = MerchantProfile.objects.get(display_name__iexact="Corner Shop").category_counts
        assert after == before


def test_income_posts_through_the_income_path(tenant):
    with tenant_scope(tenant):
        _account()
        result = quick_add.quick_add(amount_minor=50_000, merchant="Employer", is_income=True)
        assert result.transaction.amount_minor == 50_000
        assert result.transaction.category.kind == CategoryKind.INCOME


def test_quick_add_posts_a_balanced_ledger_entry(tenant):
    with tenant_scope(tenant):
        _account()
        before = LedgerLine.objects.count()
        result = quick_add.quick_add(amount_minor=1_000, merchant="Shop")
        lines = list(LedgerLine.objects.filter(entry=result.transaction.journal_entry))
        assert len(lines) == 2
        assert LedgerLine.objects.count() == before + 2


def test_recent_merchants_are_ordered_by_recency_not_alphabetically(tenant):
    with tenant_scope(tenant):
        account = _account()
        category = _category()
        now = timezone.now()
        for name, days_ago in (("Zebra Shop", 5), ("Apple Store", 1)):
            payee, _ = get_or_create_payee(name=name)
            finance_services.record_expense(
                financial_account=account, category=category, amount_minor=500,
                occurred_at=now - timedelta(days=days_ago), payee=payee,
            )
        merchants = quick_add.recent_merchants(limit=5)
        assert merchants[0] == "Apple Store"


# ---------------------------------------------------------------------- API
def test_api_quick_add(tenant_context):
    _, client = tenant_context
    client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD",
         "opening_balance_minor": 500_000},
        format="json",
    )
    resp = client.post(
        "/api/v1/finance/quick-add/",
        {"amount_minor": 1_250, "merchant": "Corner Shop"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["account_was_inferred"] is True
    assert resp.data["category_was_inferred"] is False


def test_api_quick_add_rejects_a_zero_amount(tenant_context):
    _, client = tenant_context
    resp = client.post(
        "/api/v1/finance/quick-add/", {"amount_minor": 0, "merchant": "Shop"}, format="json"
    )
    assert resp.status_code == 400


def test_api_recent_merchants(tenant_context):
    _, client = tenant_context
    client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD",
         "opening_balance_minor": 500_000},
        format="json",
    )
    client.post(
        "/api/v1/finance/quick-add/", {"amount_minor": 500, "merchant": "Corner Shop"}, format="json"
    )
    merchants = client.get("/api/v1/finance/quick-add/recent-merchants/").data
    assert "Corner Shop" in merchants


# ---------------------------------------------------------------- idempotency
def test_replaying_the_same_idempotency_key_never_double_posts(tenant):
    """The property the offline queue depends on: a submission replayed after
    its response was lost — sent, but the confirmation never arrived — must
    land on the same journal entry rather than post twice."""
    with tenant_scope(tenant):
        _account()
        key = "quick-add:client-generated-uuid-1"
        first = quick_add.quick_add(amount_minor=1_500, merchant="Corner Shop", idempotency_key=key)
        second = quick_add.quick_add(amount_minor=1_500, merchant="Corner Shop", idempotency_key=key)

        assert first.transaction.id == second.transaction.id
        assert Transaction.objects.count() == 1


def test_different_idempotency_keys_post_separately(tenant):
    with tenant_scope(tenant):
        _account()
        quick_add.quick_add(amount_minor=1_000, merchant="Shop", idempotency_key="key-a")
        quick_add.quick_add(amount_minor=1_000, merchant="Shop", idempotency_key="key-b")
        assert Transaction.objects.count() == 2


def test_api_quick_add_replay_is_idempotent(tenant_context):
    _, client = tenant_context
    client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD",
         "opening_balance_minor": 500_000},
        format="json",
    )
    payload = {"amount_minor": 1_250, "merchant": "Corner Shop", "idempotency_key": "offline-1"}
    first = client.post("/api/v1/finance/quick-add/", payload, format="json")
    second = client.post("/api/v1/finance/quick-add/", payload, format="json")

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.data["transaction_id"] == second.data["transaction_id"]
