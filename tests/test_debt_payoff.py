"""Debt payoff engine — the arithmetic, tested directly.

These exercise the pure simulator with no database at all. The cases that
matter most are the ones a naive implementation gets wrong:

  * charging interest after applying payment (understates payoff time);
  * looping forever when a minimum doesn't cover the interest;
  * losing the rollover, so payments never accelerate;
  * overpaying on the final month.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.debt import payoff

START = date(2026, 1, 15)


def _debt(debt_id, balance, apr, minimum, name=None, priority=100):
    return payoff.DebtInput(
        debt_id=debt_id,
        name=name or debt_id,
        balance_minor=balance,
        apr=Decimal(str(apr)),
        minimum_payment_minor=minimum,
        custom_priority=priority,
    )


# --------------------------------------------------------------------- basics
def test_a_zero_interest_debt_clears_in_the_obvious_number_of_months():
    # 1,000.00 at 0% paying 100.00/month is exactly 10 months. If this is
    # wrong, nothing else can be right.
    plan = payoff.simulate([_debt("a", 100_000, 0, 10_000)], start=START)
    assert plan.months_to_debt_free == 10
    assert plan.total_interest_minor == 0
    assert plan.total_paid_minor == 100_000


def test_no_debts_is_already_debt_free():
    plan = payoff.simulate([], start=START)
    assert plan.months_to_debt_free == 0
    assert plan.is_complete


def test_interest_is_charged_before_the_payment_is_applied():
    """Reversing this understates payoff time by months on a real balance."""
    plan = payoff.simulate([_debt("a", 100_000, 12, 10_000)], start=START)
    first = plan.months[0].payments[0]

    # 1% of 1,000.00 is 10.00 charged before anything is paid.
    assert first.interest_minor == 1_000
    assert first.principal_minor == 9_000
    assert first.balance_after_minor == 91_000


def test_the_final_payment_settles_exactly_without_overpaying():
    plan = payoff.simulate([_debt("a", 25_000, 0, 10_000)], start=START)
    last = plan.months[-1].payments[0]
    # 250.00 over three months at 100.00 leaves 50.00, not a 100.00 payment.
    assert last.payment_minor == 5_000
    assert last.balance_after_minor == 0
    assert plan.total_paid_minor == 25_000


def test_interest_makes_a_debt_cost_more_than_its_balance():
    plan = payoff.simulate([_debt("a", 500_000, 20, 25_000)], start=START)
    assert plan.total_paid_minor > 500_000
    assert plan.total_interest_minor > 0
    assert plan.total_paid_minor == 500_000 + plan.total_interest_minor


# ------------------------------------------------------------------- ordering
def test_avalanche_targets_the_highest_rate_first():
    debts = [
        _debt("low", 100_000, 5, 5_000, name="Low rate"),
        _debt("high", 200_000, 24, 5_000, name="High rate"),
    ]
    assert [d.debt_id for d in payoff.order_debts(debts, "avalanche")] == ["high", "low"]


def test_snowball_targets_the_smallest_balance_first():
    debts = [
        _debt("big", 500_000, 24, 5_000, name="Big"),
        _debt("small", 50_000, 5, 5_000, name="Small"),
    ]
    assert [d.debt_id for d in payoff.order_debts(debts, "snowball")] == ["small", "big"]


def test_custom_order_follows_the_user_priority():
    debts = [
        _debt("a", 100_000, 20, 5_000, priority=3),
        _debt("b", 200_000, 5, 5_000, priority=1),
    ]
    assert [d.debt_id for d in payoff.order_debts(debts, "custom")] == ["b", "a"]


def test_ordering_is_deterministic_on_ties():
    """A schedule that reshuffles between page loads is not a schedule."""
    debts = [
        _debt("z", 100_000, 10, 5_000, name="Zebra"),
        _debt("a", 100_000, 10, 5_000, name="Apple"),
    ]
    first = [d.debt_id for d in payoff.order_debts(debts, "avalanche")]
    second = [d.debt_id for d in payoff.order_debts(list(reversed(debts)), "avalanche")]
    assert first == second == ["a", "z"]


def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError):
        payoff.order_debts([_debt("a", 1000, 5, 100)], "wishful_thinking")


# ------------------------------------------------------------------- rollover
def test_a_cleared_debts_minimum_rolls_into_the_next():
    """The whole mechanic. Without it, payments never accelerate."""
    debts = [
        _debt("small", 20_000, 0, 10_000, name="Small"),
        _debt("big", 100_000, 0, 10_000, name="Big"),
    ]
    plan = payoff.simulate(debts, strategy="snowball", start=START)

    # Small clears in month 2, freeing its 100.00.
    small = next(p for p in plan.per_debt if p.debt_id == "small")
    assert small.months_to_clear == 2

    # From month 3 the big debt receives the full 200.00 budget, not 100.00.
    month_three = plan.months[2]
    big_payment = next(p for p in month_three.payments if p.debt_id == "big")
    assert big_payment.payment_minor == 20_000


def test_the_monthly_budget_stays_constant_throughout():
    debts = [
        _debt("a", 30_000, 0, 10_000),
        _debt("b", 60_000, 0, 10_000),
    ]
    plan = payoff.simulate(debts, strategy="snowball", extra_monthly_minor=5_000, start=START)
    assert plan.monthly_budget_minor == 25_000

    # Every month except the last spends the whole budget.
    for month in plan.months[:-1]:
        assert month.total_paid_minor == 25_000


def test_extra_payment_shortens_the_plan():
    debts = [_debt("a", 500_000, 18, 15_000)]
    without = payoff.simulate(debts, start=START)
    with_extra = payoff.simulate(debts, extra_monthly_minor=20_000, start=START)

    assert with_extra.months_to_debt_free < without.months_to_debt_free
    assert with_extra.total_interest_minor < without.total_interest_minor


# ---------------------------------------------------------------- impossible
def test_a_minimum_below_the_interest_is_reported_not_looped():
    """A real situation for people in trouble, and the honest answer is that
    this debt never clears — not a 40-year schedule."""
    # 5,000.00 at 24% accrues 100.00/month; a 50.00 minimum never touches it.
    plan = payoff.simulate([_debt("stuck", 500_000, 24, 5_000)], start=START)

    assert plan.months_to_debt_free is None
    assert plan.is_complete is False
    assert "stuck" in plan.stuck_debt_ids
    assert plan.per_debt[0].never_clears is True
    # And it stopped early rather than grinding to the cap.
    assert len(plan.months) < payoff.MAX_MONTHS


def test_a_stuck_debt_still_clears_with_enough_extra():
    debts = [_debt("stuck", 500_000, 24, 5_000)]
    assert payoff.simulate(debts, start=START).months_to_debt_free is None

    rescued = payoff.simulate(debts, extra_monthly_minor=20_000, start=START)
    assert rescued.months_to_debt_free is not None
    assert rescued.stuck_debt_ids == []


def test_one_stuck_debt_does_not_stop_the_others_progressing():
    debts = [
        _debt("payable", 20_000, 0, 10_000, name="Payable"),
        _debt("stuck", 500_000, 24, 5_000, name="Stuck"),
    ]
    plan = payoff.simulate(debts, strategy="snowball", start=START)
    payable = next(p for p in plan.per_debt if p.debt_id == "payable")
    # The payable one is targeted first and clears normally.
    assert payable.months_to_clear is not None


# ----------------------------------------------------------------- comparison
def test_avalanche_never_costs_more_interest_than_snowball():
    """Mathematically guaranteed, and worth pinning: if this ever fails the
    ordering has broken."""
    debts = [
        _debt("small_high", 80_000, 26, 5_000, name="Small high-rate"),
        _debt("big_low", 400_000, 4, 10_000, name="Big low-rate"),
    ]
    results = {
        c.strategy: c for c in payoff.compare_strategies(debts, extra_monthly_minor=20_000, start=START)
    }
    assert results["avalanche"].total_interest_minor <= results["snowball"].total_interest_minor


def test_snowball_can_clear_a_first_debt_sooner():
    """The trade-off snowball is actually making — worth showing, not hiding."""
    debts = [
        _debt("tiny_low", 15_000, 3, 3_000, name="Tiny low-rate"),
        _debt("big_high", 600_000, 25, 15_000, name="Big high-rate"),
    ]
    results = {
        c.strategy: c for c in payoff.compare_strategies(debts, extra_monthly_minor=10_000, start=START)
    }
    assert results["snowball"].first_cleared_months <= results["avalanche"].first_cleared_months
    assert results["snowball"].first_cleared_name == "Tiny low-rate"


def test_savings_are_measured_against_doing_nothing():
    """Comparing strategies to each other would flatter whichever came second."""
    debts = [_debt("a", 300_000, 20, 10_000)]
    results = {
        c.strategy: c for c in payoff.compare_strategies(debts, extra_monthly_minor=15_000, start=START)
    }
    assert results["avalanche"].interest_saved_minor > 0
    assert results["avalanche"].months_saved > 0


def test_no_extra_payment_means_nothing_saved():
    debts = [_debt("a", 300_000, 20, 10_000)]
    results = {c.strategy: c for c in payoff.compare_strategies(debts, start=START)}
    # Nothing changed, so claiming a saving would be false.
    assert results["avalanche"].interest_saved_minor == 0
    assert results["avalanche"].months_saved == 0


# ---------------------------------------------------------------------- curve
def test_the_extra_payment_curve_shows_diminishing_returns():
    debts = [_debt("a", 500_000, 18, 15_000)]
    curve = payoff.extra_payment_curve(debts, steps=(0, 10_000, 20_000, 40_000), start=START)

    assert curve[0]["interest_saved_minor"] == 0
    months = [c["months_to_debt_free"] for c in curve]
    # More money is never worse.
    assert months == sorted(months, reverse=True)
    # The first increment buys more than the last — the point of the curve.
    first_gain = months[0] - months[1]
    last_gain = months[2] - months[3]
    assert first_gain >= last_gain


# ------------------------------------------------------------------- calendar
def test_month_dates_are_calendar_safe():
    # Adding a month to 31 January must land on 28/29 February, not 3 March.
    assert payoff.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert payoff.add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert payoff.add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)


def test_the_schedule_carries_a_date_for_every_month():
    plan = payoff.simulate([_debt("a", 50_000, 0, 10_000)], start=date(2026, 1, 31))
    assert [m.as_of for m in plan.months][:2] == [date(2026, 2, 28), date(2026, 3, 31)]


def test_per_debt_totals_reconcile_with_the_plan_total():
    debts = [
        _debt("a", 100_000, 12, 10_000),
        _debt("b", 200_000, 6, 10_000),
    ]
    plan = payoff.simulate(debts, extra_monthly_minor=10_000, start=START)

    assert sum(p.total_paid_minor for p in plan.per_debt) == plan.total_paid_minor
    assert sum(p.interest_paid_minor for p in plan.per_debt) == plan.total_interest_minor


# =============================================================================
# Integration: ledger balances + stored terms
# =============================================================================
import uuid  # noqa: E402

from apps.debt import selectors as debt_selectors  # noqa: E402
from apps.debt import services as debt_services  # noqa: E402
from apps.debt.models import DebtKind  # noqa: E402
from apps.finance import services as finance_services  # noqa: E402
from apps.finance.models import AccountType  # noqa: E402
from tests.utils import tenant_scope  # noqa: E402

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return uuid.uuid4()


def _card(name="Card", balance=500_000, apr="19.9", minimum=10_000, **terms):
    account = finance_services.create_financial_account(
        name=name,
        account_type=AccountType.CREDIT_CARD,
        currency="USD",
        opening_balance_minor=balance,
    )
    debt_services.set_debt_terms(
        financial_account=account,
        apr=apr,
        minimum_payment_minor=minimum,
        debt_kind=DebtKind.CREDIT_CARD,
        **terms,
    )
    return account


def test_balance_comes_from_the_ledger_not_the_profile(tenant):
    """Storing a balance on the profile would create a second source of truth
    for the one number that has to reconcile."""
    with tenant_scope(tenant):
        _card(balance=500_000)
        [view] = debt_selectors.debt_views()
        assert view.balance_minor == 500_000
        assert view.apr == Decimal("19.9")


def test_terms_are_rejected_on_a_non_liability_account(tenant):
    with tenant_scope(tenant):
        savings = finance_services.create_financial_account(
            name="Savings", account_type=AccountType.SAVINGS, currency="USD"
        )
        with pytest.raises(debt_services.DebtError):
            debt_services.set_debt_terms(financial_account=savings, apr=5)


def test_an_apr_typed_as_a_fraction_is_caught(tenant):
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Card", account_type=AccountType.CREDIT_CARD, currency="USD"
        )
        # 199 instead of 19.9 — a slip that would otherwise produce a plan
        # nobody could act on.
        with pytest.raises(debt_services.DebtError, match="percentage"):
            debt_services.set_debt_terms(financial_account=account, apr=199)


def test_a_promotional_rate_needs_an_end_date(tenant):
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="BNPL", account_type=AccountType.LOAN, currency="USD"
        )
        with pytest.raises(debt_services.DebtError, match="end date"):
            debt_services.set_debt_terms(financial_account=account, apr=20, promotional_apr=0)


def test_a_promotional_rate_applies_while_it_lasts(tenant):
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="BNPL",
            account_type=AccountType.LOAN,
            currency="USD",
            opening_balance_minor=60_000,
        )
        profile = debt_services.set_debt_terms(
            financial_account=account,
            apr=22,
            minimum_payment_minor=10_000,
            promotional_apr=0,
            promotional_apr_until=date(2026, 12, 31),
        )
        # Interest-free until the promotion ends, then the headline rate.
        assert profile.effective_apr(date(2026, 6, 1)) == Decimal("0")
        assert profile.effective_apr(date(2027, 1, 1)) == Decimal("22")


def test_all_required_debt_kinds_are_supported():
    assert {
        "credit_card",
        "mortgage",
        "personal_loan",
        "student_loan",
        "bnpl",
    } <= set(DebtKind.values)


def test_a_debt_with_no_terms_still_appears_but_is_not_planned(tenant):
    """Hiding it would understate what's owed; planning it would invent terms."""
    with tenant_scope(tenant):
        finance_services.create_financial_account(
            name="Untracked card",
            account_type=AccountType.CREDIT_CARD,
            currency="USD",
            opening_balance_minor=200_000,
        )
        views = debt_selectors.debt_views()
        assert len(views) == 1
        assert views[0].balance_minor == 200_000
        # No minimum, so it can't be simulated.
        assert debt_selectors.to_debt_inputs(views) == []


