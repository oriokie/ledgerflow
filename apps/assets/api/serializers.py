from __future__ import annotations

from rest_framework import serializers

from ..models import AssetKind, ValuationSource


class AssetCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    kind = serializers.ChoiceField(choices=AssetKind.choices, default=AssetKind.OTHER)
    currency = serializers.CharField(max_length=3, min_length=3)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    acquired_on = serializers.DateField(required=False, allow_null=True)
    acquisition_cost_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    secured_by_debt_id = serializers.UUIDField(required=False, allow_null=True)
    include_in_net_worth = serializers.BooleanField(required=False, default=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    #: Most people adding a house know roughly what it is worth today. Making
    #: that a second step is the friction that leaves assets unvalued, which is
    #: exactly the state that makes the net-worth total wrong.
    initial_value_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)


class AssetUpdateSerializer(serializers.Serializer):
    """``currency`` is absent by design — every valuation recorded is
    denominated in it, so changing it would reinterpret history."""

    name = serializers.CharField(max_length=120, required=False)
    kind = serializers.ChoiceField(choices=AssetKind.choices, required=False)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True)
    acquired_on = serializers.DateField(required=False, allow_null=True)
    acquisition_cost_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    secured_by_debt_id = serializers.UUIDField(required=False, allow_null=True)
    include_in_net_worth = serializers.BooleanField(required=False)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Nothing to change.")
        return attrs


class ValuationCreateSerializer(serializers.Serializer):
    value_minor = serializers.IntegerField(min_value=0)
    as_of = serializers.DateField(required=False, allow_null=True)
    source = serializers.ChoiceField(choices=ValuationSource.choices, default=ValuationSource.OWNER)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
