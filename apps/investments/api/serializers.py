from __future__ import annotations

from rest_framework import serializers

from ..models import AssetClass


class SecurityCreateSerializer(serializers.Serializer):
    symbol = serializers.CharField(max_length=32)
    name = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")
    asset_class = serializers.ChoiceField(choices=AssetClass.choices)
    currency = serializers.CharField(max_length=3, min_length=3)
    sector = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    exchange = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")


class TradeSerializer(serializers.Serializer):
    """A buy or a sell. Quantity is decimal because crypto and some funds trade
    in fractions; money stays in integer minor units throughout."""

    financial_account_id = serializers.UUIDField()
    security_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=28, decimal_places=8, min_value=0)
    amount_minor = serializers.IntegerField(min_value=1)
    fee_minor = serializers.IntegerField(min_value=0, required=False, default=0)
    occurred_on = serializers.DateField(required=False, allow_null=True)
    cash_account_id = serializers.UUIDField(required=False, allow_null=True)
    memo = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class DividendSerializer(serializers.Serializer):
    financial_account_id = serializers.UUIDField()
    security_id = serializers.UUIDField()
    amount_minor = serializers.IntegerField(min_value=1)
    occurred_on = serializers.DateField(required=False, allow_null=True)
    cash_account_id = serializers.UUIDField(required=False, allow_null=True)
    memo = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class PriceSerializer(serializers.Serializer):
    security_id = serializers.UUIDField()
    price_minor = serializers.IntegerField(min_value=0)
    as_of = serializers.DateField(required=False, allow_null=True)
    source = serializers.CharField(max_length=40, required=False, default="manual")


class SplitSerializer(serializers.Serializer):
    financial_account_id = serializers.UUIDField()
    security_id = serializers.UUIDField()
    ratio = serializers.DecimalField(max_digits=12, decimal_places=6, min_value=0)
    occurred_on = serializers.DateField(required=False, allow_null=True)


class SecurityUpdateSerializer(serializers.Serializer):
    """Partial edit. Every field optional — the common case is fixing one typo."""

    symbol = serializers.CharField(required=False, max_length=24)
    name = serializers.CharField(required=False, max_length=120)
    asset_class = serializers.CharField(required=False, max_length=24)
    currency = serializers.CharField(required=False, max_length=3)
    sector = serializers.CharField(required=False, allow_blank=True, max_length=60)
    exchange = serializers.CharField(required=False, allow_blank=True, max_length=24)