def test_summary_weights_apr_by_balance(tenant):
    """A plain average would let a tiny expensive card out-shout a large cheap
    loan."""
    with tenant_scope(tenant):
        _card(name="Small card", balance=10_000, apr="30", minimum=2_000)
        _card(name="Big loan", balance=990_000, apr="3", minimum=20_000)

        summary = debt_selectors.debt_summary()
        assert summary.total_balance_minor == 1_000_000
        # Close to 3%, not the 16.5% a plain average would give.
        assert summary.weighted_apr < 4.0
        assert summary.highest_apr == 30.0


def test_weighted_apr_ignores_debts_whose_rate_is_unknown(tenant):
    """A debt with no terms carries `apr = 0`, and averaging it in dragged the
    reported rate toward zero — so adding a card you hadn't entered terms for
    made your borrowing look cheaper. The rate now describes exactly the debts
    it was computed from, and `priced_count` says how many that was."""
    with tenant_scope(tenant):
        _card(name="Priced card", balance=500_000, apr="20", minimum=10_000)
        # Same size, no terms: a real balance the rate cannot speak for.
        finance_services.create_financial_account(
            name="Untermed card",
            account_type=AccountType.CREDIT_CARD,
            currency="USD",
            opening_balance_minor=500_000,
        )

        summary = debt_selectors.debt_summary()
        assert summary.debt_count == 2
        assert summary.priced_count == 1
        # Both balances are owed, so the total covers both.
        assert summary.total_balance_minor == 1_000_000
        # The rate covers only the debt it could be measured from. Averaging
        # over both would report 10% — a figure describing no actual debt.
        assert summary.weighted_apr == 20.0


