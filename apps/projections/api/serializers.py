"""Serialisers for the projection API.

Input serialisers validate; output is assembled by explicit functions rather
than `ModelSerializer`. That is a deliberate choice carried over from the
analytics API: a projection response is a *view*, not a model dump, and letting
DRF infer it from the model would couple the wire format to the schema and make
every column rename a breaking API change.
"""

from __future__ import annotations

from rest_framework import serializers

from ..calculators import MAX_HORIZON_MONTHS
from ..events import EVENT_LABELS, EVENT_PARAMS, EventKind
from ..models import ScenarioStatus, ScenarioVisibility


class AssumptionSetSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)
    annual_inflation = serializers.DecimalField(max_digits=6, decimal_places=4, required=False)
    annual_salary_growth = serializers.DecimalField(max_digits=6, decimal_places=4, required=False)
    annual_investment_return = serializers.DecimalField(max_digits=6, decimal_places=4, required=False)
    annual_cash_return = serializers.DecimalField(max_digits=6, decimal_places=4, required=False)
    effective_tax_rate = serializers.DecimalField(max_digits=6, decimal_places=4, required=False)
    annual_property_growth = serializers.DecimalField(max_digits=6, decimal_places=4, required=False)


class ScenarioWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    horizon_months = serializers.IntegerField(min_value=1, max_value=MAX_HORIZON_MONTHS, default=120)
    status = serializers.ChoiceField(choices=ScenarioStatus.choices, required=False)
    visibility = serializers.ChoiceField(choices=ScenarioVisibility.choices, required=False)
    assumption_set_id = serializers.UUIDField(required=False, allow_null=True)


class ScenarioEventWriteSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[(k, EVENT_LABELS[k]) for k in EventKind.all()])
    label = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    start_month = serializers.IntegerField(min_value=1, max_value=MAX_HORIZON_MONTHS, default=1)
    params = serializers.DictField(required=False, default=dict)
    is_enabled = serializers.BooleanField(required=False, default=True)


class CompareSerializer(serializers.Serializer):
    scenario_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=6)


# ---------------------------------------------------------------------------
# calculator inputs
# ---------------------------------------------------------------------------
class MortgageSerializer(serializers.Serializer):
    property_price_minor = serializers.IntegerField(min_value=0)
    deposit_minor = serializers.IntegerField(min_value=0, default=0)
    annual_rate = serializers.FloatField()
    years = serializers.IntegerField(min_value=1, max_value=40)
    annual_tax_minor = serializers.IntegerField(min_value=0, default=0)
    annual_insurance_minor = serializers.IntegerField(min_value=0, default=0)
    extra_monthly_minor = serializers.IntegerField(min_value=0, default=0)
    with_schedule = serializers.BooleanField(default=False)


class LoanSerializer(serializers.Serializer):
    principal_minor = serializers.IntegerField(min_value=0)
    annual_rate = serializers.FloatField()
    months = serializers.IntegerField(min_value=1, max_value=MAX_HORIZON_MONTHS)
    extra_monthly_minor = serializers.IntegerField(min_value=0, default=0)
    with_schedule = serializers.BooleanField(default=False)


class InvestmentGrowthSerializer(serializers.Serializer):
    initial_minor = serializers.IntegerField(min_value=0, default=0)
    monthly_contribution_minor = serializers.IntegerField(min_value=0, default=0)
    annual_return = serializers.FloatField()
    months = serializers.IntegerField(min_value=1, max_value=MAX_HORIZON_MONTHS)
    annual_inflation = serializers.FloatField(required=False, allow_null=True)
    contribution_growth = serializers.FloatField(default=0.0)
    with_schedule = serializers.BooleanField(default=False)


class SavingsGoalSerializer(serializers.Serializer):
    target_minor = serializers.IntegerField(min_value=0)
    current_minor = serializers.IntegerField(min_value=0, default=0)
    monthly_contribution_minor = serializers.IntegerField(min_value=0, default=0)
    annual_return = serializers.FloatField(default=0.0)
    by_months = serializers.IntegerField(
        min_value=1, max_value=MAX_HORIZON_MONTHS, required=False, allow_null=True
    )


class RetirementSerializer(serializers.Serializer):
    current_pot_minor = serializers.IntegerField(min_value=0, default=0)
    monthly_contribution_minor = serializers.IntegerField(min_value=0, default=0)
    years_to_retirement = serializers.IntegerField(min_value=1, max_value=40)
    annual_return = serializers.FloatField()
    annual_inflation = serializers.FloatField(default=0.0)
    withdrawal_rate = serializers.FloatField(default=0.04)
    target_monthly_income_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    contribution_growth = serializers.FloatField(default=0.0)


class NetWorthSerializer(serializers.Serializer):
    assets_minor = serializers.IntegerField(min_value=0, default=0)
    liabilities_minor = serializers.IntegerField(min_value=0, default=0)
    monthly_saving_minor = serializers.IntegerField(min_value=0, default=0)
    annual_asset_return = serializers.FloatField(default=0.0)
    monthly_debt_payment_minor = serializers.IntegerField(min_value=0, default=0)
    debt_annual_rate = serializers.FloatField(default=0.0)
    months = serializers.IntegerField(min_value=1, max_value=MAX_HORIZON_MONTHS)


#: Calculator slug -> (serialiser, callable name). One registry so the URL
#: surface, the docs and the dispatch cannot disagree about what exists.
CALCULATORS = {
    "mortgage": (MortgageSerializer, "mortgage"),
    "loan": (LoanSerializer, "loan"),
    "investment-growth": (InvestmentGrowthSerializer, "investment_growth"),
    "savings-goal": (SavingsGoalSerializer, "savings_goal"),
    "retirement": (RetirementSerializer, "retirement_estimate"),
    "net-worth": (NetWorthSerializer, "net_worth_projection"),
}


