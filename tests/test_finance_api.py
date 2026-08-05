"""End-to-end HTTP tests for the finance + budgeting API: the engine reached
through real DRF views, permissions, and RLS binding."""

from __future__ import annotations

import pytest

from apps.tenancy.models import Role
from tests.conftest import _bearer_client
from tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db

TENANT_HDR = "HTTP_X_TENANT_ID"


def _h(membership):
    return {TENANT_HDR: str(membership.tenant_id)}


def test_create_account_and_list_balance(tenant_context):
    membership, client = tenant_context
    resp = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    listing = client.get("/api/v1/finance/accounts/")
    assert listing.status_code == 200
    assert listing.data[0]["name"] == "Checking"
    assert listing.data[0]["balance_minor"] == 0


def test_expense_flow_updates_net_worth(tenant_context):
    membership, client = tenant_context
    # Funded, because a manual expense may no longer overdraw an asset account
    # — see test_manual_expense_cannot_overdraw_an_account.
    acct = client.post(
        "/api/v1/finance/accounts/",
        {
            "name": "Checking",
            "account_type": "checking",
            "currency": "USD",
            "opening_balance_minor": 20000,
        },
        format="json",
    ).data
    cat = client.post(
        "/api/v1/finance/categories/",
        {"name": "Groceries", "kind": "expense", "currency": "USD"},
        format="json",
    ).data

    txn = client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": acct["id"],
            "category_id": cat["id"],
            "amount_minor": 5000,
            "occurred_at": "2026-01-15T12:00:00Z",
        },
        format="json",
    )
    assert txn.status_code == 201, txn.data
    assert txn.data["amount_minor"] == -5000

    nw = client.get("/api/v1/finance/net-worth/")
    assert nw.status_code == 200
    assert nw.data[0]["net_minor"] == 15000


def test_transfer_endpoint(tenant_context):
    membership, client = tenant_context
    a = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD"},
        format="json",
    ).data
    b = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Savings", "account_type": "savings", "currency": "USD"},
        format="json",
    ).data
    salary = client.post(
        "/api/v1/finance/categories/", {"name": "Salary", "kind": "income", "currency": "USD"}, format="json"
    ).data
    client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "income",
            "financial_account_id": a["id"],
            "category_id": salary["id"],
            "amount_minor": 100000,
            "occurred_at": "2026-01-01T00:00:00Z",
        },
        format="json",
    )
    resp = client.post(
        "/api/v1/finance/transfers/",
        {
            "from_account_id": a["id"],
            "to_account_id": b["id"],
            "amount_minor": 30000,
            "occurred_at": "2026-01-02T00:00:00Z",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["out"]["amount_minor"] == -30000
    assert resp.data["in"]["amount_minor"] == 30000

    # cash flow excludes the transfer: only the 100000 income shows
    flow = client.get("/api/v1/finance/cash-flow/?start=2026-01-01T00:00:00Z&end=2026-02-01T00:00:00Z")
    assert flow.data[0]["income_minor"] == 100000


def test_viewer_can_read_but_not_write(tenant_context):
    owner_membership, _owner_client = tenant_context
    viewer = MembershipFactory(tenant=owner_membership.tenant, role=Role.VIEWER)
    viewer_client = _bearer_client(viewer.user, tenant_id=viewer.tenant_id)

    # read: OK
    assert viewer_client.get("/api/v1/finance/accounts/").status_code == 200
    # write: forbidden
    resp = viewer_client.post(
        "/api/v1/finance/accounts/",
        {"name": "X", "account_type": "checking", "currency": "USD"},
        format="json",
    )
    assert resp.status_code == 403


def test_budget_status_via_api(tenant_context):
    membership, client = tenant_context
    acct = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD"},
        format="json",
    ).data
    food = client.post(
        "/api/v1/finance/categories/", {"name": "Food", "kind": "expense", "currency": "USD"}, format="json"
    ).data
    budget = client.post(
        "/api/v1/budgeting/budgets/",
        {"name": "Monthly", "currency": "USD", "starts_on": "2026-01-01", "period": "monthly"},
        format="json",
    )
    assert budget.status_code == 201, budget.data
    budget_id = budget.data["id"]
    line = client.post(
        f"/api/v1/budgeting/budgets/{budget_id}/lines/",
        {"category_id": food["id"], "limit_minor": 50000},
        format="json",
    )
    assert line.status_code == 201, line.data

    client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": acct["id"],
            "category_id": food["id"],
            "amount_minor": 20000,
            "occurred_at": "2026-01-10T12:00:00Z",
        },
        format="json",
    )
    st = client.get(f"/api/v1/budgeting/budgets/{budget_id}/status/?as_of=2026-01-31")
    assert st.status_code == 200
    assert st.data["lines"][0]["actual_minor"] == 20000
    assert st.data["lines"][0]["remaining_minor"] == 30000
    assert st.data["lines"][0]["percent_used"] == 40.0