def test_unpriced_debt_reports_zero_cost_with_a_zero_priced_count(tenant):
    """The zeroes are correct; on their own they are indistinguishable from a
    debt that genuinely costs nothing, which is why the count ships with them."""
    with tenant_scope(tenant):
        finance_services.create_financial_account(
            name="Untermed card",
            account_type=AccountType.CREDIT_CARD,
            currency="USD",
            opening_balance_minor=500_000,
        )

        summary = debt_selectors.debt_summary()
        assert summary.total_balance_minor == 500_000
        assert summary.weighted_apr == 0.0
        assert summary.annual_interest_minor == 0
        assert summary.priced_count == 0

        cost = debt_selectors.borrowing_cost()
        assert cost.annual_total_minor == 0
        assert cost.priced_count == 0
        assert cost.debt_count == 1


def test_recorded_zero_percent_is_a_measurement_not_a_gap(tenant):
    """A 0% promotional card has terms: the cost really is zero, and the UI
    must show that rather than asking for terms it already has. `priced_count`
    keys off the profile, not off the rate being non-zero."""
    with tenant_scope(tenant):
        _card(name="Promo card", balance=500_000, apr="0", minimum=10_000)

        summary = debt_selectors.debt_summary()
        assert summary.weighted_apr == 0.0
        assert summary.priced_count == 1

        cost = debt_selectors.borrowing_cost()
        assert cost.annual_total_minor == 0
        assert cost.priced_count == 1


