"""Kenya statutory rates and property-purchase conventions.

Rates are stated as of ``RATES_AS_OF`` and are editable inputs everywhere they
are used — the product must not pretend a 2026 band is eternal. These are the
KRA / NSSF / SHIF / Affordable Housing Levy figures in force for the 2025/26
year, plus typical conveyancing costs. They are *not* a tax engine that files
a return; they convert a stated gross into a stated take-home, and they price
the cash a buyer needs on completion day.

Money is integer minor units (cents). Rates are fractions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

RATES_AS_OF = date(2026, 7, 1)
RATES_SOURCE = "KRA / NSSF / SHIF / Housing levy, FY 2025/26"

#: Monthly PAYE bands: (upper bound inclusive, rate). The last band is open.
#: Source: Income Tax Act, as amended (personal relief KES 2,400/month).
PAYE_BANDS_MONTHLY_MINOR: tuple[tuple[int, float], ...] = (
    (2_400_000, 0.10),  # first 24,000
    (3_233_300, 0.25),  # next 8,333
    (50_000_000, 0.30),  # next 467,667
    (80_000_000, 0.325),  # next 300,000
    (10**15, 0.35),
)
PERSONAL_RELIEF_MONTHLY_MINOR = 240_000  # 2,400

#: NSSF Tier I ceiling 8,000; Tier II ceiling 72,000; employee 6% each.
NSSF_TIER1_CEILING_MINOR = 800_000
NSSF_TIER2_CEILING_MINOR = 7_200_000
NSSF_EMPLOYEE_RATE = 0.06

SHIF_RATE = 0.0275
HOUSING_LEVY_RATE = 0.015

#: Residential rental income tax (simplified single rate; KRA bands exist
#: around this figure). Configurable by the caller.
RENTAL_INCOME_TAX_RATE = 0.075

STAMP_DUTY_URBAN = 0.04
STAMP_DUTY_RURAL = 0.02
LEGAL_FEE_RATE = 0.015
VALUATION_FEE_RATE = 0.0025
TYPICAL_MORTGAGE_DEPOSIT = 0.10
LETTING_AGENT_FEE_RATE = 0.10  # of collected rent


@dataclass(frozen=True)
class StatutoryBreakdown:
    gross_monthly_minor: int
    paye_minor: int
    nssf_minor: int
    shif_minor: int
    housing_levy_minor: int
    net_monthly_minor: int
    rates_as_of: str = RATES_AS_OF.isoformat()
    assumptions: list[str] = field(default_factory=list)


def paye_monthly_minor(taxable_minor: int) -> int:
    """PAYE on a monthly taxable amount, after personal relief."""
    if taxable_minor <= 0:
        return 0
    tax = 0
    lower = 0
    for upper, rate in PAYE_BANDS_MONTHLY_MINOR:
        slice_ = min(taxable_minor, upper) - lower
        if slice_ <= 0:
            break
        tax += round(slice_ * rate)
        lower = upper
        if taxable_minor <= upper:
            break
    return max(0, tax - PERSONAL_RELIEF_MONTHLY_MINOR)


def nssf_employee_minor(gross_monthly_minor: int) -> int:
    """Employee NSSF: 6% of Tier I plus 6% of Tier II, capped."""
    if gross_monthly_minor <= 0:
        return 0
    tier1 = min(gross_monthly_minor, NSSF_TIER1_CEILING_MINOR)
    tier2 = min(
        max(0, gross_monthly_minor - NSSF_TIER1_CEILING_MINOR),
        NSSF_TIER2_CEILING_MINOR - NSSF_TIER1_CEILING_MINOR,
    )
    return round(tier1 * NSSF_EMPLOYEE_RATE) + round(tier2 * NSSF_EMPLOYEE_RATE)


def statutory_from_gross(gross_monthly_minor: int) -> StatutoryBreakdown:
    """Gross → net take-home with PAYE, NSSF, SHIF and housing levy.

    NSSF is deducted before PAYE (standard Kenyan payroll order). SHIF and
    the housing levy are calculated on gross, matching current KRA practice.
    """
    if not isinstance(gross_monthly_minor, int) or gross_monthly_minor < 0:
        raise ValueError("gross_monthly_minor must be a non-negative int in minor units")
    nssf = nssf_employee_minor(gross_monthly_minor)
    shif = round(gross_monthly_minor * SHIF_RATE)
    levy = round(gross_monthly_minor * HOUSING_LEVY_RATE)
    taxable = max(0, gross_monthly_minor - nssf)
    paye = paye_monthly_minor(taxable)
    net = max(0, gross_monthly_minor - paye - nssf - shif - levy)
    return StatutoryBreakdown(
        gross_monthly_minor=gross_monthly_minor,
        paye_minor=paye,
        nssf_minor=nssf,
        shif_minor=shif,
        housing_levy_minor=levy,
        net_monthly_minor=net,
        assumptions=[
            f"Rates as of {RATES_AS_OF.isoformat()} ({RATES_SOURCE}).",
            "NSSF deducted before PAYE; SHIF and housing levy on gross.",
            f"Personal relief KES {PERSONAL_RELIEF_MONTHLY_MINOR // 100:,}/month.",
        ],
    )


@dataclass(frozen=True)
class UpfrontCosts:
    deposit_minor: int
    stamp_duty_minor: int
    legal_fees_minor: int
    valuation_minor: int
    loan_fees_minor: int
    total_minor: int
    typical_deposit_minor: int
    assumptions: list[str] = field(default_factory=list)


def purchase_upfront_costs(
    *,
    property_price_minor: int,
    deposit_minor: int | None = None,
    urban: bool = True,
    stamp_duty_rate: float | None = None,
    legal_fee_rate: float = LEGAL_FEE_RATE,
    valuation_rate: float = VALUATION_FEE_RATE,
    loan_fees_minor: int = 0,
) -> UpfrontCosts:
    """Cash needed on completion day, not just the deposit."""
    if property_price_minor < 0 or loan_fees_minor < 0:
        raise ValueError("amounts cannot be negative")
    typical = round(property_price_minor * TYPICAL_MORTGAGE_DEPOSIT)
    deposit = typical if deposit_minor is None else deposit_minor
    rate = STAMP_DUTY_URBAN if urban else STAMP_DUTY_RURAL
    if stamp_duty_rate is not None:
        rate = stamp_duty_rate
    stamp = round(property_price_minor * rate)
    legal = round(property_price_minor * legal_fee_rate)
    valuation = round(property_price_minor * valuation_rate)
    total = deposit + stamp + legal + valuation + loan_fees_minor
    return UpfrontCosts(
        deposit_minor=deposit,
        stamp_duty_minor=stamp,
        legal_fees_minor=legal,
        valuation_minor=valuation,
        loan_fees_minor=loan_fees_minor,
        total_minor=total,
        typical_deposit_minor=typical,
        assumptions=[
            f"Stamp duty {'4% urban' if urban else '2% rural'} as of {RATES_AS_OF.isoformat()}.",
            f"Legal fees modelled at {legal_fee_rate:.1%}; valuation at {valuation_rate:.2%}.",
            f"Typical Kenyan mortgage deposit {TYPICAL_MORTGAGE_DEPOSIT:.0%} of price.",
            "All fee rates are editable; these are starting points, not quotes.",
        ],
    )


@dataclass(frozen=True)
class RentalYield:
    annual_rent_minor: int
    vacancy_loss_minor: int
    agent_fees_minor: int
    tax_minor: int
    service_and_repairs_minor: int
    net_annual_minor: int
    gross_yield: float
    net_yield: float
    net_monthly_income_minor: int
    assumptions: list[str] = field(default_factory=list)


def rental_yield(
    *,
    property_price_minor: int,
    expected_monthly_rent_minor: int,
    vacancy_rate: float = 0.08,
    agent_fee_rate: float = LETTING_AGENT_FEE_RATE,
    tax_rate: float = RENTAL_INCOME_TAX_RATE,
    monthly_service_minor: int = 0,
    monthly_repairs_minor: int = 0,
) -> RentalYield:
    """Gross and net rental yield after vacancy, agent, tax, service and repairs."""
    if property_price_minor < 0 or expected_monthly_rent_minor < 0:
        raise ValueError("amounts cannot be negative")
    annual_rent = expected_monthly_rent_minor * 12
    vacancy = round(annual_rent * max(0.0, vacancy_rate))
    collected = annual_rent - vacancy
    agent = round(collected * max(0.0, agent_fee_rate))
    taxable = max(0, collected - agent)
    tax = round(taxable * max(0.0, tax_rate))
    running = (monthly_service_minor + monthly_repairs_minor) * 12
    net_annual = collected - agent - tax - running
    gross = annual_rent / property_price_minor if property_price_minor else 0.0
    net = net_annual / property_price_minor if property_price_minor else 0.0
    return RentalYield(
        annual_rent_minor=annual_rent,
        vacancy_loss_minor=vacancy,
        agent_fees_minor=agent,
        tax_minor=tax,
        service_and_repairs_minor=running,
        net_annual_minor=net_annual,
        gross_yield=round(gross, 4),
        net_yield=round(net, 4),
        net_monthly_income_minor=round(net_annual / 12),
        assumptions=[
            f"Residential rental income tax at {tax_rate:.1%} as of {RATES_AS_OF.isoformat()}.",
            f"Vacancy {vacancy_rate:.0%}; letting agent {agent_fee_rate:.0%} of collected rent.",
        ],
    )


def rates_catalogue() -> dict:
    """What the UI shows as 'rates last updated' plus every editable default."""
    return {
        "as_of": RATES_AS_OF.isoformat(),
        "source": RATES_SOURCE,
        "paye_bands_monthly_minor": [
            {"up_to_minor": upper, "rate": rate} for upper, rate in PAYE_BANDS_MONTHLY_MINOR
        ],
        "personal_relief_monthly_minor": PERSONAL_RELIEF_MONTHLY_MINOR,
        "nssf_employee_rate": NSSF_EMPLOYEE_RATE,
        "nssf_tier1_ceiling_minor": NSSF_TIER1_CEILING_MINOR,
        "nssf_tier2_ceiling_minor": NSSF_TIER2_CEILING_MINOR,
        "shif_rate": SHIF_RATE,
        "housing_levy_rate": HOUSING_LEVY_RATE,
        "rental_income_tax_rate": RENTAL_INCOME_TAX_RATE,
        "stamp_duty_urban": STAMP_DUTY_URBAN,
        "stamp_duty_rural": STAMP_DUTY_RURAL,
        "legal_fee_rate": LEGAL_FEE_RATE,
        "valuation_fee_rate": VALUATION_FEE_RATE,
        "typical_mortgage_deposit": TYPICAL_MORTGAGE_DEPOSIT,
        "letting_agent_fee_rate": LETTING_AGENT_FEE_RATE,
    }
