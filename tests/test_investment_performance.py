"""Modified Dietz, volatility and drawdown — honest with sparse manual quotes."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.finance import services as finance_services
from apps.finance.models import AccountType
from apps.investments import performance, services
from apps.investments.models import AssetClass
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


def _brokerage(opening: int = 1_000_000):
    return finance_services.create_financial_account(
        name="Brokerage",
        account_type=AccountType.INVESTMENT,
        currency="USD",
        opening_balance_minor=opening,
    )


def test_performance_is_none_without_holdings():
    with tenant_scope(uuid.uuid4()):
        assert performance.portfolio_performance() is None


def test_a_rising_price_with_no_cash_flow_is_a_positive_dietz_return():
    """No contributions, a higher quote: the whole change is performance."""
    today = timezone.localdate()
    earlier = (today.replace(day=1) - timedelta(days=1)).replace(day=15)
    with tenant_scope(uuid.uuid4()):
        account = _brokerage()
        security = services.create_security(
            symbol="ACME", name="Acme", asset_class=AssetClass.STOCK, currency="USD"
        )
        services.buy(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=10_000,
            occurred_on=earlier,
        )
        services.record_price(security=security, price_minor=1_000, as_of=earlier)
        services.record_price(security=security, price_minor=1_200, as_of=today)

        result = performance.portfolio_performance(months=12)

    assert result is not None
    assert result.modified_dietz is not None
    assert result.modified_dietz > 0
    assert result.max_drawdown is not None
    assert result.max_drawdown <= 0


def test_expense_ratio_is_stored_and_weights_the_portfolio_ter():
    today = timezone.localdate()
    with tenant_scope(uuid.uuid4()):
        account = _brokerage()
        cheap = services.create_security(
            symbol="VTI",
            name="VTI",
            asset_class=AssetClass.ETF,
            currency="USD",
            expense_ratio_bp=3,
        )
        dear = services.create_security(
            symbol="FUND",
            name="Active",
            asset_class=AssetClass.MUTUAL_FUND,
            currency="USD",
            expense_ratio_bp=100,
        )
        services.buy(financial_account=account, security=cheap, quantity=Decimal("1"), amount_minor=75_000)
        services.buy(financial_account=account, security=dear, quantity=Decimal("1"), amount_minor=25_000)
        services.record_price(security=cheap, price_minor=75_000, as_of=today)
        services.record_price(security=dear, price_minor=25_000, as_of=today)

        from apps.investments.selectors import weighted_expense_ratio

        ter = weighted_expense_ratio()

    # 75% at 3bp + 25% at 100bp = 27.25bp → 0.002725
    assert ter is not None
    assert abs(ter - 0.002725) < 1e-9


def test_api_performance_is_204_without_holdings(tenant_context):
    _, client = tenant_context
    assert client.get("/api/v1/investments/portfolio/performance/").status_code == 204
