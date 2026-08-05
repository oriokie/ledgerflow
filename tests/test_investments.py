"""Investment tracking: lots, cost basis, realised gains, and valuation.

The tests that matter most are the accounting ones. An investment tracker whose
numbers don't reconcile to the ledger is a spreadsheet with extra steps, and the
specific ways it goes wrong are well known:

  * relieving the asset at sale price instead of cost;
  * capitalising dividends into cost basis;
  * posting unrealised gains;
  * losing lot identity by averaging on purchase.

There is a test for each.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.finance import selectors as finance_selectors
from apps.finance import services as finance_services
from apps.finance.models import AccountType
from apps.investments import selectors, services
from apps.investments.models import AssetClass, Holding, Lot, Security
from apps.ledger.models import AccountKind, Direction, LedgerLine
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return uuid.uuid4()


def _brokerage(opening: int = 1_000_000):
    return finance_services.create_financial_account(
        name="Brokerage",
        account_type=AccountType.INVESTMENT,
        currency="USD",
        opening_balance_minor=opening,
    )


def _security(symbol="ACME", asset_class=AssetClass.STOCK, sector="Technology"):
    return services.create_security(
        symbol=symbol, name=f"{symbol} Inc", asset_class=asset_class, currency="USD", sector=sector
    )


# ------------------------------------------------------------------ securities
def test_symbols_are_normalised(tenant):
    with tenant_scope(tenant):
        security = services.create_security(
            symbol="  aapl ", name="Apple", asset_class=AssetClass.STOCK, currency="usd"
        )
        # "aapl" and "AAPL" must be one security, not two.
        assert security.symbol == "AAPL"
        assert security.currency == "USD"


def test_a_duplicate_symbol_is_a_clean_error_not_a_raw_crash(tenant):
    """Regression: creating a security with a symbol that already exists (or
    normalises to one that does) used to hit the raw database constraint —
    django.db.utils.IntegrityError, an unhandled 500. Now a clean,
    actionable InvestmentError."""
    with tenant_scope(tenant):
        services.create_security(
            symbol="VTI", name="Vanguard Total Stock", asset_class=AssetClass.ETF, currency="USD"
        )
        with pytest.raises(services.InvestmentError, match="already tracked"):
            services.create_security(
                symbol="VTI", name="Duplicate", asset_class=AssetClass.ETF, currency="USD"
            )


def test_a_symbol_that_only_collides_after_normalising_is_also_caught(tenant):
    """The exact scenario that made this look like a dead button: typing
    "vti" after "VTI" already exists looks like a different symbol, but
    Security.save() uppercases both to the same string."""
    with tenant_scope(tenant):
        services.create_security(
            symbol="VTI", name="Vanguard Total Stock", asset_class=AssetClass.ETF, currency="USD"
        )
        with pytest.raises(services.InvestmentError, match="already tracked"):
            services.create_security(
                symbol="vti", name="lowercase attempt", asset_class=AssetClass.ETF, currency="USD"
            )


def test_a_retried_submission_after_a_slow_first_success_gets_the_same_clean_error(tenant):
    """The realistic sequence behind the report: a click that looks
    unresponsive gets clicked again: the first request actually succeeded,
    and the retry must not 500."""
    with tenant_scope(tenant):
        services.create_security(
            symbol="VTI", name="Vanguard Total Stock", asset_class=AssetClass.ETF, currency="USD"
        )
        with pytest.raises(services.InvestmentError):
            services.create_security(
                symbol="VTI", name="Vanguard Total Stock", asset_class=AssetClass.ETF, currency="USD"
            )
        # And the original security is untouched by the failed retry.
        assert Security.objects.filter(symbol="VTI").count() == 1


def test_different_symbols_are_unaffected(tenant):
    with tenant_scope(tenant):
        services.create_security(symbol="VTI", name="A", asset_class=AssetClass.ETF, currency="USD")
        services.create_security(symbol="VOO", name="B", asset_class=AssetClass.ETF, currency="USD")
        assert Security.objects.count() == 2


def test_unknown_asset_class_is_rejected(tenant):
    with tenant_scope(tenant), pytest.raises(services.InvestmentError):
        services.create_security(symbol="X", name="X", asset_class="magic_beans", currency="USD")


def test_all_required_asset_classes_are_supported():
    values = set(AssetClass.values)
    assert {
        "stock",
        "etf",
        "mutual_fund",
        "bond",
        "crypto",
        "cash_equivalent",
    } <= values


# --------------------------------------------------------------------- buying
def test_buying_posts_a_balanced_entry_and_creates_a_lot(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()

        txn = services.buy(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=50_000,
            fee_minor=500,
            occurred_on=date(2026, 1, 15),
        )

        lines = list(LedgerLine.objects.filter(entry=txn.journal_entry))
        assert len(lines) == 2
        debits = sum(line.amount_minor for line in lines if line.direction == Direction.DEBIT)
        credits = sum(line.amount_minor for line in lines if line.direction == Direction.CREDIT)
        # Fees are capitalised: what you paid to acquire it is part of its cost.
        assert debits == credits == 50_500

        lot = Lot.objects.get()
        assert lot.quantity == Decimal("10")
        assert lot.cost_minor == 50_500
        assert lot.quantity_remaining == Decimal("10")


def test_buying_debits_investments_and_credits_cash(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        txn = services.buy(
            financial_account=account, security=security, quantity=Decimal("5"), amount_minor=25_000
        )

        asset_line = LedgerLine.objects.get(
            entry=txn.journal_entry, account__kind=AccountKind.ASSET, direction=Direction.DEBIT
        )
        cash_line = LedgerLine.objects.get(entry=txn.journal_entry, account_id=account.ledger_account_id)
        assert asset_line.amount_minor == 25_000
        assert cash_line.direction == Direction.CREDIT


def test_separate_purchases_keep_their_own_lots(tenant):
    """Averaging on purchase loses tax facts that cannot be reconstructed."""
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=50_000,
            occurred_on=date(2026, 1, 10),
        )
        services.buy(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=80_000,
            occurred_on=date(2026, 3, 10),
        )

        lots = list(Lot.objects.order_by("acquired_on"))
        assert len(lots) == 2
        assert [lot.cost_minor for lot in lots] == [50_000, 80_000]

        holding = Holding.objects.get()
        assert holding.quantity == Decimal("20")
        assert selectors.holding_cost_basis_minor(holding) == 130_000


def test_buying_rejects_bad_input(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        for kwargs in (
            {"quantity": Decimal("0"), "amount_minor": 100},
            {"quantity": Decimal("-1"), "amount_minor": 100},
            {"quantity": Decimal("1"), "amount_minor": 0},
        ):
            with pytest.raises(services.InvestmentError):
                services.buy(financial_account=account, security=security, **kwargs)


def test_currency_mismatch_is_refused_rather_than_guessed(tenant):
    """A GBP account holding a USD security needs an FX policy this module
    doesn't have. Refusing is honest; inventing a rate is not."""
    with tenant_scope(tenant):
        gbp_account = finance_services.create_financial_account(
            name="UK Brokerage", account_type=AccountType.INVESTMENT, currency="GBP"
        )
        usd_security = _security()
        with pytest.raises(services.InvestmentError):
            services.buy(
                financial_account=gbp_account,
                security=usd_security,
                quantity=Decimal("1"),
                amount_minor=1_000,
            )


