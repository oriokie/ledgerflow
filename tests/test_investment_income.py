"""Income-producing investments: bonds, money-market funds and SACCO shares.

Three instruments, one distinction — **what may be projected, and what may only
be reported after the fact.** A bond's coupon is contractual and can be stated
before it happens. A money-market fund's yield is reset by its manager and a
SACCO's dividend is whatever the AGM declares; for those, last period's figure
is a measurement, and quoting it forward would be inventing a promise nobody
made.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from apps.finance import services as finance_services
from apps.finance.models import AccountType
from apps.investments import selectors, services
from apps.investments.income import PAYMENTS_PER_YEAR, coupon_schedule, realised_yield_bp
from apps.investments.models import AssetClass, IncomeKind, PaymentFrequency
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


def _brokerage(opening=100_000_000):
    return finance_services.create_financial_account(
        name="Brokerage",
        account_type=AccountType.INVESTMENT,
        currency="USD",
        opening_balance_minor=opening,
    )


def _security(symbol="BOND", asset_class=AssetClass.BOND):
    return services.create_security(
        symbol=symbol, name=f"{symbol} instrument", asset_class=asset_class, currency="USD"
    )


# ============================================================ schedule maths
def test_the_frequency_table_matches_the_model():
    """`income.py` restates it to stay free of Django; this is what stops the
    two drifting."""
    from apps.investments.models import PAYMENTS_PER_YEAR as MODEL_TABLE

    assert dict(MODEL_TABLE) == PAYMENTS_PER_YEAR


def test_a_semiannual_bond_pays_half_the_annual_rate_each_time():
    payments = coupon_schedule(
        face_value_minor=100_000,  # 1,000.00 face
        quantity=10,
        coupon_rate_bp=1200,  # 12% a year
        payment_frequency=PaymentFrequency.SEMIANNUAL,
        issued_on=date(2026, 1, 1),
        matures_on=date(2028, 1, 1),
    )
    # 1,000,000 principal at 12% = 120,000 a year = 60,000 twice a year.
    assert [p.on_date for p in payments] == [
        date(2026, 7, 1),
        date(2027, 1, 1),
        date(2027, 7, 1),
        date(2028, 1, 1),
    ]
    assert all(p.interest_minor == 60_000 for p in payments)


def test_the_principal_comes_back_at_maturity_and_only_then():
    payments = coupon_schedule(
        face_value_minor=100_000,
        quantity=10,
        coupon_rate_bp=1200,
        payment_frequency=PaymentFrequency.ANNUAL,
        issued_on=date(2026, 1, 1),
        matures_on=date(2028, 1, 1),
    )
    assert [p.principal_minor for p in payments] == [0, 1_000_000]
    assert payments[-1].is_final is True
    assert payments[-1].outstanding_minor == 0


def test_a_partial_redemption_shrinks_every_coupon_after_it():
    """The reason redemptions cannot be an afterthought.

    Interest is charged on what is still outstanding, so repaying a fifth in
    year three makes every later coupon a fifth smaller. Computing coupons off
    the original face — the obvious shortcut — overstates the income of any
    amortising bond for the rest of its life.
    """
    payments = coupon_schedule(
        face_value_minor=100_000,
        quantity=10,  # 1,000,000 principal
        coupon_rate_bp=1000,  # 10% a year
        payment_frequency=PaymentFrequency.ANNUAL,
        issued_on=date(2026, 1, 1),
        matures_on=date(2030, 1, 1),
        redemptions=[(date(2028, 1, 1), 2000)],  # 20% back in year two
    )
    by_year = {p.on_date.year: p for p in payments}

    assert by_year[2027].interest_minor == 100_000, "full principal still out"
    assert by_year[2028].principal_minor == 200_000, "the scheduled fifth comes back"
    assert by_year[2029].interest_minor == 80_000, "10% of the 800,000 still out"
    assert by_year[2030].principal_minor == 800_000, "the rest at maturity"
    assert by_year[2030].outstanding_minor == 0


def test_nothing_is_scheduled_past_maturity():
    payments = coupon_schedule(
        face_value_minor=100_000,
        quantity=1,
        coupon_rate_bp=1000,
        payment_frequency=PaymentFrequency.ANNUAL,
        issued_on=date(2020, 1, 1),
        matures_on=date(2022, 1, 1),
        from_date=date(2026, 1, 1),
    )
    assert payments == []


# ================================================= measured yield (MMF, SACCO)
def test_a_variable_yield_is_measured_from_real_distributions():
    """12 monthly payments of 1,000 on a 100,000 balance is roughly 12%."""
    bp = realised_yield_bp(
        distributions=[(date(2026, m, 1), 1_000) for m in range(1, 13)],
        average_balance_minor=100_000,
        over_days=365,
    )
    assert bp == 1200


def test_a_short_window_is_not_annualised():
    """Under a month, annualising multiplies noise by twelve."""
    assert (
        realised_yield_bp(
            distributions=[(date(2026, 1, 15), 500)],
            average_balance_minor=100_000,
            over_days=14,
        )
        is None
    )


def test_no_history_is_absent_rather_than_zero():
    """A zero would read as "this paid nothing", which is a finding. "Not
    enough history" is not."""
    assert realised_yield_bp(distributions=[], average_balance_minor=100_000, over_days=365) is None
    assert (
        realised_yield_bp(distributions=[(date(2026, 1, 1), 100)], average_balance_minor=0, over_days=365)
        is None
    )


