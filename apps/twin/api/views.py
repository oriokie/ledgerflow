"""The digital twin's API: what we have measured, how well we have predicted,
and asking in words.

The `/ask/` endpoint is the one worth reading carefully. It routes a sentence to
one of the Phase 2 evaluators and then hands off entirely — the figures come
from `decisions`, the prose from `advisor.explain`, which already refuses to
repeat a number the calculation did not produce. Nothing new computes anything
here, which is the point: the conversational surface adds a way to *reach* the
existing answers, not a second source of them.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api_base import TenantScopedAPIView
from apps.intelligence import advisor
from apps.projections import adapters, decisions
from apps.projections.api.serializers import DECISION_SERIALIZERS
from apps.projections.api.views import PLANNING, _position_error
from apps.projections.calculators import CalculatorError
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import calibration, conversation
from .. import parameters as twin_params
from .serializers import AskSerializer, ForecastSerializer


def _dc(value):
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _dc(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (list, tuple)):
        return [_dc(v) for v in value]
    return value


class TwinView(TenantScopedAPIView, APIView):
    """What the product has measured about this household."""

    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="twin_get")
    def get(self, request):
        twin = twin_params.build()
        return Response(
            {
                "currency": twin.currency,
                "as_of": twin.as_of,
                "months_observed": twin.months_observed,
                "confidence": twin.confidence,
                "parameters": [
                    {
                        **_dc(p),
                        "effective": round(p.effective, 4),
                        "differs_from_prior": p.differs_from_prior,
                    }
                    for p in twin.parameters
                ],
                "notes": twin.notes,
            }
        )


class CalibrationView(TenantScopedAPIView, APIView):
    """How well this has been predicting the household — including badly."""

    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = ForecastSerializer

    @extend_schema(operation_id="twin_calibration")
    def get(self, request):
        report = calibration.accuracy()
        return Response(
            {
                **_dc(report),
                "overall_median_error": report.overall_median_error,
            }
        )

    @extend_schema(operation_id="twin_forecast")
    def post(self, request):
        """Score any closed months, then record next month's forecast.

        Both in one call because they are two halves of the same habit, and a
        product that records forecasts but never scores them is worse than one
        that does neither — it accumulates the appearance of rigour.
        """
        scored = calibration.score()
        twin = twin_params.build()
        made = calibration.forecast_next_month(twin=twin)
        return Response(
            {
                "scored": scored,
                "recorded": [
                    {
                        "kind": m.kind,
                        "period": m.period,
                        "predicted_minor": m.predicted_minor,
                        "months_observed": m.months_observed,
                        "confidence": m.confidence,
                    }
                    for m in made
                ],
                "detail": (
                    f"{scored} closed month(s) scored; {len(made)} forecast(s) recorded " "for next month."
                ),
            }
        )


class AskView(TenantScopedAPIView, APIView):
    """Ask in words; get the same computed answer the forms give.

    A question that cannot be routed is refused with the list of what *can* be
    answered, rather than sent to the nearest-looking evaluator. Being
    confidently answered with the wrong question is worse than being asked to
    rephrase, because nothing in the output reveals which question was answered.
    """

    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = AskSerializer

    @extend_schema(operation_id="twin_ask")
    def post(self, request):
        s = AskSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        question = s.validated_data["question"]

        routing = conversation.route(question, use_llm=s.validated_data["use_llm"])
        if not routing.answerable:
            return Response(
                {
                    "answered": False,
                    "question": question,
                    "matched": routing.slug,
                    "missing": routing.missing,
                    "llm_used": routing.llm_used,
                    "detail": conversation.describe_missing(routing),
                    "available": conversation.QUESTION_LABELS,
                },
                status=status.HTTP_200_OK,
            )

        serializer_class, func_name = DECISION_SERIALIZERS[routing.slug]
        payload = serializer_class(data={**routing.params, "explain": True})
        if not payload.is_valid():
            return Response(
                {
                    "answered": False,
                    "question": question,
                    "matched": routing.slug,
                    "detail": "The numbers in that question did not make a valid enquiry.",
                    "errors": payload.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            position = adapters.current_position()
        except adapters.NoPositionError as exc:
            return _position_error(exc)

        kwargs = dict(payload.validated_data)
        kwargs.pop("explain", None)
        try:
            decision = getattr(decisions, func_name)(position=position, **kwargs)
        except CalculatorError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        explanation = advisor.explain(decision, currency=position.currency)
        return Response(
            {
                "answered": True,
                "question": question,
                "matched": routing.slug,
                "understood_as": conversation.QUESTION_LABELS[routing.slug],
                "llm_used": routing.llm_used,
                "verdict": decision.verdict,
                "headline": decision.headline,
                "confidence": decision.confidence,
                "because": [_dc(f) for f in decision.because],
                "costs": [_dc(f) for f in decision.costs],
                "risks": [_dc(f) for f in decision.risks],
                "alternatives": [_dc(f) for f in decision.alternatives],
                "assumptions": decision.assumptions,
                "explanation": {
                    "paragraphs": explanation.paragraphs,
                    "llm_used": explanation.llm_used,
                    "rejected_reason": explanation.rejected_reason,
                },
                "currency": position.currency,
            }
        )
