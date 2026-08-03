"""Getting Started journey: a brand-new workspace must arrive with a starter
set of categories so the owner can log their first transaction immediately."""

from __future__ import annotations

import pytest

from apps.tenancy.services import DEFAULT_CATEGORIES

pytestmark = pytest.mark.django_db


def test_new_workspace_is_seeded_with_default_categories(auth_client):
    res = auth_client.post(
        "/api/v1/tenancy/workspaces/",
        {"name": "Fresh", "type": "personal", "base_currency": "USD"},
        format="json",
    )
    assert res.status_code == 201, res.data
    tenant_id = res.data["tenant"]["id"]

    listing = auth_client.get("/api/v1/finance/categories/", HTTP_X_TENANT_ID=str(tenant_id))
    assert listing.status_code == 200
    names = {c["name"] for c in listing.data}
    for cat_name, _kind in DEFAULT_CATEGORIES:
        assert cat_name in names, f"{cat_name} missing from seeded categories"
    kinds = {c["kind"] for c in listing.data}
    assert {"expense", "income"} <= kinds
