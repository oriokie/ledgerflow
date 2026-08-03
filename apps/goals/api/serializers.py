from __future__ import annotations

from rest_framework import serializers

from ..models import GoalKind, GoalPriority, GoalStatus, GoalTracking


class GoalCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    kind = serializers.ChoiceField(choices=GoalKind.choices, default=GoalKind.CUSTOM)
    currency = serializers.CharField(max_length=3)
    target_minor = serializers.IntegerField(min_value=1)
    target_date = serializers.DateField(required=False, allow_null=True)
    # Omitted priority is filled from the kind by the service, so a caller who
    # doesn't care still gets a sensible funding order.
    priority = serializers.ChoiceField(choices=GoalPriority.choices, required=False, allow_null=True)
    tracking = serializers.ChoiceField(choices=GoalTracking.choices, default=GoalTracking.MANUAL)
    linked_account_id = serializers.UUIDField(required=False, allow_null=True)
    planned_monthly_minor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class GoalUpdateSerializer(serializers.Serializer):
    """Plan and presentation only.

    `currency` and `tracking` are absent by design: both change how every
    contribution already recorded should be read, so allowing edits would
    reinterpret history rather than correct it.
    """

    name = serializers.CharField(max_length=120, required=False)
    kind = serializers.ChoiceField(choices=GoalKind.choices, required=False)
    target_minor = serializers.IntegerField(min_value=1, required=False)
    target_date = serializers.DateField(required=False, allow_null=True)
    priority = serializers.ChoiceField(choices=GoalPriority.choices, required=False)
    planned_monthly_minor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    status = serializers.ChoiceField(choices=GoalStatus.choices, required=False)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)


class AutoContributionSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    amount_minor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    # 1-28 only, so the instruction fires in every month including February.
    day_of_month = serializers.IntegerField(min_value=1, max_value=28, required=False, allow_null=True)


class ContributionCreateSerializer(serializers.Serializer):
    """Log a contribution, optionally funding it for real.

    ``from_account_id`` is what separates "I already set this aside" from
    "move this money now". Omit it and nothing but the goal changes; supply it
    and a genuine transfer posts, reducing that account's balance. Defaulting
    it either way would guess at a fact only the user knows, so it stays
    explicit.
    """

    amount_minor = serializers.IntegerField(min_value=1)
    occurred_on = serializers.DateField(required=False, allow_null=True)
    memo = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    source_transaction_id = serializers.UUIDField(required=False, allow_null=True)
    #: Fund the contribution by transferring out of this account.
    from_account_id = serializers.UUIDField(required=False, allow_null=True)
    #: Where the money lands. Defaults to the goal's linked account.
    to_account_id = serializers.UUIDField(required=False, allow_null=True)
