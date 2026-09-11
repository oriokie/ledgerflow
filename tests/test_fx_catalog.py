"""The operator-maintained currency catalog, live rates, and ISO-digit conversion."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.fx import catalog, services as fx
from apps.fx.currencies import is_known, is_supported, list_currencies
from apps.fx.models import Currency
from apps.fx.providers import RateProviderError
from apps.platform_admin.rbac import PlatformRole
from tests.test_platform_admin_rbac import client_for, make_staff

pytestmark = pytest.mark.django_db

BASE = "/api/v1/platform/currencies"


def test_seeded_catalog_is_what_users_see(auth_client):
    res = auth_client.get("/api/v1/fx/currencies/")
    assert res.status_code == 200
    codes = {c["code"] for c in res.data}
    assert {"USD", "EUR", "KES", "JPY"} <= codes
    jpy = next(c for c in res.data if c["code"] == "JPY")
    assert jpy["digits"] == 0


def test_inactive_currency_drops_out_of_the_picker_but_stays_known():
    Currency.objects.filter(pk="ZAR").update(is_active=False)
    assert not is_supported("ZAR")
    assert is_known("ZAR")
    assert "ZAR" not in {c.code for c in list_currencies(active_only=True)}
    assert "ZAR" in {c.code for c in list_currencies(active_only=False)}


def test_convert_respects_minor_unit_digits():
    # 100.00 USD at 157 JPY per USD is 15,700 yen, not 1,570,000 "cents".
    yen = fx.convert(amount_minor=10_000, from_currency="USD", to_currency="JPY")
    assert yen == 15_700


def test_convert_same_scale_pair_is_unchanged(auth_client):
    res = auth_client.get("/api/v1/fx/convert/?amount_minor=10000&from=USD&to=EUR")
    assert res.status_code == 200
    assert res.data["converted_minor"] == 9200


def test_admin_lists_workspace_and_billing_apart_from_usd_quote():
    client = client_for(make_staff(PlatformRole.FINANCE))
    res = client.get(f"{BASE}/")
    assert res.status_code == 200
    kes = next(row for row in res.data if row["code"] == "KES")
    assert kes["usd_rate"] is not None
    assert kes["is_active"] is True


def test_auditor_can_read_the_catalog_but_cannot_write_a_rate():
    client = client_for(make_staff(PlatformRole.AUDITOR))
    assert client.get(f"{BASE}/").status_code == 200
    res = client.post(
        f"{BASE}/KES/rate/",
        {"rate": "130.5", "reason": "Pinned the morning fix"},
        format="json",
    )
    assert res.status_code == 403


def test_finance_can_add_a_currency_and_set_its_rate():
    client = client_for(make_staff(PlatformRole.FINANCE))
    created = client.post(
        f"{BASE}/",
        {
            "code": "rwf",
            "name": "Rwandan Franc",
            "symbol": "FRw",
            "digits": 0,
            "usd_rate": "1450",
            "reason": "Customers in Kigali asked for books in francs.",
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    assert created.data["code"] == "RWF"
    assert created.data["digits"] == 0
    assert Decimal(created.data["usd_rate"]) == Decimal("1450")
    assert is_supported("RWF")


def test_deactivating_hides_the_code_from_the_user_catalog(auth_client):
    staff = client_for(make_staff(PlatformRole.ADMIN))
    res = staff.patch(
        f"{BASE}/ARS/",
        {"is_active": False, "reason": "The official rate is unusable for books."},
        format="json",
    )
    assert res.status_code == 200, res.data
    codes = {c["code"] for c in auth_client.get("/api/v1/fx/currencies/").data}
    assert "ARS" not in codes


def test_manual_rate_is_left_alone_by_an_unforced_refresh():
    fx.upsert_rate(base="USD", quote="KES", rate=Decimal("200"), source="manual")
    with patch("apps.fx.providers.fetch_usd_rates", return_value=({"KES": Decimal("129")}, "er-api")):
        result = fx.refresh_rates(force=False)
    assert result["skipped_manual"] >= 1
    latest = fx.latest_rate("USD", "KES")
    assert latest == Decimal("200")


def test_forced_refresh_replaces_a_manual_rate():
    fx.upsert_rate(base="USD", quote="KES", rate=Decimal("200"), source="manual")
    with patch("apps.fx.providers.fetch_usd_rates", return_value=({"KES": Decimal("129")}, "er-api")):
        result = fx.refresh_rates(force=True)
    assert result["updated"] >= 1
    assert fx.latest_rate("USD", "KES") == Decimal("129")


def test_refresh_endpoint_records_an_audit_row():
    from apps.platform_admin.models import PlatformAuditLog

    client = client_for(make_staff(PlatformRole.OWNER))
    with patch(
        "apps.fx.providers.fetch_usd_rates",
        return_value=({"EUR": Decimal("0.91")}, "er-api"),
    ):
        res = client.post(
            "/api/v1/platform/fx/refresh/",
            {"reason": "Morning rates before the board pack.", "force": False},
            format="json",
        )
    assert res.status_code == 200, res.data
    assert PlatformAuditLog.objects.filter(action="fx.rates.refreshed").exists()


def test_refresh_surfaces_a_dead_feed():
    client = client_for(make_staff(PlatformRole.OWNER))
    with patch("apps.fx.providers.fetch_usd_rates", side_effect=RateProviderError("down")):
        res = client.post(
            "/api/v1/platform/fx/refresh/",
            {"reason": "Checking the feed after an outage."},
            format="json",
        )
    assert res.status_code == 502