# ================================================================== the views
def test_a_bond_reports_its_next_contracted_payment():
    with tenant_scope(uuid.uuid4()):
        account = _brokerage()
        bond = _security("TBILL", AssetClass.BOND)
        services.buy(
            financial_account=account,
            security=bond,
            quantity=Decimal("10"),
            amount_minor=1_000_000,
            occurred_on=date(2026, 1, 1),
        )
        services.set_security_terms(
            security=bond,
            income_kind=IncomeKind.COUPON,
            face_value_minor=100_000,
            coupon_rate_bp=1200,
            payment_frequency=PaymentFrequency.SEMIANNUAL,
            issued_on=date(2026, 1, 1),
            matures_on=date(2029, 1, 1),
        )

        (view,) = selectors.income_views(as_of=date(2026, 3, 1))

    assert view.income_kind == IncomeKind.COUPON
    assert view.is_projectable is True
    assert view.next_payment_on == date(2026, 7, 1)
    assert view.next_payment_minor == 60_000


def test_a_money_market_fund_is_never_projected():
    """It has a real yield; it simply is not knowable in advance."""
    with tenant_scope(uuid.uuid4()):
        account = _brokerage()
        mmf = _security("MMF", AssetClass.CASH_EQUIVALENT)
        services.buy(
            financial_account=account,
            security=mmf,
            quantity=Decimal("1000"),
            amount_minor=1_000_000,
            occurred_on=date(2026, 1, 1),
        )
        services.set_security_terms(security=mmf, income_kind=IncomeKind.VARIABLE)
        for month in (1, 2, 3):
            services.record_interest(
                financial_account=account,
                security=mmf,
                amount_minor=8_000 + month * 100,  # a rate that moves
                occurred_on=date(2026, month, 28),
            )

        (view,) = selectors.income_views(as_of=date(2026, 4, 1))

    assert view.income_kind == IncomeKind.VARIABLE
    assert view.is_projectable is False, "no schedule may be drawn from a variable rate"
    assert view.next_payment_on is None
    assert view.received_minor == 8_100 + 8_200 + 8_300
    assert view.realised_yield_bp is not None, "but what it actually paid is measurable"


