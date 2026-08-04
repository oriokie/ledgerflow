"""Liquidity journeys: the cashflow statement (monthly in/out/net + ending
liquid balance) and the cash-runway forecast ("will I run out of cash?")."""

from __future__ import annotations

import contextlib
from datetime import timedelta

import pytest
from django.db import transaction as db_tx
from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import BillingInterval, Plan, PlanTier
from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant
from apps.finance import services as fin

pytestmark = pytest.mark.django_db


@contextlib.contextmanager
def _ctx(membership):
    with db_tx.atomic(), use_tenant(membership.tenant_id, membership.user_id):
        bind_db_tenant(membership.tenant_id)
        yield


def _seed_history(membership, monthly_income=500_000, monthly_expense=650_000, months=3):
    """An account plus `months` full months of income/spending history."""
    with _ctx(membership):
        acct = fin.create_financial_account(name="Checking", account_type="checking", currency="USD")
        cat_in = fin.create_category(name="Pay", kind="income", currency="USD")
        cat_out = fin.create_category(name="Life", kind="expense", currency="USD")
        now = timezone.now()
        for m in range(1, months + 1):
            when = now.replace(day=15) - timedelta(days=30 * m)
            fin.record_income(
                financial_account=acct,
                category=cat_in,
                amount_minor=monthly_income,
                occurred_at=when,
                memo=f"salary {m}",
            )
            fin.record_expense(
                financial_account=acct,
                category=cat_out,
                amount_minor=monthly_expense,
                occurred_at=when + timedelta(days=1),
                memo=f"living {m}",
            )
    return acct


def test_cashflow_statement_rows_and_ending_balance(tenant_context):
    membership, client = tenant_context
    _seed_history(membership, monthly_income=500_000, monthly_expense=300_000, months=3)

    res = client.get("/api/v1/finance/cashflow-statement/?months=6")
    assert res.status_code == 200, res.data
    body = res.data
    assert body["currency"] == "USD"
    # Net +2000.00/mo for 3 months → liquid balance 6000.00
    assert body["liquid_balance_minor"] == 600_000
    rows = body["rows"]
    assert len(rows) == 6
    # Newest row's ending balance equals today's liquid balance.
    assert rows[-1]["ending_balance_minor"] == 600_000
    active = [r for r in rows if r["inflow_minor"]]
    assert len(active) == 3
    for r in active:
        assert r["net_minor"] == 200_000
    # Ending balances step by the month's true movement.
    assert rows[0]["ending_balance_minor"] in (0, 200_000)


def test_cashflow_statement_empty_workspace(tenant_context):
    _, client = tenant_context
    res = client.get("/api/v1/finance/cashflow-statement/")
    assert res.status_code == 200
    assert res.data["rows"] == [] and res.data["currency"] is None


def test_cash_runway_critical_when_burning(tenant_context):
    membership, client = tenant_context
    # Income 5000, spend 6500 → burn 1500/mo; balance after 3 months = -4500?
    # Use income>expense start buffer instead: 3 months of +2000 then compute burn via mixed:
    _seed_history(membership, monthly_income=500_000, monthly_expense=650_000, months=3)

    res = client.get("/api/v1/intelligence/cash-runway/")
    assert res.status_code == 200, res.data
    body = res.data
    assert body["avg_monthly_net_minor"] == -150_000
    # Balance is negative already → months_of_runway <= 0 → critical.
    assert body["status"] == "critical"
    assert body["projected_runout_date"] is not None


def test_cash_runway_healthy_when_saving(tenant_context):
    membership, client = tenant_context
    _seed_history(membership, monthly_income=700_000, monthly_expense=300_000, months=3)
    res = client.get("/api/v1/intelligence/cash-runway/")
    assert res.status_code == 200
    assert res.data["status"] == "healthy"
    assert res.data["months_of_runway"] is None  # not burning


def test_cash_runway_insufficient_data(tenant_context):
    _, client = tenant_context
    res = client.get("/api/v1/intelligence/cash-runway/")
    assert res.status_code == 200
    assert res.data["status"] == "insufficient_data"


def test_cash_runway_gated_like_other_ai_features(tenant_context):
    membership, client = tenant_context
    no_ai = Plan.objects.create(
        tier=PlanTier.FREE,
        name="Free",
        price_minor=0,
        currency="USD",
        interval=BillingInterval.MONTHLY,
        max_accounts=3,
        max_members=1,
        ai_insights=False,
    )
    billing.subscribe(tenant_id=membership.tenant_id, plan=no_ai)
    assert client.get("/api/v1/intelligence/cash-runway/").status_code == 402