def event_catalogue() -> list[dict]:
    """The fifteen life events and the parameters each accepts.

    Served to the client so the scenario builder renders its forms from the
    backend's schema rather than a hard-coded copy that drifts.
    """
    out = []
    for kind in EventKind.all():
        out.append(
            {
                "kind": kind,
                "label": EVENT_LABELS[kind],
                "params": [
                    {
                        "name": spec.name,
                        "required": spec.required,
                        "type": spec.kind.__name__,
                        "default": spec.default,
                    }
                    for spec in EVENT_PARAMS[kind]
                ],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Phase 2 — simulation, sensitivity, risk and the decision assistant
# ---------------------------------------------------------------------------
class SimulationSerializer(serializers.Serializer):
    months = serializers.IntegerField(min_value=1, max_value=MAX_HORIZON_MONTHS, default=120)
    trials = serializers.IntegerField(min_value=1, max_value=5_000, default=1_000)
    #: Part of the request *and* the response. A simulation nobody can
    #: reproduce is one nobody can check or act on.
    seed = serializers.IntegerField(default=12345)
    return_volatility = serializers.FloatField(min_value=0, max_value=1, default=0.15)
    inflation_volatility = serializers.FloatField(min_value=0, max_value=1, default=0.02)
    income_shock_probability = serializers.FloatField(min_value=0, max_value=1, default=0.04)
    #: Simulate a saved scenario rather than the bare position.
    scenario_id = serializers.UUIDField(required=False, allow_null=True)


class SensitivitySerializer(serializers.Serializer):
    months = serializers.IntegerField(min_value=1, max_value=MAX_HORIZON_MONTHS, default=120)


class RiskQuerySerializer(serializers.Serializer):
    """No inputs — risk is measured entirely from the recorded position."""


class WhatIfSerializer(serializers.Serializer):
    months = serializers.IntegerField(min_value=1, max_value=MAX_HORIZON_MONTHS, default=120)
    inflation = serializers.FloatField(required=False, allow_null=True)
    investment_return = serializers.FloatField(required=False, allow_null=True)
    salary_growth = serializers.FloatField(required=False, allow_null=True)
    rate_shift = serializers.FloatField(required=False, allow_null=True)


class _DecisionSerializer(serializers.Serializer):
    """Base for the named questions.

    `explain` opts out of the LLM tier per request. The deterministic prose is
    always produced either way, so turning it off costs nothing but latency.
    """

    explain = serializers.BooleanField(default=True)


class AffordMortgageSerializer(_DecisionSerializer):
    question = "Can I afford this mortgage?"
    property_price_minor = serializers.IntegerField(min_value=0)
    deposit_minor = serializers.IntegerField(min_value=0, default=0)
    annual_rate = serializers.FloatField()
    years = serializers.IntegerField(min_value=1, max_value=40, default=25)
    annual_tax_minor = serializers.IntegerField(min_value=0, default=0)
    annual_insurance_minor = serializers.IntegerField(min_value=0, default=0)


class HowMuchHouseSerializer(_DecisionSerializer):
    question = "How much house can I comfortably afford?"
    annual_rate = serializers.FloatField()
    years = serializers.IntegerField(min_value=1, max_value=40, default=25)
    deposit_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)


class DebtOrInvestSerializer(_DecisionSerializer):
    question = "Should I pay debt down or invest?"
    monthly_amount_minor = serializers.IntegerField(min_value=1)
    expected_return = serializers.FloatField()
    months = serializers.IntegerField(min_value=1, max_value=MAX_HORIZON_MONTHS, default=120)


class RetireSerializer(_DecisionSerializer):
    question = "Can I retire when I want to?"
    years_until = serializers.IntegerField(min_value=1, max_value=40)
    monthly_income_needed_minor = serializers.IntegerField(min_value=0)
    annual_return = serializers.FloatField(default=0.07)
    annual_inflation = serializers.FloatField(default=0.05)
    withdrawal_rate = serializers.FloatField(default=0.04)
    monthly_pension_income_minor = serializers.IntegerField(min_value=0, default=0)


class BuyOrRentSerializer(_DecisionSerializer):
    question = "Should I buy or rent?"
    property_price_minor = serializers.IntegerField(min_value=0)
    deposit_minor = serializers.IntegerField(min_value=0, default=0)
    annual_rate = serializers.FloatField()
    monthly_rent_minor = serializers.IntegerField(min_value=0)
    years = serializers.IntegerField(min_value=1, max_value=40, default=10)
    annual_tax_minor = serializers.IntegerField(min_value=0, default=0)
    annual_insurance_minor = serializers.IntegerField(min_value=0, default=0)
    maintenance_rate = serializers.FloatField(default=0.01)


#: Question slug -> (serialiser, evaluator name in `decisions`). One registry,
#: so the URL surface, the catalogue endpoint and the dispatch cannot disagree
#: about which questions exist.
DECISION_SERIALIZERS = {
    "afford-mortgage": (AffordMortgageSerializer, "can_i_afford_mortgage"),
    "how-much-house": (HowMuchHouseSerializer, "how_much_house"),
    "debt-or-invest": (DebtOrInvestSerializer, "debt_or_invest"),
    "retire": (RetireSerializer, "can_i_retire"),
    "buy-or-rent": (BuyOrRentSerializer, "buy_or_rent"),
}
