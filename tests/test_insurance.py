"""Insurance — contract overlays that never post to the ledger.

Cover versus a house, a premium that must not double-count a bill, and the
refusal to invent a gap when either figure is missing.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from django.utils import timezone

from apps.assets import services as asset_services
from apps.assets.models import AssetKind
from apps.finance import bills as bill_services
from apps.finance import services as finance_services
from apps.finance.models import AccountType, CategoryKind
from apps.insurance import selectors, services
from apps.insurance.models import PolicyKind, PremiumFrequency
from apps.projections import adapters
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


def _policy(**kw):
    kw.setdefault("name", "Buildings cover")
    kw.setdefault("currency", "USD")
    kw.setdefault("premium_minor", 12_000_00)
    kw.setdefault("premium_frequency", PremiumFrequency.ANNUAL)
    kw.setdefault("kind", PolicyKind.HOME)
    return services.create_policy(**kw)


def test_annual_premium_is_the_run_rate_not_the_quoted_instalment():
    assert selectors.annual_premium_minor(1_000_00, PremiumFrequency.MONTHLY) == 12_000_00
    assert selectors.monthly_premium_minor(12_000_00, PremiumFrequency.ANNUAL) == 1_000_00


def test_cover_below_the_asset_is_underinsured():
    with tenant_scope(uuid.uuid4()):
        house = asset_services.create_asset(name="The house", currency="USD", kind=AssetKind.PROPERTY)
        asset_services.record_valuation(asset=house, value_minor=800_000_00, as_of=date(2026, 1, 1))
        _policy(covers_asset=house, coverage_minor=400_000_00)

        views = selectors.policy_views()
        assert views[0].underinsured
        assert views[0].coverage_gap_minor == -400_000_00
        gaps = selectors.underinsured_gaps()
        assert len(gaps) == 1
        assert gaps[0]["gap_minor"] == 400_000_00


def test_no_gap_is_invented_without_cover_or_a_valuation():
    with tenant_scope(uuid.uuid4()):
        house = asset_services.create_asset(name="The house", currency="USD", kind=AssetKind.PROPERTY)
        _policy(covers_asset=house, coverage_minor=None)
        assert selectors.policy_views()[0].coverage_gap_minor is None
        assert selectors.underinsured_gaps() == ()


def test_an_unlinked_premium_appears_on_the_cashflow_stack():
    with tenant_scope(uuid.uuid4()):
        finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=1_000_000,
        )
        _policy()
        stack = adapters.cashflow_stack(currency="USD", as_of=timezone.localdate())

    line = next(row for row in stack if row["kind"] == "insurance")
    assert line["monthly_minor"] == 1_000_00
    assert line["label"] == "Buildings cover"


def test_a_premium_linked_to_a_bill_is_not_double_counted():
    with tenant_scope(uuid.uuid4()):
        finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=1_000_000,
        )
        category = finance_services.create_category(
            name="Insurance", kind=CategoryKind.EXPENSE, currency="USD"
        )
        bill = bill_services.create_bill(
            name="Home premium",
            amount_minor=12_000_00,
            currency="USD",
            due_on=date(2027, 1, 1),
            category=category,
        )
        _policy(bill=bill)
        stack = adapters.cashflow_stack(currency="USD", as_of=timezone.localdate())

    assert not any(row["kind"] == "insurance" for row in stack)


def test_a_blank_name_or_zero_premium_is_refused():
    with tenant_scope(uuid.uuid4()):
        with pytest.raises(services.InsuranceError):
            _policy(name="  ")
        with pytest.raises(services.InsuranceError):
            _policy(name="Ok", premium_minor=0)


def test_summary_is_none_when_nothing_is_recorded():
    with tenant_scope(uuid.uuid4()):
        assert selectors.summary() is None


def test_policies_are_tenant_isolated():
    a, b = uuid.uuid4(), uuid.uuid4()
    with tenant_scope(a):
        _policy()
        assert selectors.summary() is not None
    with tenant_scope(b):
        assert selectors.summary() is None
        assert selectors.policy_views() == []


def test_api_creates_lists_and_summarises_a_policy(tenant_context):
    _, client = tenant_context
    assert client.get("/api/v1/insurance/summary/").status_code == 204

    created = client.post(
        "/api/v1/insurance/",
        {
            "name": "Buildings cover",
            "kind": "home",
            "currency": "USD",
            "premium_minor": 12_000_00,
            "premium_frequency": "annual",
            "coverage_minor": 400_000_00,
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    assert created.data["annual_premium_minor"] == 12_000_00
    assert created.data["underinsured"] is False

    listed = client.get("/api/v1/insurance/")
    assert listed.status_code == 200
    assert len(listed.data) == 1
    assert listed.data[0]["name"] == "Buildings cover"

    summary = client.get("/api/v1/insurance/summary/")
    assert summary.status_code == 200
    assert summary.data["count"] == 1
    assert summary.data["annual_premium_minor"] == 12_000_00


def test_api_refuses_a_blank_name(tenant_context):
    _, client = tenant_context
    resp = client.post(
        "/api/v1/insurance/",
        {"name": "  ", "currency": "USD", "premium_minor": 100},
        format="json",
    )
    assert resp.status_code in (400, 422)
