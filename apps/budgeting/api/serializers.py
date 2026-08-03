from __future__ import annotations

from rest_framework import serializers

from ..models import BudgetPeriod


class BudgetCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    currency = serializers.CharField(max_length=3, min_length=3)
    starts_on = serializers.DateField()
    period = serializers.ChoiceField(choices=BudgetPeriod.choices, default=BudgetPeriod.MONTHLY)


class BudgetSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField()
    currency = serializers.CharField()
    period = serializers.CharField()
    starts_on = serializers.DateField()


class BudgetLineCreateSerializer(serializers.Serializer):
    category_id = serializers.UUIDField()
    limit_minor = serializers.IntegerField(min_value=0)
    rollover = serializers.BooleanField(default=False)


class BudgetLineUpdateSerializer(serializers.Serializer):
    limit_minor = serializers.IntegerField(min_value=0, required=False)
    rollover = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Nothing to update.")
        return attrs
