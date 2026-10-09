"""Kenya statutory, conveyancing, and school-fee arithmetic.

These numbers are the product's Kenyan starting points. If a band or a stamp
duty rate is edited, the golden cases here must move with it — silently
shipping a 2024 PAYE table as if it were current is the failure mode.
"""

from __future__ import annotations

import pytest

from apps.projections import calculators as calc
from apps.projections import kenya


def test_paye_on_the_first_band_is_wiped_by_personal_relief():
    """KES 24,000/month is the top of the 10% band; relief is KES 2,400."""
    gross = 2_400_000
    result = kenya.statutory_from_gross(gross)
    assert result.paye_minor == 0
    assert result.nssf_minor == 144_000
    assert result.shif_minor == 66_000
    assert result.housing_levy_minor == 36_000
    assert result.net_monthly_minor == 2_154_000
    assert result.rates_as_of == kenya.RATES_AS_OF.isoformat()


def test_statutory_deductions_never_exceed_gross():
    for gross in (0, 1, 50_000_00, 100_000_00, 500_000_00):
        result = kenya.statutory_from_gross(gross)
        taken = result.paye_minor + result.nssf_minor + result.shif_minor + result.housing_levy_minor
        assert taken + result.net_monthly_minor == gross
        assert result.net_monthly_minor >= 0


def test_urban_stamp_duty_is_four_percent():
    costs = kenya.purchase_upfront_costs(property_price_minor=10_000_000_00, deposit_minor=1_000_000_00)
    assert costs.stamp_duty_minor == 400_000_00
    assert costs.deposit_minor == 1_000_000_00
    assert costs.total_minor == (
        costs.deposit_minor
        + costs.stamp_duty_minor
        + costs.legal_fees_minor
        + costs.valuation_minor
        + costs.loan_fees_minor
    )


def test_rural_stamp_duty_is_two_percent():
    costs = kenya.purchase_upfront_costs(property_price_minor=10_000_000_00, urban=False)
    assert costs.stamp_duty_minor == 200_000_00


def test_rental_yield_applies_vacancy_agent_and_tax():
    result = kenya.rental_yield(
        property_price_minor=10_000_000_00,
        expected_monthly_rent_minor=80_000_00,
        vacancy_rate=0.10,
        agent_fee_rate=0.10,
        tax_rate=0.075,
    )
    assert result.annual_rent_minor == 960_000_00
    assert result.vacancy_loss_minor == 96_000_00
    assert result.agent_fees_minor == 86_400_00
    # tax on collected-after-agent: (960k - 96k - 86.4k) * 7.5%
    assert result.tax_minor == 58_320_00
    assert result.net_annual_minor == 719_280_00


def test_school_fees_three_terms_average_to_the_monthly_budget_figure():
    """150,000 per term × 3 = 450,000/year = 37,500/month."""
    result = calc.school_fees(fee_per_term_minor=150_000_00, children=1, terms_per_year=3)
    assert result.annual_total_minor == 450_000_00
    assert result.monthly_average_minor == 37_500_00
    assert result.term_cashflows_minor == [150_000_00, 150_000_00, 150_000_00]


def test_commute_is_round_trip_times_working_days():
    result = calc.commute_cost(extra_km=10, cost_per_km_minor=2500, working_days=22)
    assert result.monthly_cost_minor == 10 * 2 * 22 * 2500


def test_kenya_rates_catalogue_is_dated():
    catalogue = kenya.rates_catalogue()
    assert catalogue["as_of"] == "2026-07-01"
    assert catalogue["stamp_duty_urban"] == 0.04
    assert catalogue["rental_income_tax_rate"] == 0.075
    assert catalogue["sacco_share_multiple"] == 3.0
    assert catalogue["sacco_typical_rate"] == 0.12


def test_sacco_loan_capacity_is_shares_times_multiple():
    result = calc.sacco_loan(amount_minor=300_000_00, shares_held_minor=80_000_00, share_multiple=3)
    assert result.capacity_minor == 240_000_00
    assert result.extra_shares_needed_minor == 20_000_00
    assert result.monthly_payment_minor > 0


@pytest.mark.django_db
def test_kenya_rates_endpoint(tenant_context):
    _, client = tenant_context
    res = client.get("/api/v1/projections/kenya-rates/")
    assert res.status_code == 200
    assert res.data["as_of"] == kenya.RATES_AS_OF.isoformat()
    assert "paye_bands_monthly_minor" in res.data


def test_unknown_rate_override_keys_are_refused():
    with pytest.raises(ValueError, match="Unknown Kenya rate keys"):
        kenya.validate_rate_overrides({"not_a_rate": 0.1})


def test_a_rate_outside_zero_to_one_is_refused():
    with pytest.raises(ValueError, match="stamp_duty_urban"):
        kenya.validate_rate_overrides({"stamp_duty_urban": 4})


@pytest.mark.django_db
def test_an_operator_override_moves_stamp_duty_without_a_deploy():
    """KRA changing a band mid-year must not wait for the next release."""
    from apps.platform_admin import settings_store

    settings_store.clear(key="kenya.rate_overrides")
    try:
        settings_store.set_value(
            key="kenya.rate_overrides", raw={"stamp_duty_urban": 0.05, "as_of": "2026-10-01"}
        )
        catalogue = kenya.rates_catalogue()
        assert catalogue["stamp_duty_urban"] == 0.05
        assert catalogue["as_of"] == "2026-10-01"
        # Unmentioned keys keep the code table.
        assert catalogue["stamp_duty_rural"] == kenya.STAMP_DUTY_RURAL
        costs = kenya.purchase_upfront_costs(property_price_minor=10_000_000_00, deposit_minor=1_000_000_00)
        assert costs.stamp_duty_minor == 500_000_00
    finally:
        settings_store.clear(key="kenya.rate_overrides")


@pytest.mark.django_db
def test_kenya_rates_endpoint_reflects_an_operator_override(tenant_context):
    from apps.platform_admin import settings_store

    _, client = tenant_context
    settings_store.clear(key="kenya.rate_overrides")
    try:
        settings_store.set_value(key="kenya.rate_overrides", raw={"housing_levy_rate": 0.02})
        res = client.get("/api/v1/projections/kenya-rates/")
        assert res.status_code == 200
        assert res.data["housing_levy_rate"] == 0.02
        assert res.data["shif_rate"] == kenya.SHIF_RATE
    finally:
        settings_store.clear(key="kenya.rate_overrides")
