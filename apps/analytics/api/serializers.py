from __future__ import annotations

from rest_framework import serializers

from ..filters import Period


class ReportQuerySerializer(serializers.Serializer):
    """Filters shared by every report.

    One serializer for all fourteen: the filters are the same because the
    questions are the same shape — a window, optionally narrowed to some
    accounts or categories. A per-report filter schema would be fourteen ways
    to express one idea.
    """

    period = serializers.ChoiceField(
        choices=[(p, p) for p in Period.ALL], required=False, default=Period.LAST_12_MONTHS
    )
    #: Override the named period. Both must be supplied together.
    start = serializers.DateField(required=False, allow_null=True)
    end = serializers.DateField(required=False, allow_null=True)
    account_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True
    )
    category_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True
    )
    currency = serializers.CharField(max_length=3, min_length=3, required=False, allow_null=True)
    #: Include the preceding window of equal length, for comparison figures.
    compare_previous = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        start, end = attrs.get("start"), attrs.get("end")
        period = attrs.get("period")

        if bool(start) != bool(end):
            # A half-specified custom window would silently fall back to the
            # named period, which is a confusing way to be wrong.
            raise serializers.ValidationError(
                "Provide both start and end for a custom range, or neither."
            )
        if start and end and start > end:
            raise serializers.ValidationError("Start must not be after end.")

        if period == Period.CUSTOM and not start:
            # `custom` is only meaningful with dates; without them the window
            # can't be resolved at all.
            raise serializers.ValidationError(
                "A custom period needs both a start and an end."
            )

        # Supplying dates *is* the request for a custom window. Honouring the
        # named period instead would quietly answer a different question.
        if start and end:
            attrs["period"] = Period.CUSTOM
        return attrs
