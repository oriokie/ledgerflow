"""#4 editable base currency + #5 currency catalog / FX conversion."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.fx import services as fx
from apps.fx.currencies import is_supported

pytestmark = pytest.mark.django_db


def test_currency_catalog_endpoint(auth_client):
    res = auth_client.get("/api/v1/fx/currencies/")
    assert res.status_code == 200
    codes = {c["code"] for c in res.data}
    assert {"USD", "EUR", "KES", "JPY"} <= codes
    jpy = next(c for c in res.data if c["code"] == "JPY")
    assert jpy["digits"] == 0  # yen has no minor unit


def test_convert_uses_seeded_rates(auth_client):
    # 100.00 USD -> EUR at seeded 0.92 = 92.00
    res = auth_client.get("/api/v1/fx/convert/?amount_minor=10000&from=USD&to=EUR")
    assert res.status_code == 200
    assert res.data["converted_minor"] == 9200


def test_convert_triangulates_through_usd():
    # EUR -> GBP has no direct pair; triangulate via USD (1/0.92 * 0.79).
    got = fx.convert(amount_minor=10000, from_currency="EUR", to_currency="GBP")
    assert got is not None
    assert 8000 < got < 9000  # ~85.87


def test_convert_same_currency_is_identity():
    assert fx.convert(amount_minor=500, from_currency="USD", to_currency="USD") == 500


def test_convert_unknown_pair_returns_none():
    assert fx.latest_rate("USD", "XZY") is None


def test_manual_rate_upsert_then_convert():
    fx.upsert_rate(base="USD", quote="AAA", rate=Decimal("2"), source="manual")
    assert fx.convert(amount_minor=100, from_currency="USD", to_currency="AAA") == 200


def test_convert_rejects_unsupported_currency(auth_client):
    res = auth_client.get("/api/v1/fx/convert/?amount_minor=100&from=USD&to=ZZZ")
    assert res.status_code == 400


# ---------------------------------------------------------------- #4 base ccy

def test_owner_can_change_base_currency(tenant_context):
    membership, client = tenant_context
    res = client.patch(
        f"/api/v1/tenancy/workspaces/{membership.tenant_id}/",
        {"base_currency": "eur"},
        format="json",
    )
    assert res.status_code == 200, res.data
    assert res.data["base_currency"] == "EUR"
    membership.tenant.refresh_from_db()
    assert membership.tenant.base_currency == "EUR"


def test_invalid_base_currency_rejected(tenant_context):
    membership, client = tenant_context
    res = client.patch(
        f"/api/v1/tenancy/workspaces/{membership.tenant_id}/",
        {"base_currency": "ZZZ"},
        format="json",
    )
    assert res.status_code == 400


def test_non_owner_cannot_change_settings(tenant_context, user):
    from apps.tenancy import services as tsvc
    from apps.tenancy.models import Role
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    membership, _ = tenant_context
    tsvc.add_member(tenant=membership.tenant, user=user, role=Role.VIEWER)
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
                  HTTP_X_TENANT_ID=str(membership.tenant_id))
    res = c.patch(f"/api/v1/tenancy/workspaces/{membership.tenant_id}/", {"base_currency": "EUR"}, format="json")
    assert res.status_code == 403


# --------------------------------------------------- consolidated net worth

def test_net_worth_in_base_consolidates_currencies(tenant_context):
    """Mixed-currency holdings roll up into the workspace base via FX."""
    import contextlib
    from django.db import transaction as db_tx
    from django.utils import timezone

    from apps.common.rls import bind_db_tenant
    from apps.common.tenant_context import use_tenant
    from apps.finance import services as fin

    membership, client = tenant_context

    @contextlib.contextmanager
    def ctx():
        with db_tx.atomic(), use_tenant(membership.tenant_id, membership.user_id):
            bind_db_tenant(membership.tenant_id)
            yield

    with ctx():
        cat = fin.create_category(name="Pay", kind="income", currency="USD")
        usd = fin.create_financial_account(name="US", account_type="checking", currency="USD")
        eur = fin.create_financial_account(name="EU", account_type="checking", currency="EUR")
        fin.record_income(financial_account=usd, category=cat, amount_minor=100_00,
                          occurred_at=timezone.now(), memo="usd")
        fin.record_income(financial_account=eur, category=cat, amount_minor=100_00,
                          occurred_at=timezone.now(), memo="eur")

    res = client.get("/api/v1/finance/net-worth/base/")
    assert res.status_code == 200, res.data
    assert res.data["base_currency"] == "USD"
    assert res.data["converted"] is True
    assert res.data["currency_count"] == 2
    # 100 USD + 100 EUR@(1/0.92 ≈ 1.087) ≈ 208.70 USD
    assert 20_500 < res.data["total_minor"] < 21_500
