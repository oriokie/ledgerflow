"""Category management: edit, delete, and the guards protecting data integrity."""

from __future__ import annotations

import pytest

from apps.finance import services
from apps.finance.models import Category
from tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


def _client(user, tenant_id, role=None):
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant_id))
    return client


def test_rename_category():
    m = MembershipFactory()
    client = _client(m.user, m.tenant_id)
    created = client.post(
        "/api/v1/finance/categories/",
        {"name": "Groceries", "kind": "expense", "currency": "USD"},
        format="json",
    ).json()
    resp = client.patch(f"/api/v1/finance/categories/{created['id']}/", {"name": "Food"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Food"


def test_delete_unused_category():
    m = MembershipFactory()
    client = _client(m.user, m.tenant_id)
    created = client.post(
        "/api/v1/finance/categories/",
        {"name": "Temp", "kind": "expense", "currency": "USD"},
        format="json",
    ).json()
    resp = client.delete(f"/api/v1/finance/categories/{created['id']}/")
    assert resp.status_code == 204
    # soft-deleted: gone from the default (alive) manager
    from django.db import transaction

    from apps.common.rls import bind_db_tenant
    from apps.common.tenant_context import use_tenant

    with use_tenant(m.tenant_id), transaction.atomic():
        bind_db_tenant(m.tenant_id)
        assert not Category.objects.filter(id=created["id"]).exists()


def test_cannot_delete_category_in_use():
    from django.db import transaction
    from django.utils import timezone

    from apps.common.rls import bind_db_tenant
    from apps.common.tenant_context import use_tenant
    from apps.finance import services as fin

    m = MembershipFactory()
    # build an account + category + a transaction using that category
    with use_tenant(m.tenant_id, actor_id=m.user_id), transaction.atomic():
        bind_db_tenant(m.tenant_id)
        # Funded: a workspace blocks manual overdrafts by default.
        account = fin.create_financial_account(
            name="Checking",
            account_type="checking",
            currency="USD",
            opening_balance_minor=1_000_000,
        )
        category = fin.create_category(name="Rent", kind="expense", currency="USD")
        fin.record_expense(
            financial_account=account,
            category=category,
            amount_minor=1000,
            occurred_at=timezone.now(),
        )

    client = _client(m.user, m.tenant_id)
    resp = client.delete(f"/api/v1/finance/categories/{category.id}/")
    assert resp.status_code == 422
    assert "transactions" in resp.json()["detail"].lower()


def test_cannot_delete_category_with_children():
    from django.db import transaction

    from apps.common.rls import bind_db_tenant
    from apps.common.tenant_context import use_tenant

    m = MembershipFactory()
    with use_tenant(m.tenant_id, actor_id=m.user_id), transaction.atomic():
        bind_db_tenant(m.tenant_id)
        parent = services.create_category(name="Food", kind="expense", currency="USD")
        services.create_category(name="Groceries", kind="expense", currency="USD", parent=parent)

    client = _client(m.user, m.tenant_id)
    resp = client.delete(f"/api/v1/finance/categories/{parent.id}/")
    assert resp.status_code == 422
    assert "sub-categor" in resp.json()["detail"].lower()


def test_reparent_category():
    m = MembershipFactory()
    client = _client(m.user, m.tenant_id)
    parent = client.post(
        "/api/v1/finance/categories/",
        {"name": "Food", "kind": "expense", "currency": "USD"},
        format="json",
    ).json()
    child = client.post(
        "/api/v1/finance/categories/",
        {"name": "Snacks", "kind": "expense", "currency": "USD"},
        format="json",
    ).json()
    assert child["parent_id"] is None

    resp = client.patch(
        f"/api/v1/finance/categories/{child['id']}/", {"parent_id": parent["id"]}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["parent_id"] == parent["id"]
    assert body["depth"] == 1
    assert body["path"] == f"{parent['path']}.snacks"

    # and back to top-level
    resp = client.patch(f"/api/v1/finance/categories/{child['id']}/", {"parent_id": None}, format="json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["parent_id"] is None
    assert body["depth"] == 0
    assert body["path"] == "snacks"


def test_cannot_reparent_category_to_itself():
    from django.db import transaction

    from apps.common.rls import bind_db_tenant
    from apps.common.tenant_context import use_tenant

    m = MembershipFactory()
    with use_tenant(m.tenant_id, actor_id=m.user_id), transaction.atomic():
        bind_db_tenant(m.tenant_id)
        category = services.create_category(name="Food", kind="expense", currency="USD")

    client = _client(m.user, m.tenant_id)
    resp = client.patch(
        f"/api/v1/finance/categories/{category.id}/", {"parent_id": str(category.id)}, format="json"
    )
    assert resp.status_code == 422
    assert "own parent" in resp.json()["detail"].lower()


def test_cannot_reparent_category_under_its_own_descendant():
    from django.db import transaction

    from apps.common.rls import bind_db_tenant
    from apps.common.tenant_context import use_tenant

    m = MembershipFactory()
    with use_tenant(m.tenant_id, actor_id=m.user_id), transaction.atomic():
        bind_db_tenant(m.tenant_id)
        parent = services.create_category(name="Food", kind="expense", currency="USD")
        child = services.create_category(name="Groceries", kind="expense", currency="USD", parent=parent)

    client = _client(m.user, m.tenant_id)
    resp = client.patch(
        f"/api/v1/finance/categories/{parent.id}/", {"parent_id": str(child.id)}, format="json"
    )
    assert resp.status_code == 422
    assert "descendant" in resp.json()["detail"].lower()


def test_cannot_reparent_across_kinds():
    from django.db import transaction

    from apps.common.rls import bind_db_tenant
    from apps.common.tenant_context import use_tenant

    m = MembershipFactory()
    with use_tenant(m.tenant_id, actor_id=m.user_id), transaction.atomic():
        bind_db_tenant(m.tenant_id)
        income_parent = services.create_category(name="Salary", kind="income", currency="USD")
        expense_child = services.create_category(name="Rent", kind="expense", currency="USD")

    client = _client(m.user, m.tenant_id)
    resp = client.patch(
        f"/api/v1/finance/categories/{expense_child.id}/",
        {"parent_id": str(income_parent.id)},
        format="json",
    )
    assert resp.status_code == 422
    assert "kind" in resp.json()["detail"].lower()


def test_reparent_cascades_to_descendant_paths():
    from django.db import transaction

    from apps.common.rls import bind_db_tenant
    from apps.common.tenant_context import use_tenant

    m = MembershipFactory()
    with use_tenant(m.tenant_id, actor_id=m.user_id), transaction.atomic():
        bind_db_tenant(m.tenant_id)
        old_parent = services.create_category(name="Food", kind="expense", currency="USD")
        mid = services.create_category(name="Groceries", kind="expense", currency="USD", parent=old_parent)
        leaf = services.create_category(name="Produce", kind="expense", currency="USD", parent=mid)
        new_parent = services.create_category(name="Household", kind="expense", currency="USD")
        mid_id, leaf_id = mid.id, leaf.id

    client = _client(m.user, m.tenant_id)
    resp = client.patch(
        f"/api/v1/finance/categories/{mid_id}/", {"parent_id": str(new_parent.id)}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "household.groceries"
    assert body["depth"] == 1

    with use_tenant(m.tenant_id, actor_id=m.user_id), transaction.atomic():
        bind_db_tenant(m.tenant_id)
        refreshed_leaf = Category.objects.get(id=leaf_id)
        assert refreshed_leaf.path == "household.groceries.produce"
        assert refreshed_leaf.depth == 2
