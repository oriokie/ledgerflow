"""Income sources, deductions, receipts, and the committed-income ratio.

The tests that matter most here are the ones guarding against a **confident
figure derived from nothing**: a take-home rate of 100% for someone who is
taxed, a monthly total that quietly omits ad-hoc earners, or a ratio computed
over an income nobody supplied. Every one of those renders as a plausible
number, which is what makes them worse than an error.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from apps.finance import services as finance_services
from apps.finance.models import AccountType
from apps.income import selectors, services
from apps.income.models import (
    DeductionKind,
    IncomeFrequency,
    IncomeKind,
    IncomeSource,
    Reliability,
)
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db

TODAY = date(2026, 6, 15)


def _source(**kwargs):
    defaults = dict(
        name="Salary",
        currency="USD",
        net_minor=300_000,
        starts_on=date(2025, 1, 1),
        kind=IncomeKind.EMPLOYMENT,
    )
    return services.create_source(**{**defaults, **kwargs})


# --------------------------------------------------------------- cadence math
def test_fortnightly_and_semi_monthly_are_not_the_same_money():
    """26 payments a year against 24 — the reason these are separate cadences.

    Collapsing them, or reasoning in "weeks per month", loses a fortnight's pay
    from every annual figure.
    """
    assert selectors.monthly_equivalent_minor(100_000, IncomeFrequency.FORTNIGHTLY) == 216_667
    assert selectors.monthly_equivalent_minor(100_000, IncomeFrequency.SEMI_MONTHLY) == 200_000


def test_ad_hoc_income_has_no_monthly_equivalent():
    # Money that arrives whenever it arrives cannot be averaged into a month
    # without inventing a cadence the user never agreed to.
    assert selectors.monthly_equivalent_minor(100_000, IncomeFrequency.AD_HOC) is None


# ------------------------------------------------------------------ deductions
def test_percentage_deduction_without_a_gross_is_unknown_not_zero():
    """The single most misleading number this module could produce.

    Returning 0 here would report a take-home rate of 100% for someone who is
    taxed. `None` makes every caller say "not known" instead.
    """
    tid = uuid.uuid4()
    with tenant_scope(tid):
        source = _source(gross_minor=None)
        # The service refuses to create it...
        with pytest.raises(services.IncomeError, match="percentage needs something"):
            services.add_deduction(source=source, kind=DeductionKind.TAX, percent_bp=2000)

        # ...and if one exists anyway, the selector reports unknown, not zero.
        from apps.income.models import IncomeDeduction

        IncomeDeduction.objects.create(source=source, kind=DeductionKind.TAX, percent_bp=2000)
        assert selectors.deductions_for(source) is None


def test_deductions_resolve_against_gross():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        source = _source(net_minor=240_000, gross_minor=300_000)
        services.add_deduction(source=source, kind=DeductionKind.TAX, percent_bp=1500)  # 450.00
        services.add_deduction(source=source, kind=DeductionKind.PENSION, amount_minor=15_000)
        assert selectors.deductions_for(source) == 45_000 + 15_000


def test_a_deduction_is_one_basis_or_the_other():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        source = _source(gross_minor=300_000)
        with pytest.raises(services.IncomeError):
            services.add_deduction(
                source=source, kind=DeductionKind.TAX, amount_minor=1000, percent_bp=500
            )
        with pytest.raises(services.IncomeError):
            services.add_deduction(source=source, kind=DeductionKind.TAX)


def test_net_above_gross_is_refused():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        with pytest.raises(services.IncomeError, match="Net cannot exceed gross"):
            _source(net_minor=400_000, gross_minor=300_000)


# ----------------------------------------------------------------- reliability
def test_reliability_defaults_from_kind_not_to_fixed():
    """Defaulting everything to fixed would let the projection draw a confident
    line through freelance income nobody promised."""
    tid = uuid.uuid4()
    with tenant_scope(tid):
        assert _source(kind=IncomeKind.EMPLOYMENT).reliability == Reliability.FIXED
        assert _source(kind=IncomeKind.SELF_EMPLOYMENT).reliability == Reliability.IRREGULAR
        assert _source(kind=IncomeKind.RENTAL).reliability == Reliability.VARIABLE


def test_irregular_income_without_history_is_speculative():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        _source(kind=IncomeKind.SELF_EMPLOYMENT, name="Freelance")
        view = selectors.source_views(as_of=TODAY)[0]
        assert view.is_speculative
        assert not view.expected_is_observed


# -------------------------------------------------------- observed vs. stated
def test_variable_income_uses_the_observed_mean_over_the_stated_amount():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        source = _source(
            name="Retainer", kind=IncomeKind.BUSINESS, net_minor=100_000, reliability=Reliability.VARIABLE
        )
        for n, amount in enumerate((200_000, 220_000, 240_000), start=1):
            services.record_receipt(
                source=source, occurred_on=TODAY - timedelta(days=30 * n), net_minor=amount
            )
        view = selectors.source_views(as_of=TODAY)[0]
        assert view.expected_is_observed
        assert view.expected_net_minor == 220_000
        assert view.stated_net_minor == 100_000


def test_a_fixed_salary_is_not_restated_by_a_one_off_bonus():
    """Observation overrides expectation only where nothing was fixed.

    A salaried user who received one bonus has not had a pay rise, and
    permanently restating their salary upward would put a number in the
    projection their employer never agreed to.
    """
    tid = uuid.uuid4()
    with tenant_scope(tid):
        source = _source(net_minor=300_000, reliability=Reliability.FIXED)
        for n, amount in enumerate((300_000, 300_000, 900_000), start=1):
            services.record_receipt(
                source=source, occurred_on=TODAY - timedelta(days=30 * n), net_minor=amount
            )
        view = selectors.source_views(as_of=TODAY)[0]
        assert view.expected_net_minor == 300_000
        assert not view.expected_is_observed
        # The bonus is still visible as history — it just isn't the plan.
        assert view.observed_mean_minor == 500_000


def test_two_receipts_are_not_enough_to_restate_expectation():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        source = _source(kind=IncomeKind.BUSINESS, net_minor=100_000, reliability=Reliability.VARIABLE)
        for n in (1, 2):
            services.record_receipt(
                source=source, occurred_on=TODAY - timedelta(days=30 * n), net_minor=500_000
            )
        view = selectors.source_views(as_of=TODAY)[0]
        assert view.observed_mean_minor is None
        assert view.expected_net_minor == 100_000
        # The count and last date are still facts worth having.
        assert view.receipt_count == 2
        assert view.last_received_on == TODAY - timedelta(days=30)


def test_variance_is_none_without_enough_history():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        _source(kind=IncomeKind.BUSINESS, reliability=Reliability.VARIABLE)
        assert selectors.source_views(as_of=TODAY)[0].variance_pct is None


# --------------------------------------------------------------------- summary
def test_summary_is_absent_rather_than_zero_when_nothing_is_recorded():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        assert selectors.income_summary(as_of=TODAY) is None
        assert selectors.committed_income(as_of=TODAY) is None


def test_summary_reports_take_home_rate_and_concentration():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        salary = _source(name="Salary", net_minor=240_000, gross_minor=300_000)
        services.add_deduction(source=salary, kind=DeductionKind.TAX, amount_minor=60_000)
        _source(name="Rental", kind=IncomeKind.RENTAL, net_minor=60_000)

        summary = selectors.income_summary(as_of=TODAY)
        assert summary is not None
        assert summary.monthly_net_minor == 300_000
        assert summary.monthly_deductions_minor == 60_000
        assert summary.monthly_gross_minor == 360_000
        # 300000 / 360000
        assert summary.take_home_rate == 83.3
        # The salary is 240000 of the 300000 net.
        assert summary.concentration_pct == 80.0


def test_one_unknowable_deduction_makes_the_total_unknown():
    """A partial total presented as a whole is worse than no total."""
    tid = uuid.uuid4()
    with tenant_scope(tid):
        salary = _source(name="Salary", net_minor=240_000, gross_minor=300_000)
        services.add_deduction(source=salary, kind=DeductionKind.TAX, amount_minor=60_000)

        other = _source(name="Consulting", kind=IncomeKind.BUSINESS, net_minor=50_000)
        from apps.income.models import IncomeDeduction

        IncomeDeduction.objects.create(source=other, kind=DeductionKind.TAX, percent_bp=2000)

        summary = selectors.income_summary(as_of=TODAY)
        assert summary is not None
        assert summary.monthly_deductions_minor is None
        assert summary.monthly_gross_minor is None
        assert summary.take_home_rate is None


def test_ad_hoc_sources_are_counted_but_do_not_inflate_the_monthly_total():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        _source(name="Salary", net_minor=300_000)
        _source(
            name="Gigs",
            kind=IncomeKind.SELF_EMPLOYMENT,
            net_minor=999_999,
            frequency=IncomeFrequency.AD_HOC,
        )
        summary = selectors.income_summary(as_of=TODAY)
        assert summary is not None
        assert summary.monthly_net_minor == 300_000
        assert summary.source_count == 2
        # Reported so the UI can say the total is incomplete rather than
        # implying this person earns nothing from gig work.
        assert summary.ad_hoc_count == 1


def test_income_is_never_summed_across_currencies():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        _source(name="Salary KES", currency="KES", net_minor=8_000_000)
        _source(name="Consulting USD", currency="USD", net_minor=100_000)

        summary = selectors.income_summary(as_of=TODAY)
        assert summary is not None
        # The dominant currency by value, and only that currency's money.
        assert summary.currency == "KES"
        assert summary.monthly_net_minor == 8_000_000


# ----------------------------------------------------------- committed income
def test_committed_ratio_counts_bills_debt_minimums_and_recurring():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        _source(name="Salary", net_minor=400_000)

        account = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        category = finance_services.create_category(name="Rent", kind="expense", currency="USD")
        from apps.finance.bills import create_bill
        from apps.finance.models import Frequency, RecurringType
        from apps.finance.recurring import create_recurring_transaction

        create_bill(
            name="Rent",
            amount_minor=120_000,
            currency="USD",
            due_on=TODAY + timedelta(days=10),
            recurrence_frequency=Frequency.MONTHLY,
        )
        create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=account,
            category=category,
            amount_minor=30_000,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=TODAY,
            memo="Internet",
        )

        committed = selectors.committed_income(as_of=TODAY)
        assert committed is not None
        assert committed.bills_minor == 120_000
        assert committed.recurring_expenses_minor == 30_000
        assert committed.committed_minor == 150_000
        assert committed.free_minor == 250_000
        assert committed.committed_pct == 37.5


def test_a_one_off_bill_is_an_obligation_but_not_a_commitment():
    """Otherwise the ratio swings on the timing of a single vet visit and
    month-to-month comparison stops meaning anything."""
    tid = uuid.uuid4()
    with tenant_scope(tid):
        _source(name="Salary", net_minor=400_000)
        from apps.finance.bills import create_bill

        create_bill(
            name="Vet",
            amount_minor=90_000,
            currency="USD",
            due_on=TODAY + timedelta(days=5),
        )
        committed = selectors.committed_income(as_of=TODAY)
        assert committed is not None
        assert committed.bills_minor == 0


def test_committed_against_fixed_income_is_reported_separately():
    """For a salaried household the two ratios are identical; for a freelancer
    the gap between them is the finding."""
    tid = uuid.uuid4()
    with tenant_scope(tid):
        _source(name="Salary", net_minor=100_000, reliability=Reliability.FIXED)
        _source(
            name="Freelance",
            kind=IncomeKind.SELF_EMPLOYMENT,
            net_minor=300_000,
            reliability=Reliability.IRREGULAR,
        )
        from apps.finance.bills import create_bill
        from apps.finance.models import Frequency

        create_bill(
            name="Rent",
            amount_minor=100_000,
            currency="USD",
            due_on=TODAY + timedelta(days=10),
            recurrence_frequency=Frequency.MONTHLY,
        )
        committed = selectors.committed_income(as_of=TODAY)
        assert committed is not None
        # 100000 / 400000 total income looks comfortable...
        assert committed.committed_pct == 25.0
        # ...but the rent is due whether or not the freelance work arrives.
        assert committed.committed_against_fixed_pct == 100.0


def test_deleted_source_leaves_the_summary():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        source = _source(name="Old job", net_minor=300_000)
        assert selectors.income_summary(as_of=TODAY) is not None
        source.delete()
        assert selectors.income_summary(as_of=TODAY) is None
        # Soft delete: the record survives for history.
        assert IncomeSource.all_objects.filter(id=source.id).exists()


# ------------------------------------------------------------------ validation
def test_a_pay_day_beyond_the_28th_is_refused():
    """A schedule that silently skips February is a real bug, not a rare one."""
    tid = uuid.uuid4()
    with tenant_scope(tid):
        with pytest.raises(services.IncomeError, match="between 1 and 28"):
            _source(frequency=IncomeFrequency.MONTHLY, pay_day=31)


def test_semi_monthly_needs_both_pay_days():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        with pytest.raises(services.IncomeError, match="both pay days"):
            _source(frequency=IncomeFrequency.SEMI_MONTHLY, pay_day=15)


def test_currency_cannot_be_edited():
    """Every receipt already recorded is denominated in the original currency."""
    tid = uuid.uuid4()
    with tenant_scope(tid):
        source = _source(currency="USD")
        services.update_source(source=source, currency="EUR", name="Renamed")
        source.refresh_from_db()
        assert source.currency == "USD"
        assert source.name == "Renamed"