def test_summary_is_none_when_nothing_is_owed(tenant):
    with tenant_scope(tenant):
        assert debt_selectors.debt_summary() is None


def test_a_paid_off_debt_leaves_the_list(tenant):
    with tenant_scope(tenant):
        finance_services.create_financial_account(
            name="Cleared card", account_type=AccountType.CREDIT_CARD, currency="USD"
        )
        assert debt_selectors.debt_views() == []


def test_percent_repaid_needs_the_original_principal(tenant):
    with tenant_scope(tenant):
        _card(name="Known", balance=250_000, original_principal_minor=1_000_000)
        _card(name="Unknown", balance=100_000)

        by_name = {v.name: v for v in debt_selectors.debt_views()}
        assert by_name["Known"].percent_repaid == 75.0
        # A balance alone can't say how far through you are.
        assert by_name["Unknown"].percent_repaid is None


def test_a_growing_debt_is_flagged_critically(tenant):
    with tenant_scope(tenant):
        # 24% on 5,000.00 is ~100.00/month interest against a 50.00 minimum.
        _card(name="Underwater", balance=500_000, apr="24", minimum=5_000)

        [view] = debt_selectors.debt_views()
        assert view.minimum_covers_interest is False

        alerts = debt_selectors.debt_alerts()
        assert alerts[0].severity == "critical"
        assert "growing despite payments" in alerts[0].title


