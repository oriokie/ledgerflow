"""Serialisers for the household API."""

from __future__ import annotations

from rest_framework import serializers

from ..models import RelationshipKind, SharingPolicy


class HouseholdProfileSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    relationship = serializers.ChoiceField(choices=RelationshipKind.choices, required=False)
    #: Nullable on purpose: "not agreed yet" is a real state and the honest
    #: default, and clearing a share has to be expressible.
    contribution_share = serializers.DecimalField(
        max_digits=5, decimal_places=4, required=False, allow_null=True, min_value=0, max_value=1
    )


class DependantSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    relationship = serializers.ChoiceField(choices=RelationshipKind.choices, default=RelationshipKind.CHILD)
    birth_year = serializers.IntegerField(min_value=1900, max_value=2200, required=False, allow_null=True)
    monthly_cost_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    support_until_year = serializers.IntegerField(
        min_value=1900, max_value=2200, required=False, allow_null=True
    )
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class AccountSharingSerializer(serializers.Serializer):
    policy = serializers.ChoiceField(choices=SharingPolicy.choices)
    is_joint = serializers.BooleanField(required=False, default=False)
    #: Null means "no individual owner" — which is what a joint account is.
    owner_membership_id = serializers.UUIDField(required=False, allow_null=True)
