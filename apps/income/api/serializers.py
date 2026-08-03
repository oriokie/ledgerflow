from __future__ import annotations

from rest_framework import serializers

from ..models import DeductionKind, IncomeFrequency, IncomeKind, Reliability


class IncomeSourceCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    kind = serializers.ChoiceField(choices=IncomeKind.choices, default=IncomeKind.EMPLOYMENT)
    payer = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    currency = serializers.CharField(max_length=3)
    net_minor = serializers.IntegerField(min_value=1)
    gross_minor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    # Omitted reliability is filled from the kind by the service, so a caller
    # who doesn't care still gets a projection that matches the arrangement
    # rather than one that assumes every income is guaranteed.
    reliability = serializers.ChoiceField(choices=Reliability.choices, required=False, allow_null=True)
    frequency = serializers.ChoiceField(choices=IncomeFrequency.choices, default=IncomeFrequency.MONTHLY)
    pay_day = serializers.IntegerField(min_value=1, max_value=28, required=False, allow_null=True)
    second_pay_day = serializers.IntegerField(min_value=1, max_value=28, required=False, allow_null=True)
    starts_on = serializers.DateField()
    ends_on = serializers.DateField(required=False, allow_null=True)
    deposit_account_id = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class IncomeSourceUpdateSerializer(serializers.Serializer):
    """Everything editable about the plan.

    ``currency`` is absent by design: every receipt already recorded is
    denominated in the original currency, so changing it would reinterpret
    history rather than correct it — the same refusal savings goals make.
    """

    name = serializers.CharField(max_length=120, required=False)
    kind = serializers.ChoiceField(choices=IncomeKind.choices, required=False)
    payer = serializers.CharField(max_length=120, required=False, allow_blank=True)
    net_minor = serializers.IntegerField(min_value=1, required=False)
    gross_minor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    reliability = serializers.ChoiceField(choices=Reliability.choices, required=False)
    frequency = serializers.ChoiceField(choices=IncomeFrequency.choices, required=False)
    pay_day = serializers.IntegerField(min_value=1, max_value=28, required=False, allow_null=True)
    second_pay_day = serializers.IntegerField(min_value=1, max_value=28, required=False, allow_null=True)
    starts_on = serializers.DateField(required=False)
    ends_on = serializers.DateField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)


class DeductionCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=DeductionKind.choices, default=DeductionKind.OTHER)
    label = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    amount_minor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    #: Basis points: 2000 is 20%. Integer so a rate is exact rather than a
    #: float that has to be rounded before it can be compared.
    percent_bp = serializers.IntegerField(min_value=1, max_value=10000, required=False, allow_null=True)

    def validate(self, attrs):
        has_amount = attrs.get("amount_minor") is not None
        has_percent = attrs.get("percent_bp") is not None
        if has_amount == has_percent:
            raise serializers.ValidationError(
                "Give either a fixed amount or a percentage, not both and not neither."
            )
        return attrs


class ReceiptCreateSerializer(serializers.Serializer):
    occurred_on = serializers.DateField()
    net_minor = serializers.IntegerField(min_value=1)
    gross_minor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    transaction_id = serializers.UUIDField(required=False, allow_null=True)
    memo = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
