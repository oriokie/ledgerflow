from __future__ import annotations

from rest_framework import serializers

from ..models import AssetClass, IncomeKind, PaymentFrequency


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


class SecurityTermsSerializer(serializers.Serializer):
    """What an instrument has agreed to pay.

    Everything optional except the kind: only a fixed coupon needs the full
    set, and the service refuses that combination if any of it is missing.
    Demanding a rate for a money-market fund would be asking the user to invent
    the very number the fund refuses to promise.
    """

    income_kind = serializers.ChoiceField(choices=IncomeKind.choices)
    face_value_minor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    #: Basis points: 1250 is 12.5%.
    coupon_rate_bp = serializers.IntegerField(min_value=0, max_value=100_000, required=False, allow_null=True)
    payment_frequency = serializers.ChoiceField(
        choices=PaymentFrequency.choices, required=False, allow_blank=True, default=""
    )
    issued_on = serializers.DateField(required=False, allow_null=True)
    matures_on = serializers.DateField(required=False, allow_null=True)
    dividend_on_average_balance = serializers.BooleanField(required=False, default=False)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class RedemptionEntrySerializer(serializers.Serializer):
    on_date = serializers.DateField()
    #: Share of the ORIGINAL principal, in basis points — how offer documents
    #: state it ("10% per annum from year 3").
    portion_bp = serializers.IntegerField(min_value=1, max_value=10_000)


class RedemptionScheduleSerializer(serializers.Serializer):
    entries = RedemptionEntrySerializer(many=True)


class RedemptionSerializer(serializers.Serializer):
    """Principal handed back. Quantity omitted means the whole position matured."""

    financial_account_id = serializers.UUIDField()
    security_id = serializers.UUIDField()
    amount_minor = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(max_digits=28, decimal_places=8, required=False, allow_null=True)
    occurred_on = serializers.DateField(required=False, allow_null=True)
    cash_account_id = serializers.UUIDField(required=False, allow_null=True)
    memo = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
