from __future__ import annotations

from rest_framework import serializers


class AskSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=500)
    #: Opt out of the model per request. The deterministic router answers
    #: either way, so turning it off costs nothing but nuance.
    use_llm = serializers.BooleanField(default=True)


class ForecastSerializer(serializers.Serializer):
    """No inputs — the forecast is derived from the twin's own measurements."""