# --------------------------------------------------------------------- selling
def test_selling_relieves_the_asset_at_cost_not_at_sale_price(tenant):
    """The single most common way an investment tracker stops reconciling."""
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=50_000,
            occurred_on=date(2026, 1, 10),
        )

        txn = services.sell(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=80_000,
            occurred_on=date(2026, 6, 10),
        )

        asset_line = LedgerLine.objects.get(
            entry=txn.journal_entry, account__kind=AccountKind.ASSET, direction=Direction.CREDIT
        )
        # Credited at the 50,000 it cost — not the 80,000 it sold for.
        assert asset_line.amount_minor == 50_000
        assert txn.realized_gain_minor == 30_000


def test_a_sale_posts_a_balanced_entry_including_the_gain(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account, security=security, quantity=Decimal("10"), amount_minor=50_000
        )
        txn = services.sell(
            financial_account=account, security=security, quantity=Decimal("10"), amount_minor=80_000
        )

        lines = list(LedgerLine.objects.filter(entry=txn.journal_entry))
        debits = sum(line.amount_minor for line in lines if line.direction == Direction.DEBIT)
        credits = sum(line.amount_minor for line in lines if line.direction == Direction.CREDIT)
        assert debits == credits
        # Gain is booked to income, where it belongs.
        assert any(line.account.kind == AccountKind.INCOME for line in lines)


