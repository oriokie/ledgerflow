"""The digital twin: measured parameters, calibration, and the router.

The honesty properties are what these defend, because they are the ones a
product like this is tempted to get wrong:

* a measurement from two months does not override a considered default,
* calibration can report that the twin is getting *worse*,
* a forecast cannot be restated once the month it describes has closed,
* the router refuses rather than guessing at the closest question.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from django.utils import timezone

from apps.finance import services as finance_services
from apps.finance.models import AccountType, CategoryKind
from apps.projections.engine import EconomicAssumptions
from apps.twin import calibration, conversation
from apps.twin import parameters as params
from apps.twin.models import ForecastKind, ForecastSnapshot
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return uuid.uuid4()


def _month_back(n: int) -> date:
    today = timezone.localdate()
    month, year = today.month - n, today.year
    while month <= 0:
        month, year = month + 12, year - 1
    return date(year, month, 15)


def _seed(months=12, income=500_000, spend=300_000, spend_growth=0):
    account = finance_services.create_financial_account(
        name="Checking",
        account_type=AccountType.CHECKING,
        currency="USD",
        opening_balance_minor=2_000_000,
    )
    salary = finance_services.create_category(name="Salary", kind=CategoryKind.INCOME, currency="USD")
    shop = finance_services.create_category(name="Shopping", kind=CategoryKind.EXPENSE, currency="USD")
    for n in range(months, 0, -1):
        when = _month_back(n)
        at = datetime(when.year, when.month, when.day, 12, tzinfo=UTC)
        finance_services.record_income(
            financial_account=account, category=salary, amount_minor=income, occurred_at=at
        )
        # Older months spend less when growth is on, so the twin has a trend.
        amount = spend + spend_growth * (months - n)
        finance_services.record_expense(
            financial_account=account, category=shop, amount_minor=amount, occurred_at=at
        )
    return account


# ---------------------------------------------------------------------------
# measured parameters
# ---------------------------------------------------------------------------


def test_the_twin_measures_the_households_own_inflation(tenant):
    with tenant_scope(tenant):
        _seed(months=12, spend=300_000, spend_growth=5_000)
        twin = params.build()

    growth = twin.get("spending_growth")
    assert growth.measured is not None
    assert growth.measured > 0


def test_a_thin_history_leaves_the_prior_standing(tenant):
    """A measurement from two months is noisier than a sensible default, not
    better than one. Swapping it in because it is "real data" is how a product
    projects a whole future from a January with a bonus in it."""
    with tenant_scope(tenant):
        _seed(months=3)
        twin = params.build()

    growth = twin.get("spending_growth")
    assert twin.months_observed < params.MIN_MONTHS_FOR_CONFIDENCE
    assert growth.effective == pytest.approx(growth.prior)
    assert any("still uses the standard assumptions" in n for n in twin.notes)


def test_evidence_ramps_rather_than_switching(tenant):
    """A parameter that jumps the moment a sixth month lands makes the whole
    projection lurch, and the user cannot tell that from a real change."""
    assert params._blend_weight(params.MIN_MONTHS_FOR_CONFIDENCE - 1) == 0.0
    assert params._blend_weight(params.STRONG_EVIDENCE_MONTHS) == 1.0
    middle = params._blend_weight((params.MIN_MONTHS_FOR_CONFIDENCE + params.STRONG_EVIDENCE_MONTHS) // 2)
    assert 0.0 < middle < 1.0


def test_every_parameter_reports_the_evidence_behind_it(tenant):
    with tenant_scope(tenant):
        _seed(months=12)
        twin = params.build()

    for parameter in twin.parameters:
        assert parameter.confidence in vars(params.Confidence).values()
        assert parameter.detail
        assert parameter.label


def test_the_twin_is_only_as_good_as_its_thinnest_parameter(tenant):
    with tenant_scope(tenant):
        _seed(months=3)
        twin = params.build()
    assert twin.confidence in (params.Confidence.NONE, params.Confidence.WEAK)


def test_irregular_income_is_measured_and_called_out(tenant):
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=1_000_000,
        )
        salary = finance_services.create_category(name="Contract", kind=CategoryKind.INCOME, currency="USD")
        shop = finance_services.create_category(name="Shopping", kind=CategoryKind.EXPENSE, currency="USD")
        for n in range(12, 0, -1):
            when = _month_back(n)
            at = datetime(when.year, when.month, when.day, 12, tzinfo=UTC)
            # Feast and famine.
            finance_services.record_income(
                financial_account=account,
                category=salary,
                amount_minor=900_000 if n % 2 else 100_000,
                occurred_at=at,
            )
            finance_services.record_expense(
                financial_account=account, category=shop, amount_minor=300_000, occurred_at=at
            )
        twin = params.build()

    volatility = twin.get("income_volatility")
    assert volatility.measured > 0.25
    assert any("irregular" in n for n in twin.notes)


def test_the_twin_supplies_assumptions_to_the_engine(tenant):
    with tenant_scope(tenant):
        _seed(months=24, spend=300_000, spend_growth=4_000)
        twin = params.build()
        assumptions = twin.to_assumptions()

    assert isinstance(assumptions, EconomicAssumptions)
    assert assumptions.annual_inflation != EconomicAssumptions().annual_inflation


def test_it_does_not_claim_to_personalise_what_it_cannot_derive(tenant):
    """Income volatility and saving consistency describe shape, not a rate. The
    engine takes a single smooth figure, so bending one with them would be a
    claim we cannot support."""
    with tenant_scope(tenant):
        _seed(months=24)
        twin = params.build()
        assumptions = twin.to_assumptions()

    base = EconomicAssumptions()
    assert assumptions.annual_salary_growth == base.annual_salary_growth
    assert assumptions.annual_investment_return == base.annual_investment_return


def test_an_empty_workspace_produces_a_twin_that_says_it_knows_nothing(tenant):
    with tenant_scope(tenant):
        twin = params.build()
    assert twin.months_observed == 0
    assert twin.confidence == params.Confidence.NONE
    assert twin.to_assumptions() == EconomicAssumptions()


# ---------------------------------------------------------------------------
# calibration
# ---------------------------------------------------------------------------


def _next_month_start() -> date:
    today = timezone.localdate().replace(day=1)
    return (
        today.replace(year=today.year + 1, month=1)
        if today.month == 12
        else today.replace(month=today.month + 1)
    )


def test_a_forecast_about_a_month_that_has_started_is_refused(tenant):
    """ "Predicting" the present is not prediction, and allowing it would fill
    the calibration report with easy marks."""
    with tenant_scope(tenant), pytest.raises(calibration.CalibrationError, match="not started"):
        calibration.record(
            kind=ForecastKind.MONTHLY_SPEND,
            period=timezone.localdate(),
            predicted_minor=100,
            currency="USD",
        )


def test_a_second_forecast_for_the_same_month_is_refused(tenant):
    """Keeping both would let whichever turned out better be the one reported."""
    with tenant_scope(tenant):
        calibration.record(
            kind=ForecastKind.MONTHLY_SPEND,
            period=_next_month_start(),
            predicted_minor=100,
            currency="USD",
        )
        with pytest.raises(calibration.CalibrationError, match="already exists"):
            calibration.record(
                kind=ForecastKind.MONTHLY_SPEND,
                period=_next_month_start(),
                predicted_minor=999,
                currency="USD",
            )


def test_scoring_fills_in_what_actually_happened(tenant):
    with tenant_scope(tenant):
        _seed(months=6, spend=300_000)
        # A forecast made in the past about a month that has since closed.
        ForecastSnapshot.objects.create(
            kind=ForecastKind.MONTHLY_SPEND,
            period=_month_back(2).replace(day=1),
            made_on=_month_back(3),
            predicted_minor=280_000,
            currency="USD",
        )
        assert calibration.score() == 1
        snapshot = ForecastSnapshot.objects.get()

    assert snapshot.is_scored
    assert snapshot.actual_minor == 300_000
    assert snapshot.error_minor == -20_000


def test_scoring_is_idempotent_and_never_moves_a_mark(tenant):
    with tenant_scope(tenant):
        _seed(months=6)
        ForecastSnapshot.objects.create(
            kind=ForecastKind.MONTHLY_SPEND,
            period=_month_back(2).replace(day=1),
            made_on=_month_back(3),
            predicted_minor=280_000,
            currency="USD",
        )
        calibration.score()
        first = ForecastSnapshot.objects.get().actual_minor
        assert calibration.score() == 0
        assert ForecastSnapshot.objects.get().actual_minor == first


def test_calibration_can_report_that_the_twin_is_getting_worse(tenant):
    """A report that can only improve is not a measurement."""
    with tenant_scope(tenant):
        # Early forecasts close, later ones far out.
        for offset, predicted in [
            (12, 100_000),
            (11, 100_000),
            (10, 100_000),
            (9, 60_000),
            (8, 40_000),
            (7, 20_000),
        ]:
            ForecastSnapshot.objects.create(
                kind=ForecastKind.MONTHLY_SPEND,
                period=_month_back(offset).replace(day=1),
                made_on=_month_back(offset + 1),
                predicted_minor=predicted,
                currency="USD",
                actual_minor=100_000,
                scored_at=timezone.now(),
            )
        report = calibration.accuracy()

    spend = next(k for k in report.kinds if k.kind == ForecastKind.MONTHLY_SPEND)
    assert spend.samples == 6
    assert spend.trend == "worse"
    assert "further out" in spend.detail


def test_a_trend_is_withheld_until_there_is_enough_to_say_one(tenant):
    with tenant_scope(tenant):
        for offset in (5, 4):
            ForecastSnapshot.objects.create(
                kind=ForecastKind.MONTHLY_SPEND,
                period=_month_back(offset).replace(day=1),
                made_on=_month_back(offset + 1),
                predicted_minor=95_000,
                currency="USD",
                actual_minor=100_000,
                scored_at=timezone.now(),
            )
        report = calibration.accuracy()

    spend = next(k for k in report.kinds if k.kind == ForecastKind.MONTHLY_SPEND)
    assert spend.samples == 2
    assert spend.trend is None


def test_nothing_scored_yet_says_so_rather_than_claiming_accuracy(tenant):
    with tenant_scope(tenant):
        report = calibration.accuracy()
    assert report.total_scored == 0
    assert "Not enough history" in report.headline


def test_the_error_is_a_median_so_one_bad_month_does_not_decide_it(tenant):
    with tenant_scope(tenant):
        for offset, predicted in [(9, 100_000), (8, 100_000), (7, 100_000), (6, 1_000_000)]:
            ForecastSnapshot.objects.create(
                kind=ForecastKind.MONTHLY_SPEND,
                period=_month_back(offset).replace(day=1),
                made_on=_month_back(offset + 1),
                predicted_minor=predicted,
                currency="USD",
                actual_minor=100_000,
                scored_at=timezone.now(),
            )
        report = calibration.accuracy()

    spend = next(k for k in report.kinds if k.kind == ForecastKind.MONTHLY_SPEND)
    # Three perfect months and one wild miss: the median stays near zero.
    assert spend.median_error < 0.5


def test_forecasting_next_month_records_from_the_twins_own_measurements(tenant):
    with tenant_scope(tenant):
        _seed(months=12)
        twin = params.build()
        made = calibration.forecast_next_month(twin=twin)

        assert len(made) == 2
        assert {m.kind for m in made} == {
            ForecastKind.MONTHLY_SPEND,
            ForecastKind.MONTHLY_INCOME,
        }
        # The evidence travels with the prediction.
        assert all(m.months_observed == twin.months_observed for m in made)
        # Running twice leaves the first prediction standing.
        assert calibration.forecast_next_month(twin=twin) == []


def test_forecasts_do_not_leak_across_tenants(tenant):
    other = uuid.uuid4()
    with tenant_scope(tenant):
        calibration.record(
            kind=ForecastKind.MONTHLY_SPEND,
            period=_next_month_start(),
            predicted_minor=100,
            currency="USD",
        )
    with tenant_scope(other):
        assert ForecastSnapshot.objects.count() == 0


# ---------------------------------------------------------------------------
# the conversational router
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,slug",
    [
        ("Can I afford this mortgage at 450,000 with 9%?", "afford-mortgage"),
        ("Can we afford a second home?", "afford-mortgage"),
        ("How much house can I comfortably afford?", "how-much-house"),
        ("Should I buy or rent?", "buy-or-rent"),
        ("Should I pay off debt or invest?", "debt-or-invest"),
        ("Can I retire at 55?", "retire"),
        ("Will we reach financial independence?", "retire"),
    ],
)
def test_the_phrasings_people_actually_use_are_routed(question, slug):
    assert conversation.route_deterministic(question).slug == slug


def test_a_question_it_cannot_compute_is_refused_not_guessed():
    """Being confidently answered with the wrong question is worse than being
    told to rephrase — the output gives no clue the wrong thing was computed."""
    routing = conversation.route_deterministic("What is the meaning of life?")
    assert routing.slug is None
    assert not routing.answerable
    assert "not one of the questions" in routing.detail
    assert "Can I afford this mortgage?" in conversation.describe_missing(routing)


def test_numbers_are_pulled_out_of_the_sentence():
    routing = conversation.route_deterministic("Can I afford this house at 4.5m with a 900k deposit at 9%?")
    assert routing.params["property_price_minor"] == 450_000_000
    assert routing.params["deposit_minor"] == 90_000_000
    assert routing.params["annual_rate"] == pytest.approx(0.09)


def test_a_percentage_is_not_also_read_as_an_amount():
    routing = conversation.route_deterministic("Can I afford a mortgage of 300,000 at 12%?")
    assert routing.params["annual_rate"] == pytest.approx(0.12)
    assert routing.params["property_price_minor"] == 30_000_000


def test_a_year_count_is_not_read_as_money():
    routing = conversation.route_deterministic("Can I retire in 20 years on 300,000 a month?")
    assert routing.params["years_until"] == 20
    assert routing.params["monthly_income_needed_minor"] == 30_000_000


def test_a_missing_figure_is_named_rather_than_invented():
    """A mortgage answered with an invented interest rate looks like an answer
    and is not one."""
    routing = conversation.route_deterministic("Can I afford this mortgage?")
    assert routing.slug == "afford-mortgage"
    assert not routing.answerable
    assert "annual_rate" in routing.missing
    assert "nothing is assumed" in conversation.describe_missing(routing).lower()


def test_no_model_configured_still_answers(monkeypatch):
    """The deterministic router is not a fallback — with no model, it is the
    whole feature, which is the default configuration."""
    monkeypatch.setattr(conversation, "llm_available", lambda: (False, "off"))
    routing = conversation.route("Should I buy or rent?")
    assert routing.slug == "buy-or-rent"
    assert not routing.llm_used


def test_a_model_that_cannot_place_the_question_does_not_overrule_a_match(monkeypatch):
    monkeypatch.setattr(conversation, "llm_available", lambda: (True, ""))
    monkeypatch.setattr(conversation, "complete_json", lambda **_kw: {"slug": None, "params": {}})
    routing = conversation.route("Should I buy or rent?")
    assert routing.slug == "buy-or-rent"
    assert not routing.llm_used


def test_unknown_parameters_from_a_model_are_dropped(monkeypatch):
    """Same allow-list discipline as ask.py: the boundary is the list, not the
    prompt."""
    monkeypatch.setattr(conversation, "llm_available", lambda: (True, ""))
    monkeypatch.setattr(
        conversation,
        "complete_json",
        lambda **_kw: {
            "slug": "afford-mortgage",
            "params": {"property_price_minor": 1, "annual_rate": 0.09, "sneaky": 99},
        },
    )
    routing = conversation.route("Can I afford this?")
    assert routing.llm_used
    assert "sneaky" not in routing.params


def test_an_unreachable_model_falls_back_silently(monkeypatch):
    from apps.intelligence.llm import LLMError

    monkeypatch.setattr(conversation, "llm_available", lambda: (True, ""))

    def boom(**_kw):
        raise LLMError("timeout")

    monkeypatch.setattr(conversation, "complete_json", boom)
    routing = conversation.route("Can I retire at 60?")
    assert routing.slug == "retire"
    assert not routing.llm_used
