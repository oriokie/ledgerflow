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

#: Typical SACCO borrowing power: loan ≤ deposits × multiple. Three times is
#: the convention most Kenyan SACCOs still print on the loan form; the
#: evaluator takes the multiple as an input so a 4× or 2× rule is not a
#: code change.
SACCO_SHARE_MULTIPLE = 3.0
SACCO_TYPICAL_RATE = 0.12

#: Catalogue keys an operator may override without a deploy. Anything else is
#: refused at the settings boundary so a typo cannot silently no-op.
_OVERRIDE_KEYS = frozenset(
    {
        "as_of",
        "source",
        "paye_bands_monthly_minor",
        "personal_relief_monthly_minor",
        "nssf_employee_rate",
        "nssf_tier1_ceiling_minor",
        "nssf_tier2_ceiling_minor",
        "shif_rate",
        "housing_levy_rate",
        "rental_income_tax_rate",
        "stamp_duty_urban",
        "stamp_duty_rural",
        "legal_fee_rate",
        "valuation_fee_rate",
        "typical_mortgage_deposit",
        "letting_agent_fee_rate",
        "sacco_share_multiple",
        "sacco_typical_rate",
    }
)
_FRACTION_KEYS = frozenset(
    {
        "nssf_employee_rate",
        "shif_rate",
        "housing_levy_rate",
        "rental_income_tax_rate",
        "stamp_duty_urban",
        "stamp_duty_rural",
        "legal_fee_rate",
        "valuation_fee_rate",
        "typical_mortgage_deposit",
        "letting_agent_fee_rate",
        "sacco_typical_rate",
    }
)
_INT_KEYS = frozenset(
    {
        "personal_relief_monthly_minor",
        "nssf_tier1_ceiling_minor",
        "nssf_tier2_ceiling_minor",
    }
)


def _code_catalogue() -> dict:
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
        "sacco_share_multiple": SACCO_SHARE_MULTIPLE,
        "sacco_typical_rate": SACCO_TYPICAL_RATE,
    }


def validate_rate_overrides(raw) -> dict:
    """Refuse a payload that would not compute, before it is stored."""
    import json

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise ValueError("kenya.rate_overrides must be a JSON object.") from exc
    if not isinstance(raw, dict):
        raise ValueError("kenya.rate_overrides must be a JSON object.")
    unknown = sorted(set(raw) - _OVERRIDE_KEYS)
    if unknown:
        raise ValueError(f"Unknown Kenya rate keys: {', '.join(unknown)}.")
    for key, value in raw.items():
        if key in _FRACTION_KEYS:
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
                raise ValueError(f"{key} must be a rate between 0 and 1.")
        elif key in _INT_KEYS:
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{key} must be a non-negative integer in minor units.")
        elif key == "sacco_share_multiple":
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise ValueError("sacco_share_multiple must be a positive number.")
        elif key in {"as_of", "source"}:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} must be a non-empty string.")
        elif key == "paye_bands_monthly_minor":
            if not isinstance(value, list) or not value:
                raise ValueError("paye_bands_monthly_minor must be a non-empty list.")
            for band in value:
                if not isinstance(band, dict) or "up_to_minor" not in band or "rate" not in band:
                    raise ValueError("each PAYE band needs up_to_minor and rate.")
                if not isinstance(band["up_to_minor"], int) or band["up_to_minor"] <= 0:
                    raise ValueError("PAYE band up_to_minor must be a positive integer.")
                rate = band["rate"]
                if not isinstance(rate, (int, float)) or isinstance(rate, bool) or not 0 <= rate <= 1:
                    raise ValueError("PAYE band rate must be between 0 and 1.")
    return raw


def _overrides() -> dict:
    """Operator-set rates, or nothing if the console has not stored any.

    Falls back to the code table when the settings table is unreachable —
    unit tests and a mid-migrate deploy still have to compute PAYE.
    """
    try:
        from apps.platform_admin.settings_store import get as get_setting

        raw = get_setting("kenya.rate_overrides")
    except Exception:  # noqa: BLE001 — settings must never take PAYE down
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in _OVERRIDE_KEYS}


def _cfg() -> dict:
    data = _code_catalogue()
    data.update(_overrides())
    return data


def _paye_bands(cfg: dict) -> tuple[tuple[int, float], ...]:
    raw = cfg["paye_bands_monthly_minor"]
    if raw and isinstance(raw[0], dict):
        return tuple((int(band["up_to_minor"]), float(band["rate"])) for band in raw)
    return tuple((int(upper), float(rate)) for upper, rate in raw)


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


def paye_monthly_minor(taxable_minor: int, *, cfg: dict | None = None) -> int:
    """PAYE on a monthly taxable amount, after personal relief."""
    if taxable_minor <= 0:
        return 0
    rates = cfg or _cfg()
    tax = 0
    lower = 0
    for upper, rate in _paye_bands(rates):
        slice_ = min(taxable_minor, upper) - lower
        if slice_ <= 0:
            break
        tax += round(slice_ * rate)
        lower = upper
        if taxable_minor <= upper:
            break
    return max(0, tax - int(rates["personal_relief_monthly_minor"]))