def test_a_loss_debits_the_gain_account(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account, security=security, quantity=Decimal("10"), amount_minor=80_000
        )
        txn = services.sell(
            financial_account=account, security=security, quantity=Decimal("10"), amount_minor=50_000
        )

        assert txn.realized_gain_minor == -30_000
        income_line = LedgerLine.objects.get(entry=txn.journal_entry, account__kind=AccountKind.INCOME)
        # One account nets both directions, so "realised gains" is a single
        # meaningful figure rather than two to subtract.
        assert income_line.direction == Direction.DEBIT
        assert income_line.amount_minor == 30_000


def test_fifo_consumes_the_oldest_lot_first(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=50_000,
            occurred_on=date(2026, 1, 10),
        )
        services.buy(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=80_000,
            occurred_on=date(2026, 3, 10),
        )

        txn = services.sell(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=90_000,
            occurred_on=date(2026, 6, 10),
        )

        # Against the 50,000 lot, not the 80,000 one, and not an average.
        assert txn.realized_gain_minor == 40_000
        lots = list(Lot.objects.order_by("acquired_on"))
        assert lots[0].quantity_remaining == Decimal("0")
        assert lots[1].quantity_remaining == Decimal("10")


def test_a_partial_sale_pro_rates_the_lot_cost(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account, security=security, quantity=Decimal("10"), amount_minor=50_000
        )
        txn = services.sell(
            financial_account=account, security=security, quantity=Decimal("4"), amount_minor=30_000
        )

        # 4/10 of a 50,000 lot is 20,000 of cost.
        assert txn.realized_gain_minor == 10_000
        lot = Lot.objects.get()
        assert lot.quantity_remaining == Decimal("6")
        assert lot.cost_remaining_minor == 30_000


def test_selling_more_than_held_is_refused(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(financial_account=account, security=security, quantity=Decimal("5"), amount_minor=25_000)
        with pytest.raises(services.InvestmentError, match="short by"):
            services.sell(
                financial_account=account,
                security=security,
                quantity=Decimal("10"),
                amount_minor=60_000,
            )


def test_selling_without_a_holding_is_refused(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        with pytest.raises(services.InvestmentError):
            services.sell(
                financial_account=account,
                security=security,
                quantity=Decimal("1"),
                amount_minor=1_000,
            )


# ------------------------------------------------------------------ dividends
def test_dividends_are_income_not_cost_basis(tenant):
    """Capitalising a dividend understates every subsequent gain."""
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account, security=security, quantity=Decimal("10"), amount_minor=50_000
        )
        before = selectors.holding_cost_basis_minor(Holding.objects.get())

        txn = services.record_dividend(financial_account=account, security=security, amount_minor=1_200)

        assert selectors.holding_cost_basis_minor(Holding.objects.get()) == before
        income_line = LedgerLine.objects.get(entry=txn.journal_entry, account__kind=AccountKind.INCOME)
        assert income_line.direction == Direction.CREDIT
        assert income_line.amount_minor == 1_200


def test_dividend_increases_the_cash_balance(tenant):
    with tenant_scope(tenant):
        account = _brokerage(opening=100_000)
        security = _security()
        services.record_dividend(financial_account=account, security=security, amount_minor=5_000)
        assert finance_selectors.account_current_balance_minor(account) == 105_000


# ---------------------------------------------------------------------- splits
def test_a_split_changes_units_without_moving_money(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account, security=security, quantity=Decimal("10"), amount_minor=50_000
        )
        cash_before = finance_selectors.account_current_balance_minor(account)

        txn = services.apply_split(financial_account=account, security=security, ratio=Decimal("2"))

        holding = Holding.objects.get()
        assert holding.quantity == Decimal("20")
        # Same money, more units: cost basis is unchanged and nothing posted.
        assert selectors.holding_cost_basis_minor(holding) == 50_000
        assert finance_selectors.account_current_balance_minor(account) == cash_before
        assert txn.journal_entry is None


# ------------------------------------------------------------------- valuation
def test_market_value_uses_the_latest_quote(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account, security=security, quantity=Decimal("10"), amount_minor=50_000
        )
        services.record_price(security=security, price_minor=6_000, as_of=date(2026, 5, 1))
        services.record_price(security=security, price_minor=7_500, as_of=date(2026, 6, 1))

        [valuation] = selectors.holding_valuations(as_of=date(2026, 6, 15))
        assert valuation.price_minor == 7_500
        assert valuation.market_value_minor == 75_000
        assert valuation.unrealized_gain_minor == 25_000
        assert valuation.unrealized_gain_pct == 50.0


def test_an_unpriced_holding_reports_no_value_rather_than_zero(tenant):
    """A zero would read as a wipeout; the absence is the honest answer."""
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account, security=security, quantity=Decimal("10"), amount_minor=50_000
        )

        [valuation] = selectors.holding_valuations()
        assert valuation.price_minor is None
        assert valuation.market_value_minor is None
        assert valuation.unrealized_gain_minor is None
        assert valuation.is_priced is False


