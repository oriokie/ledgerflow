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
    resp = client.patch(
        f"/api/v1/finance/categories/{created['id']}/", {"name": "Food"}, format="json"
    )
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
    from apps.common.tenant_context import use_tenant
    from apps.common.rls import bind_db_tenant
    from django.db import transaction

    with use_tenant(m.tenant_id):
        with transaction.atomic():
            bind_db_tenant(m.tenant_id)
            assert not Category.objects.filter(id=created["id"]).exists()


def test_cannot_delete_category_in_use():
    from apps.finance import services as fin
    from apps.common.tenant_context import use_tenant
    from apps.common.rls import bind_db_tenant
    from django.db import transaction
    from django.utils import timezone

    m = MembershipFactory()
    # build an account + category + a transaction using that category
    with use_tenant(m.tenant_id, actor_id=m.user_id):
        with transaction.atomic():
            bind_db_tenant(m.tenant_id)
            account = fin.create_financial_account(
                name="Checking", account_type="checking", currency="USD"
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
    from apps.common.tenant_context import use_tenant
    from apps.common.rls import bind_db_tenant
    from django.db import transaction

    m = MembershipFactory()
    with use_tenant(m.tenant_id, actor_id=m.user_id):
        with transaction.atomic():
            bind_db_tenant(m.tenant_id)
            parent = services.create_category(name="Food", kind="expense", currency="USD")
            services.create_category(name="Groceries", kind="expense", currency="USD", parent=parent)

    client = _client(m.user, m.tenant_id)
    resp = client.delete(f"/api/v1/finance/categories/{parent.id}/")
    assert resp.status_code == 422
    assert "sub-categor" in resp.json()["detail"].lower()
