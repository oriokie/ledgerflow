from __future__ import annotations

from rest_framework import serializers

from ..models import Compounding, DebtKind, InterestMethod, PayoffStrategy, RateSource


class DebtTermsSerializer(serializers.Serializer):
    """Repayment terms. Every field optional so a user can fill them in as they
    find them — a partial profile is more useful than none."""

    apr = serializers.DecimalField(max_digits=6, decimal_places=3, min_value=0, required=False)
    minimum_payment_minor = serializers.IntegerField(min_value=0, required=False)
    debt_kind = serializers.ChoiceField(choices=DebtKind.choices, required=False)
    payment_day = serializers.IntegerField(min_value=1, max_value=28, required=False, allow_null=True)
    original_principal_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    opened_on = serializers.DateField(required=False, allow_null=True)
    #: The form asks in years; months is what's stored, because 18- and
    #: 30-month terms are ordinary and a fractional year is worse to keep.
    term_months = serializers.IntegerField(min_value=1, max_value=1200, required=False, allow_null=True)
    interest_method = serializers.ChoiceField(choices=InterestMethod.choices, required=False)
    credit_limit_minor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    statement_day = serializers.IntegerField(min_value=1, max_value=28, required=False, allow_null=True)
    promotional_apr = serializers.DecimalField(
        max_digits=6, decimal_places=3, min_value=0, required=False, allow_null=True
    )
    promotional_apr_until = serializers.DateField(required=False, allow_null=True)
    custom_priority = serializers.IntegerField(min_value=1, max_value=999, required=False)
    include_in_payoff = serializers.BooleanField(required=False)
    compounding = serializers.ChoiceField(choices=Compounding.choices, required=False)
    monthly_fee_minor = serializers.IntegerField(min_value=0, required=False)
    annual_fee_minor = serializers.IntegerField(min_value=0, required=False)
    annual_fee_month = serializers.IntegerField(min_value=1, max_value=12, required=False, allow_null=True)
    origination_fee_minor = serializers.IntegerField(min_value=0, required=False)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)


class DebtCreateSerializer(DebtTermsSerializer):
    """A whole debt in one request: what it is, what's owed, and its terms.

    Inherits the terms so the two cannot drift, and adds only what the account
    itself needs. Terms stay optional — money borrowed from a friend has a name
    and an amount and nothing else, and that has to be enough.
    """

    name = serializers.CharField(max_length=120)
    currency = serializers.CharField(max_length=3, min_length=3)
    balance_minor = serializers.IntegerField(min_value=0)
    #: Who it's owed to. Free text on purpose — a friend is not an institution
    #: and forcing one into that table would be modelling the wrong thing.
    lender = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")


class RateChangeSerializer(serializers.Serializer):
    """A rate effective from a date. Future dates are the point: a notified
    increase should shape the plan before it bites."""

    apr = serializers.DecimalField(max_digits=6, decimal_places=3, min_value=0)
    effective_from = serializers.DateField()
    source = serializers.ChoiceField(choices=RateSource.choices, required=False, default="manual")
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class OffsetAccountsSerializer(serializers.Serializer):
    account_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=True)


class RefinanceSerializer(serializers.Serializer):
    """Simulation inputs. Nothing here modifies the debt."""

    new_apr = serializers.DecimalField(max_digits=6, decimal_places=3, min_value=0)
    new_minimum_payment_minor = serializers.IntegerField(min_value=1)
    closing_costs_minor = serializers.IntegerField(min_value=0, required=False, default=0)
    capitalise_costs = serializers.BooleanField(required=False, default=True)
    compounding = serializers.ChoiceField(choices=Compounding.choices, required=False, default="monthly")


class ConsolidationSerializer(serializers.Serializer):
    account_ids = serializers.ListField(child=serializers.UUIDField(), min_length=2)
    new_apr = serializers.DecimalField(max_digits=6, decimal_places=3, min_value=0)
    new_minimum_payment_minor = serializers.IntegerField(min_value=1)
    fees_minor = serializers.IntegerField(min_value=0, required=False, default=0)
    compounding = serializers.ChoiceField(choices=Compounding.choices, required=False, default="monthly")


class ScenarioSerializer(serializers.Serializer):
    """One extra-payment scenario, for side-by-side comparison."""

    label = serializers.CharField(max_length=60, required=False, default="Scenario")
    strategy = serializers.ChoiceField(choices=PayoffStrategy.choices, required=False, default="avalanche")
    monthly_minor = serializers.IntegerField(min_value=0, required=False, default=0)
    #: [[month_index, amount], ...] — a bonus, a refund, a windfall.
    lump_sums = serializers.ListField(
        child=serializers.ListField(child=serializers.IntegerField(min_value=0), min_length=2, max_length=2),
        required=False,
        default=list,
    )
    #: [[month_index, amount], ...] — a permanent change from that month on.
    step_ups = serializers.ListField(
        child=serializers.ListField(child=serializers.IntegerField(min_value=0), min_length=2, max_length=2),
        required=False,
        default=list,
    )


class ScenarioComparisonSerializer(serializers.Serializer):
    scenarios = ScenarioSerializer(many=True)


class PayoffQuerySerializer(serializers.Serializer):
    strategy = serializers.ChoiceField(
        choices=PayoffStrategy.choices, required=False, default=PayoffStrategy.AVALANCHE
    )
    #: Money above the minimums. The single lever a user actually controls.
    extra_monthly_minor = serializers.IntegerField(min_value=0, required=False, default=0)
    months = serializers.IntegerField(min_value=1, max_value=120, required=False, default=12)