def test_unrealised_gains_are_never_posted_to_the_ledger(tenant):
    """The whole basis of the design: the ledger holds cost, not opinion."""
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account, security=security, quantity=Decimal("10"), amount_minor=50_000
        )
        entries_before = LedgerLine.objects.count()

        services.record_price(security=security, price_minor=20_000)

        assert LedgerLine.objects.count() == entries_before
        # The gain is real in the report and absent from the books, correctly.
        [valuation] = selectors.holding_valuations()
        assert valuation.unrealized_gain_minor == 150_000


# ------------------------------------------------------------------ allocation
def test_asset_allocation_splits_by_class(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        stock = _security("ACME", AssetClass.STOCK)
        crypto = _security("BTC", AssetClass.CRYPTO)

        services.buy(financial_account=account, security=stock, quantity=Decimal("10"), amount_minor=50_000)
        services.buy(financial_account=account, security=crypto, quantity=Decimal("1"), amount_minor=50_000)
        services.record_price(security=stock, price_minor=7_500)
        services.record_price(security=crypto, price_minor=25_000)

        slices = {s.label: s for s in selectors.asset_allocation()}
        assert slices["Stocks"].market_value_minor == 75_000
        assert slices["Crypto"].market_value_minor == 25_000
        assert slices["Stocks"].percent == 75.0


def test_sector_allocation_groups_unclassified_securities(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = services.create_security(
            symbol="MYSTERY", name="Mystery", asset_class=AssetClass.STOCK, currency="USD"
        )
        services.buy(financial_account=account, security=security, quantity=Decimal("1"), amount_minor=10_000)
        services.record_price(security=security, price_minor=10_000)

        [slice_] = selectors.sector_allocation()
        assert slice_.label == "Unclassified"


def test_unpriced_holdings_are_excluded_from_allocation(tenant):
    """Counting them as zero would inflate every other slice while the pie
    still summed to 100%."""
    with tenant_scope(tenant):
        account = _brokerage()
        priced = _security("PRICED", AssetClass.STOCK)
        unpriced = _security("UNPRICED", AssetClass.CRYPTO)

        services.buy(financial_account=account, security=priced, quantity=Decimal("1"), amount_minor=10_000)
        services.buy(financial_account=account, security=unpriced, quantity=Decimal("1"), amount_minor=10_000)
        services.record_price(security=priced, price_minor=10_000)

        slices = selectors.asset_allocation()
        assert len(slices) == 1
        assert slices[0].percent == 100.0


# --------------------------------------------------------------------- summary
def test_portfolio_summary_separates_the_four_kinds_of_gain(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()

        services.buy(
            financial_account=account,
            security=security,
            quantity=Decimal("20"),
            amount_minor=100_000,
            occurred_on=date(2026, 1, 10),
        )
        services.sell(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=80_000,
            occurred_on=date(2026, 3, 10),
        )
        services.record_dividend(financial_account=account, security=security, amount_minor=2_000)
        services.record_price(security=security, price_minor=9_000)

        summary = selectors.portfolio_summary()
        assert summary is not None
        assert summary.cost_basis_minor == 50_000  # 10 units left
        assert summary.market_value_minor == 90_000
        assert summary.unrealized_gain_minor == 40_000  # paper
        assert summary.realized_gain_minor == 30_000  # booked
        assert summary.dividend_income_minor == 2_000  # income
        assert summary.total_return_minor == 72_000


def test_summary_is_none_without_holdings(tenant):
    with tenant_scope(tenant):
        # An all-zero summary would look like a portfolio that lost everything.
        assert selectors.portfolio_summary() is None


def test_summary_reports_how_many_holdings_are_unpriced(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        a = _security("AAA")
        b = _security("BBB")
        services.buy(financial_account=account, security=a, quantity=Decimal("1"), amount_minor=10_000)
        services.buy(financial_account=account, security=b, quantity=Decimal("1"), amount_minor=10_000)
        services.record_price(security=a, price_minor=12_000)

        summary = selectors.portfolio_summary()
        # So the UI can say the total is partial rather than complete.
        assert summary.unpriced_count == 1
        assert summary.holding_count == 2


def test_a_valuation_carries_the_date_its_price_was_taken(tenant):
    """Quotes are entered by hand, so a "market value" is only as current as
    the last time someone typed a number in. The selector used to discard the
    quote's date, leaving the UI no way to tell this morning's valuation from
    one taken in March — and it renders both under "what it's worth today"."""
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(financial_account=account, security=security, quantity=Decimal("1"), amount_minor=10_000)
        old_day = timezone.localdate() - timedelta(days=140)
        services.record_price(security=security, price_minor=12_000, as_of=old_day)

        [valuation] = selectors.holding_valuations()
        assert valuation.price_minor == 12_000
        assert valuation.priced_as_of == old_day

        summary = selectors.portfolio_summary()
        assert summary.priced_as_of == old_day
        assert summary.stale_count == 1


def test_the_total_is_dated_by_its_stalest_input(tenant):
    """The oldest quote, not the newest. Reporting the newest would let one
    symbol updated this morning present a portfolio last valued in March as
    today's worth — which is the precise overstatement this field exists to
    prevent."""
    with tenant_scope(tenant):
        account = _brokerage()
        fresh, stale = _security("FRSH"), _security("STAL")
        for security in (fresh, stale):
            services.buy(
                financial_account=account,
                security=security,
                quantity=Decimal("1"),
                amount_minor=10_000,
            )
        today = timezone.localdate()
        old_day = today - timedelta(days=90)
        services.record_price(security=fresh, price_minor=12_000, as_of=today)
        services.record_price(security=stale, price_minor=9_000, as_of=old_day)

        summary = selectors.portfolio_summary()
        assert summary.priced_as_of == old_day
        assert summary.stale_count == 1


def test_prices_taken_today_are_not_reported_as_stale(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(financial_account=account, security=security, quantity=Decimal("1"), amount_minor=10_000)
        services.record_price(security=security, price_minor=12_000)

        summary = selectors.portfolio_summary()
        assert summary.priced_as_of == timezone.localdate()
        assert summary.stale_count == 0


# ------------------------------------------------------------- net worth link
def test_net_worth_carries_investments_at_cost(tenant):
    """The ledger stays at book value; the market-value overlay is separate."""
    with tenant_scope(tenant):
        account = _brokerage(opening=100_000)
        security = _security()
        services.buy(
            financial_account=account, security=security, quantity=Decimal("10"), amount_minor=50_000
        )
        services.record_price(security=security, price_minor=20_000)

        usd = next(n for n in finance_selectors.net_worth() if n.currency == "USD")
        # 100,000 opening: 50,000 still cash, 50,000 now an investment asset.
        assert usd.assets_minor == 100_000

        # The adjustment needed to present market value instead.
        assert selectors.unrealized_gain_for_net_worth(currency="USD") == 150_000


def test_the_net_worth_adjustment_ignores_unpriced_holdings(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account, security=security, quantity=Decimal("10"), amount_minor=50_000
        )
        # Never claims a gain on a position nobody has valued.
        assert selectors.unrealized_gain_for_net_worth(currency="USD") == 0


# ------------------------------------------------------------------- history
def test_valuation_history_omits_months_with_no_prices(tenant):
    """A line dropping to the axis reads as a loss, not as missing data."""
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=50_000,
            occurred_on=timezone.localdate() - timedelta(days=5),
        )
        services.record_price(security=security, price_minor=6_000)

        points = selectors.valuation_history(months=6)
        assert points, "expected at least the current month"
        assert all(p.market_value_minor > 0 for p in points)


def test_dividend_income_is_summarised_per_security(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        a = _security("AAA")
        b = _security("BBB")
        services.record_dividend(financial_account=account, security=a, amount_minor=3_000)
        services.record_dividend(financial_account=account, security=b, amount_minor=1_000)

        summary = selectors.dividend_income()
        assert summary.total_minor == 4_000
        assert summary.by_security[0]["symbol"] == "AAA"


def test_dividend_summary_is_none_when_there_are_none(tenant):
    with tenant_scope(tenant):
        assert selectors.dividend_income() is None


# ------------------------------------------------------------------------ API
def test_api_a_duplicate_symbol_is_a_422_not_a_500(tenant_context):
    """The exact bug reported in production: submitting a symbol that already
    exists crashed with an unhandled IntegrityError, which the frontend saw
    as a request that never came back — indistinguishable from a dead
    button."""
    _, client = tenant_context
    first = client.post(
        "/api/v1/investments/securities/",
        {"symbol": "VTI", "name": "Vanguard Total Stock", "asset_class": "etf", "currency": "USD"},
        format="json",
    )
    assert first.status_code == 201, first.data

    duplicate = client.post(
        "/api/v1/investments/securities/",
        {"symbol": "VTI", "name": "Duplicate", "asset_class": "etf", "currency": "USD"},
        format="json",
    )
    assert duplicate.status_code == 422
    assert "already tracked" in duplicate.data["detail"]


def test_api_a_case_only_difference_is_still_caught_as_a_duplicate(tenant_context):
    _, client = tenant_context
    client.post(
        "/api/v1/investments/securities/",
        {"symbol": "VTI", "name": "Vanguard Total Stock", "asset_class": "etf", "currency": "USD"},
        format="json",
    )
    resp = client.post(
        "/api/v1/investments/securities/",
        {"symbol": "vti", "name": "lowercase", "asset_class": "etf", "currency": "USD"},
        format="json",
    )
    assert resp.status_code == 422


def _api_setup(client):
    account = client.post(
        "/api/v1/finance/accounts/",
        {
            "name": "Brokerage",
            "account_type": "investment",
            "currency": "USD",
            "opening_balance_minor": 1_000_000,
        },
        format="json",
    ).data
    security = client.post(
        "/api/v1/investments/securities/",
        {
            "symbol": "acme",
            "name": "Acme Inc",
            "asset_class": "stock",
            "currency": "USD",
            "sector": "Technology",
        },
        format="json",
    ).data
    return account, security


def test_api_buy_sell_and_portfolio_round_trip(tenant_context):
    _, client = tenant_context
    account, security = _api_setup(client)
    assert security["symbol"] == "ACME"

    buy = client.post(
        "/api/v1/investments/trade/buy/",
        {
            "financial_account_id": account["id"],
            "security_id": security["id"],
            "quantity": "10",
            "amount_minor": 50_000,
        },
        format="json",
    )
    assert buy.status_code == 201, buy.data

    client.post(
        "/api/v1/investments/prices/",
        {"security_id": security["id"], "price_minor": 7_500},
        format="json",
    )

    holdings = client.get("/api/v1/investments/holdings/").data
    assert holdings[0]["market_value_minor"] == 75_000
    assert holdings[0]["unrealized_gain_minor"] == 25_000

    sell = client.post(
        "/api/v1/investments/trade/sell/",
        {
            "financial_account_id": account["id"],
            "security_id": security["id"],
            "quantity": "5",
            "amount_minor": 40_000,
        },
        format="json",
    )
    assert sell.status_code == 201, sell.data
    assert sell.data["realized_gain_minor"] == 15_000

    portfolio = client.get("/api/v1/investments/portfolio/").data
    assert portfolio["realized_gain_minor"] == 15_000
    assert portfolio["asset_allocation"][0]["label"] == "Stocks"
    assert portfolio["sector_allocation"][0]["label"] == "Technology"


def test_api_portfolio_is_204_without_holdings(tenant_context):
    _, client = tenant_context
    assert client.get("/api/v1/investments/portfolio/").status_code == 204


def test_api_rejects_an_unknown_trade_action(tenant_context):
    _, client = tenant_context
    account, security = _api_setup(client)
    resp = client.post(
        "/api/v1/investments/trade/short/",
        {
            "financial_account_id": account["id"],
            "security_id": security["id"],
            "quantity": "1",
            "amount_minor": 100,
        },
        format="json",
    )
    assert resp.status_code == 400


def test_api_overselling_returns_a_clear_error(tenant_context):
    _, client = tenant_context
    account, security = _api_setup(client)
    client.post(
        "/api/v1/investments/trade/buy/",
        {
            "financial_account_id": account["id"],
            "security_id": security["id"],
            "quantity": "1",
            "amount_minor": 5_000,
        },
        format="json",
    )
    resp = client.post(
        "/api/v1/investments/trade/sell/",
        {
            "financial_account_id": account["id"],
            "security_id": security["id"],
            "quantity": "99",
            "amount_minor": 5_000,
        },
        format="json",
    )
    assert resp.status_code == 422
    assert "short by" in resp.data["detail"]


def test_api_dividend_and_summary(tenant_context):
    _, client = tenant_context
    account, security = _api_setup(client)
    resp = client.post(
        "/api/v1/investments/dividends/record/",
        {"financial_account_id": account["id"], "security_id": security["id"], "amount_minor": 2_500},
        format="json",
    )
    assert resp.status_code == 201, resp.data

    summary = client.get("/api/v1/investments/dividends/").data
    assert summary["total_minor"] == 2_500
    assert summary["by_security"][0]["symbol"] == "ACME"


# ------------------------------------------------- historical cost correctness
def test_historical_cost_reflects_the_position_as_it_stood(tenant):
    """Regression guard for an approximation.

    Reading each lot's *current* remaining quantity would report a
    since-sold position as having cost nothing, making the cost line on the
    performance chart sag toward zero in exactly the months a user was
    invested.
    """
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        holding_date = date(2026, 1, 10)
        services.buy(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=50_000,
            occurred_on=holding_date,
        )
        # Sold entirely, later.
        services.sell(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=80_000,
            occurred_on=date(2026, 6, 10),
        )

        # In February the position was fully held and had cost 50,000.
        assert selectors._cost_at(Holding.objects.get(), date(2026, 2, 1)) == 50_000
        # After the sale, nothing remains.
        assert selectors._cost_at(Holding.objects.get(), date(2026, 7, 1)) == 0


def test_historical_cost_handles_a_partial_sale(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=50_000,
            occurred_on=date(2026, 1, 10),
        )
        services.sell(
            financial_account=account,
            security=security,
            quantity=Decimal("4"),
            amount_minor=40_000,
            occurred_on=date(2026, 5, 10),
        )
        holding = Holding.objects.get()

        assert selectors._cost_at(holding, date(2026, 3, 1)) == 50_000
        # 6 of 10 units left, so 30,000 of the original cost.
        assert selectors._cost_at(holding, date(2026, 6, 1)) == 30_000


def test_historical_cost_consumes_lots_fifo(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=50_000,
            occurred_on=date(2026, 1, 10),
        )
        services.buy(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=90_000,
            occurred_on=date(2026, 3, 10),
        )
        services.sell(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=100_000,
            occurred_on=date(2026, 5, 10),
        )
        holding = Holding.objects.get()

        # The cheap lot went first, so the expensive one remains.
        assert selectors._cost_at(holding, date(2026, 6, 1)) == 90_000
        # Before the second purchase, only the first lot existed.
        assert selectors._cost_at(holding, date(2026, 2, 1)) == 50_000


def test_historical_cost_agrees_with_current_cost_basis(tenant):
    """The replayed figure and the live one must not disagree about today."""
    with tenant_scope(tenant):
        account = _brokerage()
        security = _security()
        services.buy(
            financial_account=account,
            security=security,
            quantity=Decimal("10"),
            amount_minor=50_000,
            occurred_on=date(2026, 1, 10),
        )
        services.sell(
            financial_account=account,
            security=security,
            quantity=Decimal("3"),
            amount_minor=30_000,
            occurred_on=date(2026, 5, 10),
        )
        holding = Holding.objects.get()
        today = timezone.localdate()

        assert selectors._cost_at(holding, today) == selectors.holding_cost_basis_minor(holding)


def test_net_worth_api_returns_book_and_market_value_separately(tenant_context):
    """One is what the books say, the other what the market says. Folding them
    together would put an unposted gain into the ledger figure."""
    _, client = tenant_context
    account = client.post(
        "/api/v1/finance/accounts/",
        {
            "name": "Brokerage",
            "account_type": "investment",
            "currency": "USD",
            "opening_balance_minor": 100_000,
        },
        format="json",
    ).data
    security = client.post(
        "/api/v1/investments/securities/",
        {"symbol": "ACME", "name": "Acme", "asset_class": "stock", "currency": "USD"},
        format="json",
    ).data

    client.post(
        "/api/v1/investments/trade/buy/",
        {
            "financial_account_id": account["id"],
            "security_id": security["id"],
            "quantity": "10",
            "amount_minor": 50_000,
        },
        format="json",
    )
    client.post(
        "/api/v1/investments/prices/",
        {"security_id": security["id"], "price_minor": 20_000},
        format="json",
    )

    usd = next(r for r in client.get("/api/v1/finance/net-worth/").data if r["currency"] == "USD")
    # Book value: 50,000 cash + 50,000 investment at cost.
    assert usd["assets_minor"] == 100_000
    # Market overlay: the position is now worth 200,000.
    assert usd["unrealized_gain_minor"] == 150_000
    assert usd["market_assets_minor"] == 250_000
    assert usd["market_net_minor"] == 250_000


def test_net_worth_overlay_is_zero_without_investments(tenant_context):
    _, client = tenant_context
    client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD", "opening_balance_minor": 100_000},
        format="json",
    )
    usd = next(r for r in client.get("/api/v1/finance/net-worth/").data if r["currency"] == "USD")
    assert usd["unrealized_gain_minor"] == 0
    assert usd["market_net_minor"] == usd["net_minor"]


# ------------------------------------------------------------------- interest
def test_interest_from_an_mmf_or_bond_is_recorded_against_the_holding(tenant):
    """`InvestmentTransactionType.INTEREST` existed but nothing could create one.

    A money-market fund or a bond pays periodically — that is the whole point of
    holding one — and there was no way to record it against the security that
    generated it.
    """
    from apps.investments.models import InvestmentTransaction, InvestmentTransactionType

    with tenant_scope(tenant):
        account = _brokerage()
        mmf = _security(symbol="MMF", asset_class=AssetClass.CASH_EQUIVALENT, sector="")
        services.buy(
            financial_account=account, security=mmf, quantity=Decimal("1000"), amount_minor=100_000
        )
        before = selectors.holding_cost_basis_minor(Holding.objects.get())

        txn = services.record_interest(financial_account=account, security=mmf, amount_minor=850)

        assert txn.txn_type == InvestmentTransactionType.INTEREST
        assert InvestmentTransaction.objects.filter(
            txn_type=InvestmentTransactionType.INTEREST
        ).count() == 1
        # Interest is a return *on* the investment, never added to its cost.
        assert selectors.holding_cost_basis_minor(Holding.objects.get()) == before

        income_line = LedgerLine.objects.get(entry=txn.journal_entry, account__kind=AccountKind.INCOME)
        assert income_line.direction == Direction.CREDIT
        assert income_line.amount_minor == 850
        # Booked apart from dividends: taxed and reported differently.
        assert "Investment interest" in income_line.account.name


def test_investment_income_reaches_the_cash_flow(tenant):
    """It used to move the balance but appear in no cash-flow figure.

    Dividends and interest posted a journal entry and nothing else, while cash
    flow, the transaction list and every income total read `finance.Transaction`
    — so the money arrived invisibly.
    """
    from datetime import datetime

    with tenant_scope(tenant):
        account = _brokerage()
        mmf = _security(symbol="MMF", asset_class=AssetClass.CASH_EQUIVALENT, sector="")
        equity = _security(symbol="ACME")
        services.buy(
            financial_account=account, security=mmf, quantity=Decimal("1000"), amount_minor=100_000
        )
        services.buy(
            financial_account=account, security=equity, quantity=Decimal("10"), amount_minor=50_000
        )

        today = timezone.localdate()
        services.record_interest(
            financial_account=account, security=mmf, amount_minor=850, occurred_on=today
        )
        services.record_dividend(
            financial_account=account, security=equity, amount_minor=1_200, occurred_on=today
        )

        start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
        end = start + timedelta(days=1)
        flows = finance_selectors.cash_flow(start=start, end=end)

    usd = next(f for f in flows if f.currency == "USD")
    assert usd.income_minor == 2_050, "both the coupon and the dividend are income"


def test_recording_the_same_interest_payment_twice_posts_it_once(tenant):
    """Idempotency has to cover the domain row as well as the ledger entry, or
    a retried request doubles the income without doubling the balance."""
    with tenant_scope(tenant):
        account = _brokerage()
        mmf = _security(symbol="MMF", asset_class=AssetClass.CASH_EQUIVALENT, sector="")
        services.buy(
            financial_account=account, security=mmf, quantity=Decimal("1000"), amount_minor=100_000
        )
        on = date(2026, 3, 31)
        for _ in range(2):
            services.record_interest(
                financial_account=account, security=mmf, amount_minor=850, occurred_on=on
            )

        from apps.finance.models import Transaction as FinanceTransaction

        assert FinanceTransaction.objects.filter(amount_minor=850).count() == 1


def test_interest_is_refused_when_it_is_not_positive(tenant):
    with tenant_scope(tenant):
        account = _brokerage()
        mmf = _security(symbol="MMF", asset_class=AssetClass.CASH_EQUIVALENT, sector="")
        with pytest.raises(services.InvestmentError):
            services.record_interest(financial_account=account, security=mmf, amount_minor=0)
