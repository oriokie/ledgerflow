from __future__ import annotations

from rest_framework import serializers

from ..models import AutomationRule, CategorizationSuggestion


class CategorizationSuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CategorizationSuggestion
        fields = [
            "id",
            "transaction_id",
            "suggested_category_id",
            "confidence",
            "status",
            "provider",
            "provider_kind",
            "provider_version",
            "rationale",
            "decided_at",
            "created_at",
        ]
        read_only_fields = fields


class AutomationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutomationRule
        fields = [
            "id",
            "name",
            "is_active",
            "priority",
            "conditions",
            "actions",
            "stop_processing",
            "match_count",
            "last_matched_at",
        ]
        read_only_fields = ["id", "match_count", "last_matched_at"]


class AutomationRuleWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    conditions = serializers.DictField()
    actions = serializers.ListField(child=serializers.DictField())
    priority = serializers.IntegerField(required=False, default=100)
    is_active = serializers.BooleanField(required=False, default=True)
    stop_processing = serializers.BooleanField(required=False, default=False)


class AutomationRuleUpdateSerializer(serializers.Serializer):
    """Every field optional so a PATCH can edit just one thing (e.g. flip
    `is_active` to pause a rule) without resending the whole body."""

    name = serializers.CharField(max_length=120, required=False)
    conditions = serializers.DictField(required=False)
    actions = serializers.ListField(child=serializers.DictField(), required=False)
    priority = serializers.IntegerField(required=False)
    is_active = serializers.BooleanField(required=False)
    stop_processing = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Nothing to change.")
        return attrs
