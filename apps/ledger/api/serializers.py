from __future__ import annotations

from rest_framework import serializers

from ..models import Account, Direction


class AccountSerializer(serializers.ModelSerializer):
    balance_minor = serializers.IntegerField(source="balance.balance_minor", read_only=True)

    class Meta:
        model = Account
        fields = ["id", "name", "kind", "currency", "is_system", "balance_minor", "created_at"]
        read_only_fields = ["id", "is_system", "balance_minor", "created_at"]


class LineInputSerializer(serializers.Serializer):
    account_id = serializers.UUIDField()
    direction = serializers.ChoiceField(choices=Direction.choices)
    amount_minor = serializers.IntegerField(min_value=1)


class PostEntrySerializer(serializers.Serializer):
    occurred_at = serializers.DateTimeField()
    memo = serializers.CharField(max_length=255, allow_blank=True, required=False, default="")
    idempotency_key = serializers.CharField(max_length=128)
    lines = LineInputSerializer(many=True, min_length=2)

    def validate_lines(self, value):
        debits = sum(line["amount_minor"] for line in value if line["direction"] == Direction.DEBIT)
        credits = sum(line["amount_minor"] for line in value if line["direction"] == Direction.CREDIT)
        if debits != credits:
            raise serializers.ValidationError("Entry is unbalanced: debits must equal credits.")
        return value
