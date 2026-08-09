"""AutomationRule: the regex operator, edit (GET/PATCH) support, retroactive
apply, and the RLS fix that makes this table's tenant isolation more than
ORM-deep."""

from __future__ import annotations

import uuid

import pytest
from django.db import connection
from django.utils import timezone

from apps.finance import services as finance_services
from apps.finance.models import AccountType, CategoryKind
from apps.intelligence import automation
from apps.intelligence import services as intel_services
from apps.intelligence.models import AutomationRule
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db

PARKNGO_MEMO = "Pay Bill Online to 4161505 - PARKNGO LIMITED Acc. Garden- sp"


@pytest.fixture
def tenant():
    return uuid.uuid4()


def _categories():
    parking = finance_services.create_category(name="Parking", kind=CategoryKind.EXPENSE, currency="USD")
    # Mirrors the real lazily-created placeholder both import_csv.py and
    # import_mpesa_service.py fall back to — a posting needs *some* category,
    # so a genuinely-uncategorized import row lands here, never at
    # category=None. This is the population apply_rules_to_uncategorized's
    # default scope actually needs to reach.
    uncategorized = finance_services.create_category(
        name="Uncategorized", kind=CategoryKind.EXPENSE, currency="USD"
    )
    return parking, uncategorized


def _seed():
    account = finance_services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency="USD", opening_balance_minor=1_000_000
    )
    parking, uncategorized = _categories()
    return account, parking, uncategorized


def _spend(account, category, amount=1500, memo=""):
    return finance_services.record_expense(
        financial_account=account,
        category=category,
        amount_minor=amount,
        occurred_at=timezone.now(),
        memo=memo,
    )


def _clear_category(txn):
    """The other, rarer way a transaction ends up with no category: a human
    clears it by hand via PATCH (services.update_transaction(category=None))."""
    return finance_services.update_transaction(txn=txn, category=None)


# =============================================================================
# Regex operator — engine level
# =============================================================================
def test_regex_matches_the_parkngo_memo():
    conditions = {"all": [{"field": "memo", "op": "regex", "value": "PARKNGO"}]}
    assert automation.conditions_match(conditions, {"memo": PARKNGO_MEMO}) is True


def test_regex_does_not_match_unrelated_memo():
    conditions = {"all": [{"field": "memo", "op": "regex", "value": "PARKNGO"}]}
    assert automation.conditions_match(conditions, {"memo": "Naivas Supermarket"}) is False


def test_regex_is_case_insensitive():
    conditions = {"all": [{"field": "memo", "op": "regex", "value": "parkngo"}]}
    assert automation.conditions_match(conditions, {"memo": PARKNGO_MEMO}) is True


def test_validate_conditions_rejects_an_invalid_pattern():
    with pytest.raises(automation.AutomationError):
        automation.validate_conditions({"all": [{"field": "memo", "op": "regex", "value": "("}]})


def test_validate_conditions_accepts_a_valid_pattern():
    automation.validate_conditions({"all": [{"field": "memo", "op": "regex", "value": "PARKNGO"}]})


def test_a_bad_stored_regex_degrades_to_no_match_rather_than_crashing():
    """Defense in depth: data that predates validation (or was written
    directly) must not crash evaluation."""
    conditions = {"all": [{"field": "memo", "op": "regex", "value": "("}]}
    assert automation.conditions_match(conditions, {"memo": "anything"}) is False


# =============================================================================
# End-to-end: a regex rule actually categorizes a matching transaction
# =============================================================================
def test_a_regex_rule_categorizes_a_matching_transaction_on_creation(tenant):
    """The PARKNGO example, exactly as described: a rule matching
    field=memo, op=regex, value=PARKNGO sets the category to Parking — even
    though the transaction arrives holding the import placeholder category,
    not a true null one."""
    with tenant_scope(tenant):
        account, parking, uncategorized = _seed()
        AutomationRule.objects.create(
            name="Parking",
            conditions={"all": [{"field": "memo", "op": "regex", "value": "PARKNGO"}]},
            actions=[{"type": "set_category", "category_id": str(parking.id)}],
        )
        txn = _spend(account, category=uncategorized, memo=PARKNGO_MEMO)
        intel_services.run_automation(txn)
        txn.refresh_from_db()
        assert txn.category_id == parking.id