def test_recurring_creation_via_api(tenant_context):
    membership, client = tenant_context
    acct = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD"},
        format="json",
    ).data
    rent = client.post(
        "/api/v1/finance/categories/", {"name": "Rent", "kind": "expense", "currency": "USD"}, format="json"
    ).data
    resp = client.post(
        "/api/v1/finance/recurring/",
        {
            "txn_type": "expense",
            "financial_account_id": acct["id"],
            "category_id": rent["id"],
            "amount_minor": 150000,
            "currency": "USD",
            "frequency": "monthly",
            "starts_on": "2026-02-01",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["next_run_on"] == "2026-02-01"
    assert resp.data["is_active"] is True


def test_review_count_reports_a_total_the_paginated_list_cannot(tenant_context):
    """The ledger is cursor-paginated, deliberately — it has no natural end. But
    cursor pagination cannot report a total, so anything wanting to say "12 need
    a look" has to ask directly rather than counting a page and hoping."""
    from django.utils import timezone

    from apps.finance import services as finance_services
    from apps.finance.models import AccountType, CategoryKind

    membership, client = tenant_context
    from tests.utils import tenant_scope

    with tenant_scope(membership.tenant_id):
        account = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD", opening_balance_minor=100_00
        )
        category = finance_services.create_category(
            name="Groceries", kind=CategoryKind.EXPENSE, currency="USD"
        )
        flagged = [
            finance_services.record_expense(
                financial_account=account,
                category=category,
                amount_minor=1_00,
                occurred_at=timezone.now(),
            )
            for _ in range(3)
        ]
        for txn in flagged[:2]:
            finance_services.flag_transaction_for_review(txn=txn, reason="Ambiguous payee")

    resp = client.get("/api/v1/finance/transactions/review-count/", **_h(membership))
    assert resp.status_code == 200, resp.data
    assert resp.data["count"] == 2


def test_a_transaction_says_whether_it_needs_review_and_why(tenant_context):
    """The flag was filterable but not readable: the ledger could be narrowed to
    the rows needing attention without ever being able to mark them."""
    from django.utils import timezone

    from apps.finance import services as finance_services
    from apps.finance.models import AccountType, CategoryKind
    from tests.utils import tenant_scope

    membership, client = tenant_context
    with tenant_scope(membership.tenant_id):
        account = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD", opening_balance_minor=100_00
        )
        category = finance_services.create_category(
            name="Groceries", kind=CategoryKind.EXPENSE, currency="USD"
        )
        txn = finance_services.record_expense(
            financial_account=account,
            category=category,
            amount_minor=1_00,
            occurred_at=timezone.now(),
        )
        finance_services.flag_transaction_for_review(txn=txn, reason="Ambiguous payee")

    resp = client.get("/api/v1/finance/transactions/?needs_review=true", **_h(membership))
    assert resp.status_code == 200
    rows = resp.data["results"]
    assert rows and all(r["needs_review"] for r in rows)
    assert rows[0]["review_reason"] == "Ambiguous payee"


def test_manual_expense_cannot_overdraw_an_account(tenant_context):
    """The reported bug: the product let an account be spent past empty.

    The refusal names the account and the shortfall, because "insufficient
    funds" on its own leaves the user to work out which account and by how much.
    """
    _, client = tenant_context
    acct = client.post(
        "/api/v1/finance/accounts/",
        {
            "name": "Checking",
            "account_type": "checking",
            "currency": "USD",
            "opening_balance_minor": 10_000,
        },
        format="json",
    ).data
    cat = client.post(
        "/api/v1/finance/categories/",
        {"name": "Groceries", "kind": "expense", "currency": "USD"},
        format="json",
    ).data

    over = client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": acct["id"],
            "category_id": cat["id"],
            "amount_minor": 25_000,
            "occurred_at": "2026-01-15T12:00:00Z",
        },
        format="json",
    )
    assert over.status_code == 422, over.data
    assert over.data["code"] == "insufficient_funds"
    assert over.data["account_name"] == "Checking"
    assert over.data["available_minor"] == 10_000
    assert over.data["shortfall_minor"] == 15_000
    assert "Checking" in over.data["detail"]

    # Spending down to exactly zero is fine — it is the step past it that isn't.
    exact = client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": acct["id"],
            "category_id": cat["id"],
            "amount_minor": 10_000,
            "occurred_at": "2026-01-15T12:00:00Z",
        },
        format="json",
    )
    assert exact.status_code == 201, exact.data


def test_a_credit_card_is_allowed_to_go_negative(tenant_context):
    """Carrying a balance is what a credit card is for; blocking it would make
    the product unable to record the debts its planner exists to pay off."""
    _, client = tenant_context
    card = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Visa", "account_type": "credit_card", "currency": "USD"},
        format="json",
    ).data
    cat = client.post(
        "/api/v1/finance/categories/",
        {"name": "Groceries", "kind": "expense", "currency": "USD"},
        format="json",
    ).data

    spend = client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": card["id"],
            "category_id": cat["id"],
            "amount_minor": 25_000,
            "occurred_at": "2026-01-15T12:00:00Z",
        },
        format="json",
    )
    assert spend.status_code == 201, spend.data


def test_an_arranged_overdraft_is_honoured(tenant_context):
    """`overdraft_limit_minor` is a real ceiling, not a yes/no."""
    from apps.finance.models import FinancialAccount
    from tests.utils import tenant_scope

    membership, client = tenant_context
    acct = client.post(
        "/api/v1/finance/accounts/",
        {
            "name": "Current",
            "account_type": "checking",
            "currency": "USD",
            "opening_balance_minor": 10_000,
        },
        format="json",
    ).data
    cat = client.post(
        "/api/v1/finance/categories/",
        {"name": "Groceries", "kind": "expense", "currency": "USD"},
        format="json",
    ).data
    with tenant_scope(membership.tenant_id):
        FinancialAccount.objects.filter(id=acct["id"]).update(overdraft_limit_minor=20_000)

    # 10,000 held + 20,000 arranged = 30,000 available.
    within = client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": acct["id"],
            "category_id": cat["id"],
            "amount_minor": 30_000,
            "occurred_at": "2026-01-15T12:00:00Z",
        },
        format="json",
    )
    assert within.status_code == 201, within.data
