"""Automation services: scanning, review, and the learning loop.

The properties pinned hardest are the ones that decide whether someone keeps
the feature switched on:

  * a dismissed suggestion never comes back;
  * nothing writes to the ledger;
  * a rejection teaches the engine rather than being discarded.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.finance import services as finance_services
from apps.finance.import_csv import import_transactions_csv
from apps.finance.models import AccountType, CategoryKind
from apps.finance.payees import get_or_create_payee
from apps.intelligence import automation_services as auto
from apps.intelligence import detect
from apps.intelligence.models import (
    AutomationSuggestion,
    MerchantProfile,
    ReviewStatus,
    SuggestionKind,
)
from apps.ledger.models import LedgerLine
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return uuid.uuid4()


def _setup():
    checking = finance_services.create_financial_account(
        name="Checking",
        account_type=AccountType.CHECKING,
        currency="USD",
        opening_balance_minor=1_000_000,
    )
    savings = finance_services.create_financial_account(
        name="Savings", account_type=AccountType.SAVINGS, currency="USD"
    )
    groceries = finance_services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
    dining = finance_services.create_category(name="Dining", kind=CategoryKind.EXPENSE, currency="USD")
    return checking, savings, groceries, dining


def _import_uncategorised(account, *, description, amount_major):
    """Import an uncategorised transaction.

    CSV import is the real path by which uncategorised rows arrive — the
    importer explicitly defers to "the auto-categorization pipeline", which is
    this. Constructing one directly would bypass the ledger and test a state
    the product can't actually reach.
    """
    when = timezone.now().date().isoformat()
    csv_text = f"date,amount,description\n{when},-{amount_major:.2f},{description}\n"
    import_transactions_csv(financial_account=account, file_content=csv_text)
    from apps.finance.models import Transaction

    # The importer routes these through a lazily-created "Uncategorized"
    # category, because the ledger needs one for a valid posting.
    return Transaction.objects.filter(category__name__istartswith="Uncategor").order_by("-created_at").first()


def _spend(account, category, amount, *, days_ago=0, payee="Corner Shop"):
    payee_obj, _ = get_or_create_payee(name=payee)
    return finance_services.record_expense(
        financial_account=account,
        category=category,
        amount_minor=amount,
        occurred_at=timezone.now() - timedelta(days=days_ago),
        payee=payee_obj,
    )


# =============================================================================
# Taxonomy consistency
# =============================================================================
def test_model_and_engine_suggestion_kinds_agree():
    """Duplicated because the detector can't import Django — this is what stops
    the two drifting apart."""
    engine = {
        detect.SuggestionKind.CATEGORY,
        detect.SuggestionKind.TRANSFER,
        detect.SuggestionKind.DUPLICATE,
        detect.SuggestionKind.REFUND,
        detect.SuggestionKind.RECURRING,
        detect.SuggestionKind.SPLIT,
        detect.SuggestionKind.INCOME,
    }
    assert engine == set(SuggestionKind.values)


# =============================================================================
# Scanning
# =============================================================================
def test_a_scan_of_an_empty_workspace_finds_nothing(tenant):
    with tenant_scope(tenant):
        result = auto.scan()
        assert result.created == 0
        assert AutomationSuggestion.objects.count() == 0


def test_a_transfer_pair_is_detected_and_persisted(tenant):
    with tenant_scope(tenant):
        checking, savings, _, _ = _setup()
        finance_services.record_transfer(
            from_account=checking,
            to_account=savings,
            amount_minor=50_000,
            occurred_at=timezone.now(),
        )
        auto.scan()

        suggestion = AutomationSuggestion.objects.filter(kind=SuggestionKind.TRANSFER).first()
        assert suggestion is not None
        assert suggestion.confidence >= 0.9
        assert suggestion.reason


def test_scanning_twice_does_not_duplicate_findings(tenant):
    """The scanner runs over overlapping windows; without stable identity every
    run would re-propose everything."""
    with tenant_scope(tenant):
        checking, _, groceries, _ = _setup()
        _spend(checking, groceries, 1_250)
        _spend(checking, groceries, 1_250)

        first = auto.scan()
        before = AutomationSuggestion.objects.count()
        second = auto.scan()

        assert AutomationSuggestion.objects.count() == before
        assert second.created == 0
        assert first.created > 0


def test_a_dismissed_suggestion_never_comes_back(tenant):
    """Overriding a dismissal is how a product teaches people to ignore it."""
    with tenant_scope(tenant):
        checking, _, groceries, _ = _setup()
        _spend(checking, groceries, 1_250)
        _spend(checking, groceries, 1_250)
        auto.scan()

        suggestion = AutomationSuggestion.objects.filter(kind=SuggestionKind.DUPLICATE).first()
        auto.reject(suggestion=suggestion)

        auto.scan()
        suggestion.refresh_from_db()
        assert suggestion.status == ReviewStatus.REJECTED
        assert suggestion not in auto.pending_suggestions()


def test_rescanning_refreshes_an_undecided_finding(tenant):
    """Evidence strengthens as more data arrives, so an open suggestion should
    reflect the best current reasoning."""
    with tenant_scope(tenant):
        checking, _, groceries, _ = _setup()
        for days in (60, 30, 0):
            _spend(checking, groceries, 1_299, days_ago=days, payee="Streaming Co")
        auto.scan()

        suggestion = AutomationSuggestion.objects.filter(kind=SuggestionKind.RECURRING).first()
        assert suggestion is not None

        result = auto.scan()
        assert result.refreshed >= 1


# =============================================================================
# Accounting safety
# =============================================================================
def test_scanning_never_writes_to_the_ledger(tenant):
    """The governing rule of the whole module."""
    with tenant_scope(tenant):
        checking, savings, groceries, _ = _setup()
        finance_services.record_transfer(
            from_account=checking,
            to_account=savings,
            amount_minor=50_000,
            occurred_at=timezone.now(),
        )
        _spend(checking, groceries, 1_250)
        _spend(checking, groceries, 1_250)

        before = LedgerLine.objects.count()
        auto.scan()
        assert LedgerLine.objects.count() == before


def test_approving_a_duplicate_does_not_delete_anything(tenant):
    """Duplicates are advisory. Acting on one would delete a real transaction
    on the strength of a guess."""
    with tenant_scope(tenant):
        checking, _, groceries, _ = _setup()
        _spend(checking, groceries, 1_250)
        _spend(checking, groceries, 1_250)
        auto.scan()

        suggestion = AutomationSuggestion.objects.filter(kind=SuggestionKind.DUPLICATE).first()
        lines_before = LedgerLine.objects.count()
        txns_before = suggestion.transactions.count()

        auto.approve(suggestion=suggestion)

        assert LedgerLine.objects.count() == lines_before
        assert suggestion.transactions.count() == txns_before
        assert suggestion.status == ReviewStatus.APPROVED


def test_approving_a_transfer_suggestion_does_not_repost(tenant):
    with tenant_scope(tenant):
        checking, savings, _, _ = _setup()
        finance_services.record_transfer(
            from_account=checking,
            to_account=savings,
            amount_minor=50_000,
            occurred_at=timezone.now(),
        )
        auto.scan()
        suggestion = AutomationSuggestion.objects.filter(kind=SuggestionKind.TRANSFER).first()

        before = LedgerLine.objects.count()
        auto.approve(suggestion=suggestion)
        assert LedgerLine.objects.count() == before


# =============================================================================
# Learning
# =============================================================================
def test_categorising_a_transaction_teaches_the_merchant_profile(tenant):
    with tenant_scope(tenant):
        checking, _, groceries, _ = _setup()
        txn = _spend(checking, groceries, 3_000, payee="SQ *CORNER SHOP 1234")
        auto.learn_from_transaction(txn)

        profile = MerchantProfile.objects.get()
        assert profile.display_name == "Corner Shop"
        assert profile.category_counts[str(groceries.id)] == 1
        assert profile.transaction_count == 1


def test_descriptor_variants_teach_one_profile(tenant):
    """The payoff of normalisation: three descriptors, one merchant, enough
    examples to actually learn something."""
    with tenant_scope(tenant):
        checking, _, groceries, _ = _setup()
        for descriptor in ("SQ *CORNER SHOP 1234", "SQ*CORNER SHOP", "CORNER SHOP 4471"):
            auto.learn_from_transaction(_spend(checking, groceries, 3_000, payee=descriptor))

        assert MerchantProfile.objects.count() == 1
        profile = MerchantProfile.objects.get()
        assert profile.category_counts[str(groceries.id)] == 3
        # And the raw descriptors are kept so "why were these grouped?" has an
        # answer.
        assert len(profile.seen_descriptors) == 3


def test_a_learned_category_is_suggested_on_the_next_scan(tenant):
    with tenant_scope(tenant):
        checking, _, groceries, _ = _setup()
        for _ in range(3):
            auto.learn_from_transaction(_spend(checking, groceries, 3_000, payee="Corner Shop"))

        uncategorised = _import_uncategorised(checking, description="Corner Shop", amount_major=25.00)
        assert uncategorised is not None
        auto.scan()

        suggestion = AutomationSuggestion.objects.filter(
            kind=SuggestionKind.CATEGORY, primary_transaction=uncategorised
        ).first()
        assert suggestion is not None
        assert suggestion.payload["category_id"] == str(groceries.id)


def test_rejecting_a_category_withdraws_its_vote(tenant):
    """Without this the engine learns from its own mistakes and grows more
    confident in them."""
    with tenant_scope(tenant):
        checking, _, groceries, _ = _setup()
        for _ in range(3):
            auto.learn_from_transaction(_spend(checking, groceries, 3_000, payee="Corner Shop"))
        before = MerchantProfile.objects.get().category_counts[str(groceries.id)]

        auto.unlearn_category(
            merchant_key_value=detect.merchant_key("Corner Shop"),
            category_id=str(groceries.id),
        )
        after = MerchantProfile.objects.get().category_counts[str(groceries.id)]
        assert after == before - 1


def test_a_split_history_suggests_no_category(tenant):
    """A coin toss presented as a recommendation is worse than silence."""
    with tenant_scope(tenant):
        checking, _, groceries, dining = _setup()
        for category in (groceries, dining, groceries, dining):
            auto.learn_from_transaction(_spend(checking, category, 3_000, payee="Corner Shop"))

        profile = MerchantProfile.objects.get()
        assert profile.dominant_category_id is None


def test_a_dominant_category_is_reported(tenant):
    with tenant_scope(tenant):
        checking, _, groceries, dining = _setup()
        for category in (groceries, groceries, groceries, dining):
            auto.learn_from_transaction(_spend(checking, category, 3_000, payee="Corner Shop"))

        assert MerchantProfile.objects.get().dominant_category_id == str(groceries.id)


# =============================================================================
# Review workflow
# =============================================================================
def test_approving_a_category_applies_it(tenant):
    with tenant_scope(tenant):
        checking, _, groceries, _ = _setup()
        for _ in range(3):
            auto.learn_from_transaction(_spend(checking, groceries, 3_000, payee="Corner Shop"))
        uncategorised = _import_uncategorised(checking, description="Corner Shop", amount_major=25.00)
        auto.scan()

        suggestion = AutomationSuggestion.objects.filter(
            kind=SuggestionKind.CATEGORY, primary_transaction=uncategorised
        ).first()
        if suggestion.status != ReviewStatus.AUTO_APPLIED:
            auto.approve(suggestion=suggestion)

        uncategorised.refresh_from_db()
        assert uncategorised.category_id == groceries.id


def test_a_decided_suggestion_cannot_be_decided_again(tenant):
    with tenant_scope(tenant):
        checking, _, groceries, _ = _setup()
        _spend(checking, groceries, 1_250)
        _spend(checking, groceries, 1_250)
        auto.scan()

        suggestion = AutomationSuggestion.objects.filter(kind=SuggestionKind.DUPLICATE).first()
        auto.reject(suggestion=suggestion)
        with pytest.raises(auto.AutomationError):
            auto.approve(suggestion=suggestion)


def test_bulk_review_decides_many_at_once(tenant):
    """A hundred suggestions one tap at a time is a queue nobody finishes."""
    with tenant_scope(tenant):
        checking, _, groceries, _ = _setup()
        for i in range(4):
            _spend(checking, groceries, 1_000 + i, days_ago=i, payee=f"Shop {i}")
            _spend(checking, groceries, 1_000 + i, days_ago=i, payee=f"Shop {i}")
        auto.scan()

        ids = [s.id for s in auto.pending_suggestions()]
        assert len(ids) >= 2

        decided = auto.bulk_decide(suggestion_ids=ids, decision="reject")
        assert decided == len(ids)
        assert auto.pending_suggestions().count() == 0


def test_bulk_review_rejects_an_unknown_decision(tenant):
    with tenant_scope(tenant), pytest.raises(auto.AutomationError):
        auto.bulk_decide(suggestion_ids=[], decision="maybe")


def test_bulk_review_skips_rows_already_decided_elsewhere(tenant):
    """A concurrent session shouldn't be able to fail someone else's batch."""
    with tenant_scope(tenant):
        checking, _, groceries, _ = _setup()
        _spend(checking, groceries, 1_250)
        _spend(checking, groceries, 1_250)
        auto.scan()

        suggestions = list(auto.pending_suggestions())
        auto.reject(suggestion=suggestions[0])

        decided = auto.bulk_decide(suggestion_ids=[s.id for s in suggestions], decision="approve")
        assert decided == len(suggestions) - 1


# =============================================================================
# Queue summary
# =============================================================================
def test_the_queue_reports_its_own_accuracy(tenant):
    with tenant_scope(tenant):
        checking, _, groceries, _ = _setup()
        for i in range(3):
            _spend(checking, groceries, 2_000 + i, days_ago=i, payee=f"Shop {i}")
            _spend(checking, groceries, 2_000 + i, days_ago=i, payee=f"Shop {i}")
        auto.scan()

        pending = list(auto.pending_suggestions())
        auto.approve(suggestion=pending[0])
        auto.reject(suggestion=pending[1])

        summary = auto.queue_summary()
        assert summary.approval_rate == 0.5
        assert summary.pending == len(pending) - 2


def test_accuracy_is_none_before_anything_is_decided(tenant):
    """An accuracy figure from no data is not an accuracy figure."""
    with tenant_scope(tenant):
        assert auto.queue_summary().approval_rate is None


def test_the_uncategorised_placeholder_is_never_learned(tenant):
    """It means "we don't know". Voting for it would make the engine confident
    in its own ignorance."""
    with tenant_scope(tenant):
        checking, _, _, _ = _setup()
        for _ in range(3):
            imported = _import_uncategorised(checking, description="Mystery Shop", amount_major=12.00)
            auto.learn_from_transaction(imported)

        profile = MerchantProfile.objects.get(key=detect.merchant_key("Mystery Shop"))
        assert profile.category_counts == {}
        # The merchant is still learned — only the fake category is skipped.
        assert profile.transaction_count == 3


# =============================================================================
# API
# =============================================================================
def _api_setup(client):
    account = client.post(
        "/api/v1/finance/accounts/",
        {
            "name": "Checking",
            "account_type": "checking",
            "currency": "USD",
            "opening_balance_minor": 1_000_000,
        },
        format="json",
    ).data
    savings = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Savings", "account_type": "savings", "currency": "USD"},
        format="json",
    ).data
    category = client.post(
        "/api/v1/finance/categories/",
        {"name": "Groceries", "kind": "expense", "currency": "USD"},
        format="json",
    ).data
    return account, savings, category


def _api_spend(client, account, category, amount, description="Corner Shop"):
    return client.post(
        "/api/v1/finance/transactions/",
        {
            "financial_account_id": account["id"],
            "category_id": category["id"],
            "type": "expense",
            "amount_minor": amount,
            "occurred_at": timezone.now().isoformat(),
            "memo": description,
        },
        format="json",
    )


def test_api_scan_and_queue(tenant_context):
    _, client = tenant_context
    account, _, category = _api_setup(client)
    _api_spend(client, account, category, 1_250)
    _api_spend(client, account, category, 1_250)

    scan = client.post("/api/v1/intelligence/automation/scan/", {}, format="json")
    assert scan.status_code == 200, scan.data
    assert scan.data["created"] >= 1

    queue = client.get("/api/v1/intelligence/automation/queue/").data
    assert queue["pending"] >= 1
    assert queue["suggestions"]
    # Every suggestion arrives with the reasoning behind it.
    assert all(s["reason"] for s in queue["suggestions"])
    # No accuracy claimed before anything is decided.
    assert queue["approval_rate"] is None


def test_api_scanning_twice_creates_nothing_new(tenant_context):
    _, client = tenant_context
    account, _, category = _api_setup(client)
    _api_spend(client, account, category, 1_250)
    _api_spend(client, account, category, 1_250)

    client.post("/api/v1/intelligence/automation/scan/", {}, format="json")
    second = client.post("/api/v1/intelligence/automation/scan/", {}, format="json")
    assert second.data["created"] == 0


def test_api_decide_one(tenant_context):
    _, client = tenant_context
    account, _, category = _api_setup(client)
    _api_spend(client, account, category, 1_250)
    _api_spend(client, account, category, 1_250)
    client.post("/api/v1/intelligence/automation/scan/", {}, format="json")

    suggestion = client.get("/api/v1/intelligence/automation/queue/").data["suggestions"][0]
    resp = client.post(f"/api/v1/intelligence/automation/{suggestion['id']}/reject/", {}, format="json")
    assert resp.status_code == 200
    assert resp.data["status"] == "rejected"


def test_api_rejects_an_unknown_decision(tenant_context):
    _, client = tenant_context
    account, _, category = _api_setup(client)
    _api_spend(client, account, category, 1_250)
    _api_spend(client, account, category, 1_250)
    client.post("/api/v1/intelligence/automation/scan/", {}, format="json")
    suggestion = client.get("/api/v1/intelligence/automation/queue/").data["suggestions"][0]

    resp = client.post(f"/api/v1/intelligence/automation/{suggestion['id']}/maybe/", {}, format="json")
    assert resp.status_code == 400


def test_api_bulk_decide(tenant_context):
    _, client = tenant_context
    account, _, category = _api_setup(client)
    for i in range(3):
        _api_spend(client, account, category, 2_000 + i, description=f"Shop {i}")
        _api_spend(client, account, category, 2_000 + i, description=f"Shop {i}")
    client.post("/api/v1/intelligence/automation/scan/", {}, format="json")

    ids = [s["id"] for s in client.get("/api/v1/intelligence/automation/queue/").data["suggestions"]]
    resp = client.post(
        "/api/v1/intelligence/automation/bulk/",
        {"suggestion_ids": ids, "decision": "reject"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["decided"] == len(ids)
    assert client.get("/api/v1/intelligence/automation/queue/").data["pending"] == 0


def test_api_merchant_profiles_expose_the_learning(tenant_context):
    """A user who asks why a category keeps being suggested deserves to see the
    counts it came from."""
    membership, client = tenant_context
    account, _, category = _api_setup(client)
    for _ in range(3):
        _api_spend(client, account, category, 3_000, description="SQ *CORNER SHOP 1234")

    from apps.finance.models import Transaction

    # The client carries the tenant; direct ORM access needs its own binding.
    with tenant_scope(membership.tenant_id):
        for txn in Transaction.objects.all():
            auto.learn_from_transaction(txn)

    profiles = client.get("/api/v1/intelligence/merchants/").data
    assert profiles
    assert any(p["seen_descriptors"] for p in profiles)


# =============================================================================
# Approved detections reach the forecast
# =============================================================================
def test_approving_a_recurring_charge_puts_it_in_the_forecast(tenant):
    """Marking the merchant profile teaches the categoriser and nothing else.
    The cash-flow projection reads bills and recurring templates, so before this
    a user could approve "yes, this recurs" and watch their forecast stay
    completely flat — the one screen the finding most belonged on."""
    from apps.finance.models import Bill, BillStatus

    with tenant_scope(tenant):
        checking, _, groceries, _ = _setup()
        for days in (60, 30, 0):
            _spend(checking, groceries, 1_299, days_ago=days, payee="Streaming Co")
        auto.scan()

        suggestion = AutomationSuggestion.objects.filter(kind=SuggestionKind.RECURRING).first()
        assert suggestion is not None
        assert not Bill.objects.exists(), "nothing forecast before the user agrees"

        auto.approve(suggestion=suggestion)

        bill = Bill.objects.get()
        assert bill.amount_minor == 1_299
        assert bill.status == BillStatus.UPCOMING
        # ~30 days after the most recent charge, which was today.
        assert bill.due_on > timezone.localdate()


def test_a_predicted_bill_is_never_a_recurring_template(tenant):
    """An active recurring template is executed by a beat task that posts real
    ledger entries. Creating one from a *guess* would write transactions the
    user never made — the single thing this module refuses to do. A bill is an
    expectation, and it posts nothing until somebody marks it paid."""
    from apps.finance.models import RecurringTransaction

    with tenant_scope(tenant):
        checking, _, groceries, _ = _setup()
        for days in (60, 30, 0):
            _spend(checking, groceries, 1_299, days_ago=days, payee="Streaming Co")
        auto.scan()
        suggestion = AutomationSuggestion.objects.filter(kind=SuggestionKind.RECURRING).first()

        before = LedgerLine.objects.count()
        auto.approve(suggestion=suggestion)

        assert not RecurringTransaction.objects.exists()
        assert LedgerLine.objects.count() == before


def test_the_same_charge_is_only_forecast_once(tenant):
    """Approving twice is already refused upstream, so the duplicate that can
    actually happen is the detector re-firing on the same history and a second
    suggestion being approved. The guard is on the predicted bill itself."""
    with tenant_scope(tenant):
        from apps.finance.models import Bill

        checking, _, groceries, _ = _setup()
        for days in (60, 30, 0):
            _spend(checking, groceries, 1_299, days_ago=days, payee="Streaming Co")
        auto.scan()
        suggestion = AutomationSuggestion.objects.filter(kind=SuggestionKind.RECURRING).first()

        auto.approve(suggestion=suggestion)
        # Exactly what a rescan-then-approve would reach.
        auto._forecast_next_occurrence(suggestion)
        assert Bill.objects.count() == 1
