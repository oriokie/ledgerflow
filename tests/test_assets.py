"""Assets — the things you own that you do not transact through.

For most households the house and the car are the two largest numbers on the
balance sheet, and a net worth that omits them is not net worth. The tests that
matter most are about *value between valuations*: a house is looked at every few
years and the chart draws a point every month, so almost every figure the
product shows is one nobody typed.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from apps.assets import selectors, services
from apps.assets.models import Asset, AssetKind, ValuationSource
from apps.finance import services as finance_services
from apps.finance.models import AccountType
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


def _house(**kw):
    kw.setdefault("name", "The house")
    kw.setdefault("currency", "USD")
    kw.setdefault("kind", AssetKind.PROPERTY)
    return services.create_asset(**kw)


# ============================================================== interpolation
def test_value_between_two_valuations_is_interpolated():
    """A house valued at 6m in 2022 and 8m in 2026 was, as far as anyone can
    honestly say, worth about 7m in 2024. A step function would instead show
    four flat years and a sudden jump in one month — a claim about *when* the
    value changed that nobody made."""
    with tenant_scope(uuid.uuid4()):
        asset = _house()
        services.record_valuation(asset=asset, value_minor=600_000_00, as_of=date(2022, 1, 1))
        services.record_valuation(asset=asset, value_minor=800_000_00, as_of=date(2026, 1, 1))

        midpoint = selectors.value_at(asset, date(2024, 1, 1))

    # Four years, 200,000 of growth; two years in is roughly half.
    assert 698_000_00 <= midpoint <= 702_000_00


def test_value_after_the_last_valuation_is_held_flat_never_extrapolated():
    """The important one. Continuing the trend past the last real figure would
    invent growth nobody measured, and it would compound — this chart drawn
    today would show a different past than the same chart drawn next year."""
    with tenant_scope(uuid.uuid4()):
        asset = _house()
        services.record_valuation(asset=asset, value_minor=600_000_00, as_of=date(2022, 1, 1))
        services.record_valuation(asset=asset, value_minor=800_000_00, as_of=date(2024, 1, 1))

        assert selectors.value_at(asset, date(2026, 1, 1)) == 800_000_00
        assert selectors.value_at(asset, date(2030, 1, 1)) == 800_000_00


def test_value_before_the_first_valuation_reaches_back_to_what_it_cost():
    with tenant_scope(uuid.uuid4()):
        asset = _house(acquired_on=date(2020, 1, 1), acquisition_cost_minor=400_000_00)
        services.record_valuation(asset=asset, value_minor=800_000_00, as_of=date(2024, 1, 1))

        midpoint = selectors.value_at(asset, date(2022, 1, 1))

    # Four years from 400k to 800k; halfway is about 600k.
    assert 598_000_00 <= midpoint <= 602_000_00


def test_an_asset_is_worth_nothing_before_it_was_acquired():
    with tenant_scope(uuid.uuid4()):
        asset = _house(acquired_on=date(2020, 1, 1), acquisition_cost_minor=400_000_00)
        services.record_valuation(asset=asset, value_minor=800_000_00, as_of=date(2024, 1, 1))

        assert selectors.value_at(asset, date(2019, 6, 1)) == 0


def test_an_unvalued_asset_with_no_cost_contributes_nothing():
    """Never a guess. The same refusal the health score makes about data it
    does not have."""
    with tenant_scope(uuid.uuid4()):
        asset = _house()
        assert selectors.value_at(asset, date(2026, 1, 1)) == 0
        assert selectors.total_value_minor(currency="USD") == 0


def test_a_single_valuation_applies_in_both_directions():
    """One point is a horizontal line, not a slope through the origin."""
    with tenant_scope(uuid.uuid4()):
        asset = _house()
        services.record_valuation(asset=asset, value_minor=500_000_00, as_of=date(2024, 1, 1))

        assert selectors.value_at(asset, date(2020, 1, 1)) == 500_000_00
        assert selectors.value_at(asset, date(2026, 1, 1)) == 500_000_00


# ================================================================== the views
def test_equity_is_the_gap_between_worth_and_owed():
    """The reason the debt link exists: "worth 8m, owing 5m, your equity is 3m"
    is a different and better statement than two unrelated figures."""
    with tenant_scope(uuid.uuid4()):
        mortgage = finance_services.create_financial_account(
            name="Mortgage",
            account_type=AccountType.LOAN,
            currency="USD",
            opening_balance_minor=500_000_00,
        )
        _house(secured_by_debt=mortgage, initial_value_minor=800_000_00)

        (view,) = selectors.asset_views()

    assert view.value_minor == 800_000_00
    assert view.debt_minor == 500_000_00
    assert view.equity_minor == 300_000_00
    assert view.loan_to_value_pct == 62.5


def test_equity_is_absent_while_the_asset_is_unvalued():
    """The figure is the gap between two known numbers, and one is missing."""
    with tenant_scope(uuid.uuid4()):
        _house()
        (view,) = selectors.asset_views()
    assert view.value_minor is None
    assert view.equity_minor is None
    assert view.loan_to_value_pct is None


def test_an_asset_owned_outright_reports_no_ratio():
    """0% would be a different statement from "nothing is owed on this"."""
    with tenant_scope(uuid.uuid4()):
        _house(initial_value_minor=800_000_00)
        (view,) = selectors.asset_views()
    assert view.debt_minor == 0
    assert view.loan_to_value_pct is None


def test_summary_is_absent_rather_than_zeroed_when_nothing_is_recorded():
    with tenant_scope(uuid.uuid4()):
        assert selectors.summary() is None


def test_summary_reports_what_is_still_unvalued():
    """They are the reason the total is lower than the household expects."""
    with tenant_scope(uuid.uuid4()):
        _house(name="Valued", initial_value_minor=800_000_00)
        _house(name="Not valued")

        result = selectors.summary()

    assert result.value_minor == 800_000_00
    assert result.count == 2
    assert result.unvalued_count == 1


def test_an_asset_can_be_left_out_of_net_worth():
    """A car held for a relative, a property owned with others."""
    with tenant_scope(uuid.uuid4()):
        _house(initial_value_minor=800_000_00, include_in_net_worth=False)
        assert selectors.total_value_minor(currency="USD") == 0


# ================================================================== the rules
def test_a_second_valuation_on_one_day_replaces_the_first():
    """Two judgements about the same day are a correction, not two data points
    — and keeping both would let the interpolation draw a line between a figure
    and its own correction."""
    with tenant_scope(uuid.uuid4()):
        asset = _house()
        services.record_valuation(asset=asset, value_minor=700_000_00, as_of=date(2026, 1, 1))
        services.record_valuation(
            asset=asset, value_minor=750_000_00, as_of=date(2026, 1, 1), source=ValuationSource.PROFESSIONAL
        )

        assert asset.valuations.count() == 1
        assert selectors.value_at(asset, date(2026, 1, 1)) == 750_000_00


def test_an_asset_cannot_be_valued_before_it_was_acquired():
    with tenant_scope(uuid.uuid4()):
        asset = _house(acquired_on=date(2024, 1, 1))
        with pytest.raises(services.AssetError):
            services.record_valuation(asset=asset, value_minor=1, as_of=date(2023, 1, 1))


def test_only_a_liability_can_secure_an_asset():
    """An asset "secured by" a savings account is meaningless, and would put
    nonsense into every equity figure derived from it."""
    with tenant_scope(uuid.uuid4()):
        savings = finance_services.create_financial_account(
            name="Savings", account_type=AccountType.SAVINGS, currency="USD"
        )
        with pytest.raises(services.AssetError):
            _house(secured_by_debt=savings)


def test_the_currency_cannot_be_changed():
    with tenant_scope(uuid.uuid4()):
        asset = _house()
        with pytest.raises(services.AssetError):
            services.update_asset(asset=asset, currency="KES")


def test_assets_are_tenant_isolated():
    """The closest thing the product holds to a statement of wealth."""
    a, b = uuid.uuid4(), uuid.uuid4()
    with tenant_scope(a):
        _house(initial_value_minor=800_000_00)
        assert Asset.objects.count() == 1
    with tenant_scope(b):
        assert Asset.objects.count() == 0
        assert selectors.summary() is None


# ============================================================ net worth wiring
def test_assets_reach_net_worth_as_an_overlay(tenant_context):
    """Not a ledger balance: their worth changes because somebody re-estimated
    it, not because money moved."""
    membership, client = tenant_context
    client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD", "opening_balance_minor": 100_000},
        format="json",
    )
    created = client.post(
        "/api/v1/assets/",
        {"name": "The house", "kind": "property", "currency": "USD", "initial_value_minor": 800_000_00},
        format="json",
    )
    assert created.status_code == 201, created.data

    row = client.get("/api/v1/finance/net-worth/").data[0]
    assert row["assets_minor"] == 100_000, "the ledger half is untouched"
    assert row["asset_value_minor"] == 800_000_00
    assert row["market_net_minor"] == row["net_minor"] + 800_000_00


def test_the_history_interpolates_assets_between_valuations(tenant_context):
    """The chart draws a point every month; a house is valued every few years."""
    from apps.intelligence.selectors import net_worth_history

    membership, client = tenant_context
    with tenant_scope(membership.tenant_id):
        finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=100_000,
        )
        asset = _house(acquired_on=date(2020, 1, 1), acquisition_cost_minor=400_000_00)
        services.record_valuation(asset=asset, value_minor=800_000_00, as_of=date(2024, 1, 1))

        series = net_worth_history(months=3, as_of=date(2026, 6, 30))

    # Past the last valuation, so every point is held flat — not extrapolated.
    assert all(point["asset_value_minor"] == 800_000_00 for point in series)
    assert all(point["assets_minor"] >= 800_000_00 for point in series)