def test_alerts_flag_missing_terms_without_alarm(tenant):
    with tenant_scope(tenant):
        finance_services.create_financial_account(
            name="No terms",
            account_type=AccountType.CREDIT_CARD,
            currency="USD",
            opening_balance_minor=100_000,
        )
        alerts = debt_selectors.debt_alerts()
        assert any(a.severity == "info" and "missing terms" in a.title for a in alerts)
        assert not any(a.severity == "critical" for a in alerts)


def test_payoff_plan_runs_over_stored_debts(tenant):
    with tenant_scope(tenant):
        _card(name="Card A", balance=100_000, apr="0", minimum=20_000)
        _card(name="Card B", balance=200_000, apr="0", minimum=20_000)

        plan = debt_selectors.payoff_plan(strategy="snowball")
        assert plan is not None
        assert plan.currency == "USD"
        assert plan.months_to_debt_free is not None
        assert plan.monthly_budget_minor == 40_000


def test_excluded_debts_stay_out_of_the_plan(tenant):
    """A mortgage nobody intends to overpay shouldn't distort a card plan."""
    with tenant_scope(tenant):
        _card(name="Card", balance=100_000, apr="0", minimum=10_000)
        mortgage = finance_services.create_financial_account(
            name="Mortgage",
            account_type=AccountType.LOAN,
            currency="USD",
            opening_balance_minor=20_000_000,
        )
        debt_services.set_debt_terms(
            financial_account=mortgage,
            apr="4",
            minimum_payment_minor=120_000,
            debt_kind=DebtKind.MORTGAGE,
            include_in_payoff=False,
        )

        plan = debt_selectors.payoff_plan()
        assert [p.name for p in plan.per_debt] == ["Card"]
        # But it still counts toward what's owed.
        assert debt_selectors.debt_summary().total_balance_minor == 20_100_000