def nssf_employee_minor(gross_monthly_minor: int, *, cfg: dict | None = None) -> int:
    """Employee NSSF: 6% of Tier I plus 6% of Tier II, capped."""
    if gross_monthly_minor <= 0:
        return 0
    rates = cfg or _cfg()
    tier1_ceiling = int(rates["nssf_tier1_ceiling_minor"])
    tier2_ceiling = int(rates["nssf_tier2_ceiling_minor"])
    employee_rate = float(rates["nssf_employee_rate"])
    tier1 = min(gross_monthly_minor, tier1_ceiling)
    tier2 = min(max(0, gross_monthly_minor - tier1_ceiling), tier2_ceiling - tier1_ceiling)
    return round(tier1 * employee_rate) + round(tier2 * employee_rate)


def statutory_from_gross(gross_monthly_minor: int) -> StatutoryBreakdown:
    """Gross → net take-home with PAYE, NSSF, SHIF and housing levy.

    NSSF is deducted before PAYE (standard Kenyan payroll order). SHIF and
    the housing levy are calculated on gross, matching current KRA practice.
    """
    if not isinstance(gross_monthly_minor, int) or gross_monthly_minor < 0:
        raise ValueError("gross_monthly_minor must be a non-negative int in minor units")
    rates = _cfg()
    nssf = nssf_employee_minor(gross_monthly_minor, cfg=rates)
    shif = round(gross_monthly_minor * float(rates["shif_rate"]))
    levy = round(gross_monthly_minor * float(rates["housing_levy_rate"]))
    taxable = max(0, gross_monthly_minor - nssf)
    paye = paye_monthly_minor(taxable, cfg=rates)
    net = max(0, gross_monthly_minor - paye - nssf - shif - levy)
    as_of = str(rates["as_of"])
    relief = int(rates["personal_relief_monthly_minor"])
    return StatutoryBreakdown(
        gross_monthly_minor=gross_monthly_minor,
        paye_minor=paye,
        nssf_minor=nssf,
        shif_minor=shif,
        housing_levy_minor=levy,
        net_monthly_minor=net,
        rates_as_of=as_of,
        assumptions=[
            f"Rates as of {as_of} ({rates['source']}).",
            "NSSF deducted before PAYE; SHIF and housing levy on gross.",
            f"Personal relief KES {relief // 100:,}/month.",
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
    legal_fee_rate: float | None = None,
    valuation_rate: float | None = None,
    loan_fees_minor: int = 0,
) -> UpfrontCosts:
    """Cash needed on completion day, not just the deposit."""
    if property_price_minor < 0 or loan_fees_minor < 0:
        raise ValueError("amounts cannot be negative")
    rates = _cfg()
    legal = float(rates["legal_fee_rate"]) if legal_fee_rate is None else legal_fee_rate
    valuation = float(rates["valuation_fee_rate"]) if valuation_rate is None else valuation_rate
    typical_rate = float(rates["typical_mortgage_deposit"])
    typical = round(property_price_minor * typical_rate)
    deposit = typical if deposit_minor is None else deposit_minor
    rate = float(rates["stamp_duty_urban"] if urban else rates["stamp_duty_rural"])
    if stamp_duty_rate is not None:
        rate = stamp_duty_rate
    stamp = round(property_price_minor * rate)
    legal_fees = round(property_price_minor * legal)
    valuation_fees = round(property_price_minor * valuation)
    total = deposit + stamp + legal_fees + valuation_fees + loan_fees_minor
    return UpfrontCosts(
        deposit_minor=deposit,
        stamp_duty_minor=stamp,
        legal_fees_minor=legal_fees,
        valuation_minor=valuation_fees,
        loan_fees_minor=loan_fees_minor,
        total_minor=total,
        typical_deposit_minor=typical,
        assumptions=[
            f"Stamp duty {rate:.0%} {'urban' if urban else 'rural'} as of {rates['as_of']}.",
            f"Legal fees modelled at {legal:.1%}; valuation at {valuation:.2%}.",
            f"Typical Kenyan mortgage deposit {typical_rate:.0%} of price.",
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
    agent_fee_rate: float | None = None,
    tax_rate: float | None = None,
    monthly_service_minor: int = 0,
    monthly_repairs_minor: int = 0,
) -> RentalYield:
    """Gross and net rental yield after vacancy, agent, tax, service and repairs."""
    if property_price_minor < 0 or expected_monthly_rent_minor < 0:
        raise ValueError("amounts cannot be negative")
    rates = _cfg()
    agent_fee_rate = float(rates["letting_agent_fee_rate"]) if agent_fee_rate is None else agent_fee_rate
    tax_rate = float(rates["rental_income_tax_rate"]) if tax_rate is None else tax_rate
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
            f"Residential rental income tax at {tax_rate:.1%} as of {rates['as_of']}.",
            f"Vacancy {vacancy_rate:.0%}; letting agent {agent_fee_rate:.0%} of collected rent.",
        ],
    )


def rates_catalogue() -> dict:
    """What the UI shows as 'rates last updated' plus every editable default.

    Code constants are the starting point. An operator can overlay keys via
    the platform setting ``kenya.rate_overrides`` without a deploy — which is
    how a mid-year KRA change reaches every workspace the same day.
    """
    return _cfg()
