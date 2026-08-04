from __future__ import annotations

from rest_framework import serializers

from ..models import Invitation, Membership, Tenant, TenantType


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["id", "name", "type", "base_currency", "default_locale", "default_timezone", "created_at"]


class WorkspaceMembershipSerializer(serializers.ModelSerializer):
    """A workspace as seen by the current user: the tenant plus their role in it."""

    tenant = TenantSerializer()

    class Meta:
        model = Membership
        fields = ["id", "tenant", "role", "created_at"]


class CreateWorkspaceSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    type = serializers.ChoiceField(choices=TenantType.choices, default=TenantType.PERSONAL)
    base_currency = serializers.CharField(max_length=3, default="USD")
    locale = serializers.CharField(max_length=10, default="en-US")
    timezone = serializers.CharField(max_length=64, default="UTC")


class MemberSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user_id", "email", "full_name", "role", "created_at"]


class ChangeMemberRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Membership._meta.get_field("role").choices)


class CreateInvitationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=Membership._meta.get_field("role").choices)


class InvitationSerializer(serializers.ModelSerializer):
    invited_by_email = serializers.EmailField(source="invited_by.email", read_only=True, default=None)
    workspace_name = serializers.CharField(source="tenant.name", read_only=True)

    class Meta:
        model = Invitation
        fields = [
            "id",
            "email",
            "role",
            "status",
            "workspace_name",
            "invited_by_email",
            "expires_at",
            "created_at",
        ]


class AcceptInvitationSerializer(serializers.Serializer):
    token = serializers.CharField()


class WorkspaceAISettingsSerializer(serializers.Serializer):
    """A workspace's model override.

    The key is write-only, like every other credential in this codebase: a
    workspace can replace its key, nobody can read one back out. `api_key_set`
    tells the interface whether to show "replace" or "add" without disclosing
    anything.
    """

    provider = serializers.CharField(max_length=32, allow_blank=True, required=False)
    model = serializers.CharField(max_length=120, allow_blank=True, required=False)
    base_url = serializers.URLField(allow_blank=True, required=False)
    api_key = serializers.CharField(write_only=True, allow_blank=True, required=False)
    api_key_set = serializers.SerializerMethodField()

    def get_api_key_set(self, obj) -> bool:
        return bool(getattr(obj, "encrypted_api_key", ""))

    def validate_provider(self, value: str) -> str:
        if not value:
            return value
        from apps.intelligence.llm import PROVIDER_PRESETS

        if value not in PROVIDER_PRESETS:
            raise serializers.ValidationError(
                f"Unknown provider. Choose one of: {', '.join(sorted(PROVIDER_PRESETS))}."
            )
        return value
