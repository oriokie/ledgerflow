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
