from __future__ import annotations

from rest_framework import serializers

from ..models import ReceivableKind


class ReceivableCreateSerializer(serializers.Serializer):
    counterparty = serializers.CharField(max_length=120)
    kind = serializers.ChoiceField(choices=ReceivableKind.choices, default=ReceivableKind.PERSONAL)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    currency = serializers.CharField(max_length=3, min_length=3)
    principal_minor = serializers.IntegerField(min_value=1)
    lent_on = serializers.DateField()
    #: Optional on purpose — most informal loans have no date attached, and
    #: inventing one would manufacture an overdue warning nobody agreed to.
    due_on = serializers.DateField(required=False, allow_null=True)
    source_account_id = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class ReceivableUpdateSerializer(serializers.Serializer):
    """Everything editable.

    ``currency`` is absent by design: every repayment already recorded is
    denominated in the original currency, so changing it would reinterpret
    history rather than correct it — the same refusal income sources make.
    """

    counterparty = serializers.CharField(max_length=120, required=False)
    kind = serializers.ChoiceField(choices=ReceivableKind.choices, required=False)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True)
    principal_minor = serializers.IntegerField(min_value=1, required=False)
    lent_on = serializers.DateField(required=False)
    due_on = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Nothing to change.")
        return attrs


class RepaymentCreateSerializer(serializers.Serializer):
    amount_minor = serializers.IntegerField(min_value=1)
    received_on = serializers.DateField()
    transaction_id = serializers.UUIDField(required=False, allow_null=True)
    memo = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