def test_committed_monthly_is_exposed_for_cash_flow(tenant):
    with tenant_scope(tenant):
        _card(name="A", minimum=10_000)
        _card(name="B", minimum=15_000)
        # Minimums are committed outflow, not discretionary.
        assert debt_selectors.committed_monthly_minor() == 25_000


def test_recommendation_prefers_avalanche_when_it_saves_materially(tenant):
    with tenant_scope(tenant):
        _card(name="Small cheap", balance=50_000, apr="2", minimum=5_000)
        _card(name="Big expensive", balance=800_000, apr="27", minimum=20_000)

        rec = debt_selectors.debt_recommendation(extra_monthly_minor=30_000)
        assert rec["strategy"] == "avalanche"
        assert "less in interest" in rec["rationale"]


def test_recommendation_prefers_snowball_when_the_difference_is_small(tenant):
    with tenant_scope(tenant):
        # Similar rates, so ordering barely affects total interest.
        _card(name="Small", balance=40_000, apr="12", minimum=5_000)
        _card(name="Large", balance=200_000, apr="12.5", minimum=10_000)

        rec = debt_selectors.debt_recommendation(extra_monthly_minor=10_000)
        assert rec["strategy"] == "snowball"
        # And it says why, rather than asserting one method is simply correct.
        assert "stick to" in rec["rationale"]


def test_payoff_calendar_groups_by_month(tenant):
    with tenant_scope(tenant):
        _card(name="Card", balance=60_000, apr="0", minimum=20_000)
        calendar = debt_selectors.payoff_calendar(months=6)

        assert len(calendar) == 3
        assert calendar[0]["payments"][0]["name"] == "Card"
        assert calendar[-1]["payments"][0]["clears_here"] is True


# ---------------------------------------------------------------- API surface
def _api_card(client, name="Card", balance=500_000, apr="19.9", minimum=10_000, **terms):
    account = client.post(
        "/api/v1/finance/accounts/",
        {"name": name, "account_type": "credit_card", "currency": "USD", "opening_balance_minor": balance},
        format="json",
    ).data
    payload = {"apr": apr, "minimum_payment_minor": minimum, "debt_kind": "credit_card"}
    payload.update(terms)
    resp = client.put(f"/api/v1/debt/debts/{account['id']}/terms/", payload, format="json")
    assert resp.status_code == 200, resp.data
    return account


