"""Account edit, deactivate/reactivate, and permanent delete.

Service-level tests exercise `delete_financial_account`'s guards directly
against the tenant-scoped ORM; API-level tests reach the same lifecycle
through real DRF views, permissions, and RLS binding (mirrors the style in
test_finance_modules_api.py / test_bills_recurring_import.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from apps.finance import bills, recurring, services
from apps.finance.models import AccountType, CategoryKind, FinancialAccount, Transaction
from apps.tenancy.models import Role
from tests.conftest import _bearer_client
from tests.factories import MembershipFactory
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


# =============================================================================
# Service level — delete_financial_account guards
# =============================================================================
@pytest.fixture
def tenant_id():
    return uuid.uuid4()


def _account(name="Checking", account_type=AccountType.CHECKING, currency="USD"):
    return services.create_financial_account(name=name, account_type=account_type, currency=currency)


def test_delete_succeeds_and_soft_deletes_a_clean_account(tenant_id):
    with tenant_scope(tenant_id):
        acct = _account()
        services.delete_financial_account(financial_account=acct)
        assert not FinancialAccount.objects.filter(id=acct.id).exists()
        assert FinancialAccount.all_objects.filter(id=acct.id).exists()


def test_delete_blocked_when_account_is_the_primary_leg(tenant_id):
    with tenant_scope(tenant_id):
        acct = _account()
        category = services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
        services.record_expense(
            financial_account=acct,
            category=category,
            amount_minor=5000,
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        with pytest.raises(services.FinanceError, match="transactions"):
            services.delete_financial_account(financial_account=acct)
        assert FinancialAccount.objects.filter(id=acct.id).exists()


def test_delete_blocked_when_account_is_only_a_transfer_counterparty(tenant_id):
    """A transfer's two rows are symmetric (each account is `financial_account`
    on its own leg and `counter_account` on the other's), so a real transfer
    always exercises both branches of the guard's query at once. This test
    isolates the `counter_account`-only branch with a bare row that has no
    `financial_account` leg of its own, so the OR is proven necessary rather
    than merely redundant with the primary-leg test above."""
    with tenant_scope(tenant_id):
        acct = _account("Checking")
        other = _account("Savings", account_type=AccountType.SAVINGS)
        Transaction.objects.create(
            financial_account=other,
            counter_account=acct,
            amount_minor=1000,
            currency="USD",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        with pytest.raises(services.FinanceError, match="transactions"):
            services.delete_financial_account(financial_account=acct)


def test_delete_blocked_when_account_backs_a_recurring_schedule(tenant_id):
    with tenant_scope(tenant_id):
        acct = _account()
        category = services.create_category(name="Housing", kind=CategoryKind.EXPENSE, currency="USD")
        recurring.create_recurring_transaction(
            txn_type="expense",
            financial_account=acct,
            category=category,
            amount_minor=150000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 2, 1),
        )
        with pytest.raises(services.FinanceError, match="recurring"):
            services.delete_financial_account(financial_account=acct)


def test_delete_blocked_when_account_is_a_recurring_transfer_counterparty(tenant_id):
    with tenant_scope(tenant_id):
        acct = _account("Checking")
        other = _account("Savings", account_type=AccountType.SAVINGS)
        recurring.create_recurring_transaction(
            txn_type="transfer",
            financial_account=other,
            counter_account=acct,
            amount_minor=20000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 2, 1),
        )
        with pytest.raises(services.FinanceError, match="recurring"):
            services.delete_financial_account(financial_account=acct)


def test_delete_blocked_when_account_is_a_bills_autopay_account(tenant_id):
    with tenant_scope(tenant_id):
        acct = _account()
        bills.create_bill(
            name="Rent",
            amount_minor=150000,
            currency="USD",
            due_on=date(2026, 2, 1),
            autopay_account=acct,
        )
        with pytest.raises(services.FinanceError, match="autopay"):
            services.delete_financial_account(financial_account=acct)


def test_update_financial_account_ignores_disallowed_keys(tenant_id):
    with tenant_scope(tenant_id):
        acct = _account(currency="USD")
        services.update_financial_account(
            financial_account=acct, name="Renamed", currency="EUR", account_type=AccountType.SAVINGS
        )
        acct.refresh_from_db()
        assert acct.name == "Renamed"
        assert acct.currency == "USD"
        assert acct.account_type == AccountType.CHECKING


# =============================================================================
# API level
# =============================================================================
def _api_account(client, name="Checking", account_type="checking", currency="USD", opening=1_000_000):
    return client.post(
        "/api/v1/finance/accounts/",
        {"name": name, "account_type": account_type, "currency": currency, "opening_balance_minor": opening},
        format="json",
    ).data


def test_patch_account_edits_fields(tenant_context):
    membership, client = tenant_context
    acct = _api_account(client)
    resp = client.patch(
        f"/api/v1/finance/accounts/{acct['id']}/",
        {"name": "Main Checking", "notes": "primary"},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["name"] == "Main Checking"
    assert resp.data["notes"] == "primary"


def test_delete_archives_and_it_still_resolves_with_include_archived(tenant_context):
    membership, client = tenant_context
    acct = _api_account(client)

    resp = client.delete(f"/api/v1/finance/accounts/{acct['id']}/")
    assert resp.status_code == 200, resp.data
    assert resp.data["is_archived"] is True

    default_listing = client.get("/api/v1/finance/accounts/")
    assert acct["id"] not in [a["id"] for a in default_listing.data]

    archived_listing = client.get("/api/v1/finance/accounts/?include_archived=1")
    assert acct["id"] in [a["id"] for a in archived_listing.data]


def test_unarchive_reverses_it(tenant_context):
    membership, client = tenant_context
    acct = _api_account(client)
    client.delete(f"/api/v1/finance/accounts/{acct['id']}/")

    resp = client.post(f"/api/v1/finance/accounts/{acct['id']}/unarchive/", {}, format="json")
    assert resp.status_code == 200, resp.data
    assert resp.data["is_archived"] is False

    default_listing = client.get("/api/v1/finance/accounts/")
    assert acct["id"] in [a["id"] for a in default_listing.data]


def test_purge_succeeds_on_a_clean_account(tenant_context):
    membership, client = tenant_context
    acct = _api_account(client)
    resp = client.delete(f"/api/v1/finance/accounts/{acct['id']}/purge/")
    assert resp.status_code == 204, resp.data

    listing = client.get("/api/v1/finance/accounts/?include_archived=1")
    assert acct["id"] not in [a["id"] for a in listing.data]


def test_purge_422s_once_the_account_has_a_transaction(tenant_context):
    membership, client = tenant_context
    acct = _api_account(client)
    cat = client.post(
        "/api/v1/finance/categories/",
        {"name": "Groceries", "kind": "expense", "currency": "USD"},
        format="json",
    ).data
    client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": acct["id"],
            "category_id": cat["id"],
            "amount_minor": 5000,
            "occurred_at": "2026-01-01T00:00:00Z",
        },
        format="json",
    )

    resp = client.delete(f"/api/v1/finance/accounts/{acct['id']}/purge/")
    assert resp.status_code == 422
    assert "detail" in resp.data


def test_viewer_cannot_write_account_lifecycle_endpoints(tenant_context):
    owner_membership, owner_client = tenant_context
    acct = _api_account(owner_client)
    viewer = MembershipFactory(tenant=owner_membership.tenant, role=Role.VIEWER)
    viewer_client = _bearer_client(viewer.user, tenant_id=viewer.tenant_id)

    assert (
        viewer_client.patch(
            f"/api/v1/finance/accounts/{acct['id']}/", {"name": "Hack"}, format="json"
        ).status_code
        == 403
    )
    assert viewer_client.delete(f"/api/v1/finance/accounts/{acct['id']}/").status_code == 403
    assert (
        viewer_client.post(f"/api/v1/finance/accounts/{acct['id']}/unarchive/", {}, format="json").status_code
        == 403
    )
    assert viewer_client.delete(f"/api/v1/finance/accounts/{acct['id']}/purge/").status_code == 403