# =============================================================================
# Create/update API — regex validated at save time
# =============================================================================
def test_api_create_rule_with_regex_condition(tenant_context):
    _, client = tenant_context
    resp = client.post(
        "/api/v1/intelligence/automation-rules/",
        {
            "name": "Parking",
            "conditions": {"all": [{"field": "memo", "op": "regex", "value": "PARKNGO"}]},
            "actions": [{"type": "flag_review"}],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["conditions"]["all"][0]["op"] == "regex"


def test_api_create_rule_rejects_invalid_regex(tenant_context):
    _, client = tenant_context
    resp = client.post(
        "/api/v1/intelligence/automation-rules/",
        {
            "name": "Bad",
            "conditions": {"all": [{"field": "memo", "op": "regex", "value": "("}]},
            "actions": [{"type": "flag_review"}],
        },
        format="json",
    )
    assert resp.status_code == 422


def test_api_update_rule_rejects_invalid_regex(tenant_context):
    _, client = tenant_context
    created = client.post(
        "/api/v1/intelligence/automation-rules/",
        {
            "name": "Parking",
            "conditions": {"all": [{"field": "memo", "op": "regex", "value": "PARKNGO"}]},
            "actions": [{"type": "flag_review"}],
        },
        format="json",
    ).data
    resp = client.patch(
        f"/api/v1/intelligence/automation-rules/{created['id']}/",
        {"conditions": {"all": [{"field": "memo", "op": "regex", "value": "("}]}},
        format="json",
    )
    assert resp.status_code == 422


# =============================================================================
# GET-single / PATCH
# =============================================================================
def test_api_get_single_rule(tenant_context):
    _, client = tenant_context
    created = client.post(
        "/api/v1/intelligence/automation-rules/",
        {
            "name": "Parking",
            "conditions": {"all": [{"field": "memo", "op": "contains", "value": "parkngo"}]},
            "actions": [{"type": "flag_review"}],
        },
        format="json",
    ).data
    resp = client.get(f"/api/v1/intelligence/automation-rules/{created['id']}/")
    assert resp.status_code == 200
    assert resp.data["name"] == "Parking"


def test_api_get_single_rule_404(tenant_context):
    _, client = tenant_context
    resp = client.get(f"/api/v1/intelligence/automation-rules/{uuid.uuid4()}/")
    assert resp.status_code == 404


def test_api_patch_updates_only_the_given_fields(tenant_context):
    _, client = tenant_context
    created = client.post(
        "/api/v1/intelligence/automation-rules/",
        {
            "name": "Parking",
            "conditions": {"all": [{"field": "memo", "op": "contains", "value": "parkngo"}]},
            "actions": [{"type": "flag_review"}],
            "priority": 50,
        },
        format="json",
    ).data

    resp = client.patch(
        f"/api/v1/intelligence/automation-rules/{created['id']}/", {"is_active": False}, format="json"
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["is_active"] is False
    # everything else untouched
    assert resp.data["name"] == "Parking"
    assert resp.data["priority"] == 50
    assert resp.data["conditions"] == created["conditions"]


def test_api_patch_rejects_an_empty_body(tenant_context):
    _, client = tenant_context
    created = client.post(
        "/api/v1/intelligence/automation-rules/",
        {
            "name": "Parking",
            "conditions": {"all": [{"field": "memo", "op": "contains", "value": "parkngo"}]},
            "actions": [{"type": "flag_review"}],
        },
        format="json",
    ).data
    resp = client.patch(f"/api/v1/intelligence/automation-rules/{created['id']}/", {}, format="json")
    assert resp.status_code == 400


def test_api_patch_404(tenant_context):
    _, client = tenant_context
    resp = client.patch(
        f"/api/v1/intelligence/automation-rules/{uuid.uuid4()}/", {"is_active": False}, format="json"
    )
    assert resp.status_code == 404


# =============================================================================
# Retroactive apply
# =============================================================================
def test_apply_rules_targets_the_import_placeholder_by_default(tenant):
    with tenant_scope(tenant):
        account, parking, uncategorized = _seed()
        already_categorized = _spend(account, category=parking, memo=PARKNGO_MEMO)
        placeholder = _spend(account, category=uncategorized, memo=PARKNGO_MEMO)
        AutomationRule.objects.create(
            name="Parking",
            conditions={"all": [{"field": "memo", "op": "regex", "value": "PARKNGO"}]},
            actions=[{"type": "set_category", "category_id": str(parking.id)}],
        )

        result = intel_services.apply_rules_to_uncategorized(scope="uncategorized")
        # the already-correctly-categorized row isn't even in scope
        assert result.scanned == 1
        assert result.matched == 1
        placeholder.refresh_from_db()
        already_categorized.refresh_from_db()
        assert placeholder.category_id == parking.id
        assert already_categorized.category_id == parking.id  # untouched, was already this


def test_apply_rules_also_reaches_a_category_cleared_by_hand(tenant):
    with tenant_scope(tenant):
        account, parking, uncategorized = _seed()
        txn = _spend(account, category=uncategorized, memo=PARKNGO_MEMO)
        _clear_category(txn)
        assert txn.category_id is None
        AutomationRule.objects.create(
            name="Parking",
            conditions={"all": [{"field": "memo", "op": "regex", "value": "PARKNGO"}]},
            actions=[{"type": "set_category", "category_id": str(parking.id)}],
        )

        result = intel_services.apply_rules_to_uncategorized(scope="uncategorized")
        assert result.matched == 1
        txn.refresh_from_db()
        assert txn.category_id == parking.id


def test_apply_rules_all_scope_reaches_already_categorized_rows_for_tag_only_rules(tenant):
    with tenant_scope(tenant):
        account, parking, _uncategorized = _seed()
        txn = _spend(account, category=parking, memo=PARKNGO_MEMO)
        AutomationRule.objects.create(
            name="Flag parking",
            conditions={"all": [{"field": "memo", "op": "regex", "value": "PARKNGO"}]},
            actions=[{"type": "flag_review"}],
        )

        result = intel_services.apply_rules_to_uncategorized(scope="all")
        assert result.scanned == 1
        assert result.matched == 1
        txn.refresh_from_db()
        assert txn.needs_review is True


def test_apply_rules_excludes_transfers_and_void(tenant):
    with tenant_scope(tenant):
        checking = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=1_000_000,
        )
        savings = finance_services.create_financial_account(
            name="Savings", account_type=AccountType.SAVINGS, currency="USD"
        )
        finance_services.record_transfer(
            from_account=checking, to_account=savings, amount_minor=5000, occurred_at=timezone.now()
        )
        parking, uncategorized = _categories()
        voided = _spend(checking, category=uncategorized, memo=PARKNGO_MEMO)
        finance_services.void_transaction(txn=voided)
        AutomationRule.objects.create(
            name="Parking",
            conditions={"all": [{"field": "memo", "op": "regex", "value": "PARKNGO"}]},
            actions=[{"type": "set_category", "category_id": str(parking.id)}],
        )

        result = intel_services.apply_rules_to_uncategorized(scope="all")
        assert result.scanned == 0


def test_apply_rules_one_bad_row_does_not_abort_the_batch(tenant):
    """A rule whose target category kind mismatches the transaction direction
    raises CategoryKindError deep inside run_automation — that must not take
    down every other row in the sweep."""
    with tenant_scope(tenant):
        account, _parking, uncategorized = _seed()
        income_category = finance_services.create_category(
            name="Salary", kind=CategoryKind.INCOME, currency="USD"
        )
        # An income category applied to an expense row is the mismatch.
        AutomationRule.objects.create(
            name="Bad rule",
            conditions={"all": [{"field": "memo", "op": "regex", "value": "PARKNGO"}]},
            actions=[{"type": "set_category", "category_id": str(income_category.id)}],
        )
        bad = _spend(account, category=uncategorized, memo=PARKNGO_MEMO)
        good = _spend(account, category=uncategorized, memo="unrelated memo, no rule matches")

        result = intel_services.apply_rules_to_uncategorized(scope="uncategorized")
        assert result.scanned == 2
        assert len(result.errors) == 1
        assert result.errors[0]["transaction_id"] == str(bad.id)
        good.refresh_from_db()
        assert good.category_id == uncategorized.id  # no rule matched it, untouched — not an error


def test_apply_rules_respects_limit(tenant):
    with tenant_scope(tenant):
        account, parking, uncategorized = _seed()
        for _ in range(3):
            _spend(account, category=uncategorized, memo=PARKNGO_MEMO)
        AutomationRule.objects.create(
            name="Parking",
            conditions={"all": [{"field": "memo", "op": "regex", "value": "PARKNGO"}]},
            actions=[{"type": "set_category", "category_id": str(parking.id)}],
        )
        result = intel_services.apply_rules_to_uncategorized(scope="uncategorized", limit=2)
        assert result.scanned == 2


def test_apply_rules_is_a_noop_with_no_active_rules(tenant):
    with tenant_scope(tenant):
        account, _parking, uncategorized = _seed()
        _spend(account, category=uncategorized, memo=PARKNGO_MEMO)
        result = intel_services.apply_rules_to_uncategorized()
        assert result == intel_services.RetroactiveApplyResult(0, 0, 0, [])


def test_api_apply_rules_endpoint(tenant_context):
    _, client = tenant_context
    account, parking, uncategorized = _seed_via_client(client)
    client.post(
        "/api/v1/intelligence/automation-rules/",
        {
            "name": "Parking",
            "conditions": {"all": [{"field": "memo", "op": "regex", "value": "PARKNGO"}]},
            "actions": [{"type": "set_category", "category_id": parking["id"]}],
        },
        format="json",
    )
    client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": account["id"],
            "category_id": uncategorized["id"],
            "amount_minor": 1000,
            "occurred_at": timezone.now().isoformat(),
            "memo": PARKNGO_MEMO,
        },
        format="json",
    )
    resp = client.post("/api/v1/intelligence/automation/apply-rules/", {}, format="json")
    assert resp.status_code == 200, resp.data
    assert resp.data["matched"] == 1