def test_a_sacco_dividend_is_recorded_when_declared():
    """A rate exists, but only once the AGM has declared it."""
    with tenant_scope(uuid.uuid4()):
        account = _brokerage()
        sacco = _security("SACCO", AssetClass.OTHER)
        services.buy(
            financial_account=account,
            security=sacco,
            quantity=Decimal("500"),
            amount_minor=500_000,
            occurred_on=date(2026, 1, 1),
        )
        services.set_security_terms(
            security=sacco, income_kind=IncomeKind.DECLARED, dividend_on_average_balance=True
        )
        services.record_dividend(
            financial_account=account, security=sacco, amount_minor=60_000, occurred_on=date(2026, 3, 15)
        )

        (view,) = selectors.income_views(as_of=date(2026, 6, 1))

    assert view.income_kind == IncomeKind.DECLARED
    assert view.is_projectable is False
    assert view.received_minor == 60_000


def test_a_fixed_coupon_missing_its_terms_is_refused():
    """A schedule missing one of face, rate, frequency or maturity is not a
    partial schedule — it is a guess."""
    with tenant_scope(uuid.uuid4()):
        bond = _security("PART", AssetClass.BOND)
        with pytest.raises(services.InvestmentError) as caught:
            services.set_security_terms(
                security=bond, income_kind=IncomeKind.COUPON, face_value_minor=100_000
            )
    assert "coupon rate" in str(caught.value)


# ================================================================ redemptions
def test_redeeming_principal_is_not_a_sale():
    """Booking it as a disposal would report profit on getting your own money
    back."""
    with tenant_scope(uuid.uuid4()):
        account = _brokerage()
        bond = _security("REDEEM", AssetClass.BOND)
        services.buy(financial_account=account, security=bond, quantity=Decimal("10"), amount_minor=1_000_000)

        txn = services.record_redemption(
            financial_account=account,
            security=bond,
            amount_minor=200_000,
            quantity=Decimal("2"),
            occurred_on=date(2026, 6, 1),
        )

        from apps.investments.models import Holding

        holding = Holding.objects.get()
        assert selectors.holding_quantity(holding) == Decimal("8"), "units retired"
        # Redeemed at par: no gain, because nothing was gained.
        assert txn.realized_gain_minor is None


def test_redeeming_above_par_is_a_real_gain():
    with tenant_scope(uuid.uuid4()):
        account = _brokerage()
        bond = _security("PREM", AssetClass.BOND)
        services.buy(financial_account=account, security=bond, quantity=Decimal("10"), amount_minor=1_000_000)
        txn = services.record_redemption(financial_account=account, security=bond, amount_minor=1_050_000)
    assert txn.realized_gain_minor == 50_000


def test_redemption_money_reaches_the_cash_flow():
    """Principal coming back is money arriving — the same omission that made
    dividends invisible."""
    from datetime import datetime, timedelta

    from django.utils import timezone as dj_tz

    from apps.finance import selectors as finance_selectors

    with tenant_scope(uuid.uuid4()):
        account = _brokerage()
        bond = _security("CASHFLOW", AssetClass.BOND)
        services.buy(financial_account=account, security=bond, quantity=Decimal("10"), amount_minor=1_000_000)
        today = dj_tz.localdate()
        services.record_redemption(
            financial_account=account, security=bond, amount_minor=1_000_000, occurred_on=today
        )
        start = dj_tz.make_aware(datetime.combine(today, datetime.min.time()))
        flows = finance_selectors.cash_flow(start=start, end=start + timedelta(days=1))

    assert next(f for f in flows if f.currency == "USD").income_minor == 1_000_000


def test_a_schedule_cannot_return_more_than_the_principal():
    with tenant_scope(uuid.uuid4()):
        bond = _security("OVER", AssetClass.BOND)
        with pytest.raises(services.InvestmentError):
            services.set_redemption_schedule(
                security=bond,
                entries=[(date(2027, 1, 1), 6000), (date(2028, 1, 1), 6000)],
            )


def test_you_cannot_redeem_more_than_is_held():
    with tenant_scope(uuid.uuid4()):
        account = _brokerage()
        bond = _security("SMALL", AssetClass.BOND)
        services.buy(financial_account=account, security=bond, quantity=Decimal("2"), amount_minor=200_000)
        with pytest.raises(services.InvestmentError):
            services.record_redemption(
                financial_account=account, security=bond, amount_minor=500_000, quantity=Decimal("5")
            )
