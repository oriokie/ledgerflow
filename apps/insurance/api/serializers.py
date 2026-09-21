from __future__ import annotations

from rest_framework import serializers

from ..models import PolicyKind, PremiumFrequency


class PolicyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    kind = serializers.ChoiceField(choices=PolicyKind.choices, default=PolicyKind.OTHER)
    insurer = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    currency = serializers.CharField(max_length=3, min_length=3)
    coverage_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    deductible_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    premium_minor = serializers.IntegerField(min_value=1)
    premium_frequency = serializers.ChoiceField(
        choices=PremiumFrequency.choices, default=PremiumFrequency.ANNUAL
    )
    renews_on = serializers.DateField(required=False, allow_null=True)
    ends_on = serializers.DateField(required=False, allow_null=True)
    covers_asset_id = serializers.UUIDField(required=False, allow_null=True)
    covers_account_id = serializers.UUIDField(required=False, allow_null=True)
    bill_id = serializers.UUIDField(required=False, allow_null=True)
    recurring_transaction_id = serializers.UUIDField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False, default=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class PolicyUpdateSerializer(serializers.Serializer):
    """``currency`` is absent — every figure already recorded is denominated in it."""

    name = serializers.CharField(max_length=120, required=False)
    kind = serializers.ChoiceField(choices=PolicyKind.choices, required=False)
    insurer = serializers.CharField(max_length=120, required=False, allow_blank=True)
    coverage_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    deductible_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    premium_minor = serializers.IntegerField(min_value=1, required=False)
    premium_frequency = serializers.ChoiceField(choices=PremiumFrequency.choices, required=False)
    renews_on = serializers.DateField(required=False, allow_null=True)
    ends_on = serializers.DateField(required=False, allow_null=True)
    covers_asset_id = serializers.UUIDField(required=False, allow_null=True)
    covers_account_id = serializers.UUIDField(required=False, allow_null=True)
    bill_id = serializers.UUIDField(required=False, allow_null=True)
    recurring_transaction_id = serializers.UUIDField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Nothing to change.")
        return attrs