def _seed_via_client(client):
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
    parking = client.post(
        "/api/v1/finance/categories/",
        {"name": "Parking", "kind": "expense", "currency": "USD"},
        format="json",
    ).data
    uncategorized = client.post(
        "/api/v1/finance/categories/",
        {"name": "Uncategorized", "kind": "expense", "currency": "USD"},
        format="json",
    ).data
    return account, parking, uncategorized


# =============================================================================
# RLS
# =============================================================================
def test_rls_denies_reads_of_automation_rules_when_no_tenant_is_bound(tenant):
    with tenant_scope(tenant):
        AutomationRule.objects.create(
            name="Parking",
            conditions={"all": [{"field": "memo", "op": "contains", "value": "x"}]},
            actions=[{"type": "flag_review"}],
        )
    if connection.vendor != "postgresql":
        pytest.skip("RLS is a PostgreSQL feature")
    with connection.cursor() as cur:
        cur.execute("SET LOCAL app.current_tenant = ''")
        cur.execute("SELECT count(*) FROM intelligence_automationrule")
        assert cur.fetchone()[0] == 0


def test_rls_prevents_reading_another_tenants_automation_rules(tenant):
    other_tenant = uuid.uuid4()
    with tenant_scope(tenant):
        AutomationRule.objects.create(
            name="Mine",
            conditions={"all": [{"field": "memo", "op": "contains", "value": "x"}]},
            actions=[{"type": "flag_review"}],
        )
    with tenant_scope(other_tenant):
        AutomationRule.objects.create(
            name="Theirs",
            conditions={"all": [{"field": "memo", "op": "contains", "value": "x"}]},
            actions=[{"type": "flag_review"}],
        )
    if connection.vendor != "postgresql":
        pytest.skip("RLS is a PostgreSQL feature")
    with connection.cursor() as cur:
        cur.execute("SET LOCAL app.current_tenant = %s", [str(tenant)])
        cur.execute("SELECT name FROM intelligence_automationrule")
        names = {row[0] for row in cur.fetchall()}
    assert names == {"Mine"}