def test_api_terms_round_trip(tenant_context):
    _, client = tenant_context
    _api_card(client)

    [debt] = client.get("/api/v1/debt/debts/").data
    assert debt["apr"] == 19.9
    assert debt["balance_minor"] == 500_000
    assert debt["has_terms"] is True


def test_api_rejects_an_implausible_apr(tenant_context):
    _, client = tenant_context
    account = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Card", "account_type": "credit_card", "currency": "USD"},
        format="json",
    ).data
    resp = client.put(f"/api/v1/debt/debts/{account['id']}/terms/", {"apr": "199"}, format="json")
    assert resp.status_code == 422
    assert "percentage" in resp.data["detail"]


def test_api_summary_reports_annual_interest_and_alerts(tenant_context):
    _, client = tenant_context
    _api_card(client, name="Underwater", balance=500_000, apr="24", minimum=5_000)

    data = client.get("/api/v1/debt/debts/summary/").data
    assert data["total_balance_minor"] == 500_000
    assert data["annual_interest_minor"] == data["total_monthly_interest_minor"] * 12
    assert data["growing_count"] == 1
    assert data["alerts"][0]["severity"] == "critical"


def test_api_summary_is_204_without_debt(tenant_context):
    _, client = tenant_context
    assert client.get("/api/v1/debt/debts/summary/").status_code == 204


def test_api_payoff_plan_includes_calendar_and_comparison(tenant_context):
    _, client = tenant_context
    _api_card(client, name="A", balance=100_000, apr="0", minimum=20_000)
    _api_card(client, name="B", balance=200_000, apr="0", minimum=20_000)

    data = client.get("/api/v1/debt/debts/payoff/?strategy=snowball&extra_monthly_minor=10000&months=6").data

    assert data["strategy"] == "snowball"
    assert data["months_to_debt_free"] is not None
    assert data["is_complete"] is True
    assert data["calendar"], "expected a month-by-month schedule"
    assert {c["strategy"] for c in data["comparison"]} == {"avalanche", "snowball", "custom"}


def test_api_payoff_reports_a_plan_that_cannot_finish(tenant_context):
    _, client = tenant_context
    _api_card(client, name="Stuck", balance=500_000, apr="24", minimum=5_000)

    data = client.get("/api/v1/debt/debts/payoff/").data
    # Honest: no completion date, and the reason is named.
    assert data["is_complete"] is False
    assert data["months_to_debt_free"] is None
    assert data["stuck_debt_ids"]


def test_api_extra_payment_curve(tenant_context):
    _, client = tenant_context
    _api_card(client, balance=500_000, apr="18", minimum=15_000)

    curve = client.get("/api/v1/debt/debts/extra-payment-curve/").data
    assert len(curve) > 1
    assert curve[0]["interest_saved_minor"] == 0


def test_api_clearing_terms_leaves_the_debt(tenant_context):
    """You stop planning; you don't stop owing."""
    _, client = tenant_context
    account = _api_card(client)

    assert client.delete(f"/api/v1/debt/debts/{account['id']}/terms/").status_code == 204
    [debt] = client.get("/api/v1/debt/debts/").data
    assert debt["has_terms"] is False
    assert debt["balance_minor"] == 500_000


def test_terms_can_be_re_added_after_being_cleared(tenant):
    """Soft deletion must not make clearing terms a one-way door."""
    with tenant_scope(tenant):
        account = _card(name="Card", apr="19.9", minimum=10_000)
        debt_services.clear_debt_terms(financial_account=account)
        assert debt_selectors.debt_views()[0].profile_id is None

        debt_services.set_debt_terms(financial_account=account, apr="12.5", minimum_payment_minor=8_000)
        view = debt_selectors.debt_views()[0]
        assert view.profile_id is not None
        assert view.apr == Decimal("12.5")
