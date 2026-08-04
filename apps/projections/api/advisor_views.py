"""Phase 2 endpoints: simulation, sensitivity, risk and the decision assistant.

Kept in their own module rather than swelling `views.py`, because the two halves
answer different kinds of question. Phase 1 serves *projections* — here is the
line. Phase 2 serves *positions* — here is what we think, and why, and how sure.

Every endpoint here shares one contract: the response carries the figures, the
assumptions behind them, and a confidence statement. Nothing returns a bare
number. That is the product's stated standard for decision support, and it is
cheaper to enforce at the boundary than to remember at each call site.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api_base import TenantScopedAPIView
from apps.intelligence import advisor
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import adapters, decisions, risk, sensitivity, services, simulation
from ..calculators import CalculatorError
from .serializers import (
    DECISION_SERIALIZERS,
    RiskQuerySerializer,
    SensitivitySerializer,
    SimulationSerializer,
    WhatIfSerializer,
)
from .views import PLANNING, _position_error, _projection_out


def _context(months: int | None = None):
    """The three things every Phase 2 endpoint needs: the household's position,
    the workspace's assumptions, and a horizon."""
    position = adapters.current_position()
    assumption_set = services.ensure_default_assumption_set()
    return position, services.to_engine_assumptions(assumption_set), months


def _dc(value):
    """Dataclass to dict, recursively, skipping private fields."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _dc(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, list):
        return [_dc(v) for v in value]
    if isinstance(value, tuple):
        return [_dc(v) for v in value]
    return value


class SimulationView(TenantScopedAPIView, APIView):
    """Monte Carlo over the household's position.

    POST because the settings are a structured body, and because a thousand
    engine runs is not something a browser should be able to trigger by
    prefetching a link.
    """

    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = SimulationSerializer

    @extend_schema(operation_id="projection_simulate")
    def post(self, request):
        s = SimulationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        try:
            position, assumptions, _ = _context()
        except adapters.NoPositionError as exc:
            return _position_error(exc)

        scenario_events = []
        if data.get("scenario_id"):
            from ..models import Scenario

            scenario = Scenario.objects.filter(id=data["scenario_id"]).first()
            if scenario is None:
                return Response({"detail": "Scenario not found."}, status=status.HTTP_404_NOT_FOUND)
            scenario_events = services.compile_scenario_events(scenario, position, assumptions)

        try:
            settings = simulation.SimulationSettings(
                trials=data["trials"],
                seed=data["seed"],
                return_volatility=data["return_volatility"],
                inflation_volatility=data["inflation_volatility"],
                income_shock_probability=data["income_shock_probability"],
            )
            result = simulation.simulate(
                position=position,
                assumptions=assumptions,
                events=scenario_events,
                months=data["months"],
                settings=settings,
            )
        except simulation.SimulationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "currency": result.currency,
                "trials": result.trials,
                "seed": result.seed,
                "months": result.months,
                "closing_net_worth": _dc(result.closing_net_worth),
                "trough": _dc(result.trough),
                "success_probability": result.success_probability,
                "failure_probability": result.failure_probability,
                "median_failure_month": result.median_failure_month,
                "bands": result.bands,
                "assumptions": result.assumptions,
                "deterministic": (_projection_out(result.deterministic) if result.deterministic else None),
            }
        )


class SensitivityView(TenantScopedAPIView, APIView):
    """Which assumption is actually load-bearing."""

    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = SensitivitySerializer

    @extend_schema(operation_id="projection_sensitivity")
    def get(self, request):
        s = SensitivitySerializer(data=request.query_params)
        s.is_valid(raise_exception=True)
        try:
            position, assumptions, _ = _context()
        except adapters.NoPositionError as exc:
            return _position_error(exc)

        result = sensitivity.analyse(
            position=position, assumptions=assumptions, months=s.validated_data["months"]
        )
        return Response(
            {
                "currency": result.currency,
                "months": result.months,
                "baseline_closing_minor": result.baseline_closing_minor,
                "swings": [
                    {**_dc(swing), "spread_minor": swing.spread_minor, "direction": swing.direction}
                    for swing in result.swings
                ],
                "notes": result.notes,
            }
        )


class WhatIfView(TenantScopedAPIView, APIView):
    """One named question — "what if inflation reaches 10%"."""

    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = WhatIfSerializer

    @extend_schema(operation_id="projection_what_if")
    def post(self, request):
        s = WhatIfSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        try:
            position, assumptions, _ = _context()
        except adapters.NoPositionError as exc:
            return _position_error(exc)

        try:
            result = sensitivity.what_if(
                position=position,
                assumptions=assumptions,
                months=data["months"],
                inflation=data.get("inflation"),
                investment_return=data.get("investment_return"),
                salary_growth=data.get("salary_growth"),
                rate_shift=data.get("rate_shift"),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({**_dc(result), "delta_minor": result.delta_minor})


class RiskView(TenantScopedAPIView, APIView):
    """The exposures a projection line does not show."""

    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = RiskQuerySerializer

    @extend_schema(operation_id="projection_risk")
    def get(self, request):
        try:
            position, _assumptions, _ = _context()
        except adapters.NoPositionError as exc:
            return _position_error(exc)

        profile = risk.assess(position=position, income_sources=_income_sources())
        return Response(
            {
                "currency": profile.currency,
                "resilience": profile.resilience,
                "headline": profile.headline,
                "factors": [_dc(f) for f in profile.factors],
                "notes": profile.notes,
            }
        )


def _income_sources() -> list[int] | None:
    """Monthly amounts per recorded income source, or None.

    None rather than an empty list when the income context has nothing: the
    risk module treats the two differently on purpose, omitting concentration
    rather than reporting a household as well-diversified on no evidence.
    """
    try:
        from apps.income import selectors as income_selectors

        views = income_selectors.source_views()
    except Exception:  # pragma: no cover - income app optional in some installs
        return None
    amounts = [v.monthly_equivalent_minor for v in views if getattr(v, "monthly_equivalent_minor", None)]
    return amounts or None


class DecisionView(TenantScopedAPIView, APIView):
    """The named questions, one endpoint per slug.

    Each returns the verdict, the figures behind it, and — separately — the
    prose. Keeping the two apart is deliberate: a client that wants to render
    its own layout gets structured findings, and the explanation never becomes
    the only place a number appears.
    """

    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="decision_ask")
    def post(self, request, slug):
        entry = DECISION_SERIALIZERS.get(slug)
        if entry is None:
            return Response(
                {"detail": f"Unknown question {slug!r}.", "available": sorted(DECISION_SERIALIZERS)},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer_class, func_name = entry
        s = serializer_class(data=request.data)
        s.is_valid(raise_exception=True)

        try:
            position, assumptions, _ = _context()
        except adapters.NoPositionError as exc:
            return _position_error(exc)

        kwargs = dict(s.validated_data)
        explain = kwargs.pop("explain", True)
        func = getattr(decisions, func_name)
        if "assumptions" in func.__code__.co_varnames:
            kwargs["assumptions"] = assumptions

        try:
            decision = func(position=position, **kwargs)
        except CalculatorError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        explanation = advisor.explain(decision, currency=position.currency, use_llm=explain)
        return Response(
            {
                "question": decision.question,
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


class DecisionCatalogueView(TenantScopedAPIView, APIView):
    """What can be asked, and what each question needs to be answered."""

    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="decision_catalogue")
    def get(self, request):
        out = []
        for slug, (serializer_class, _func) in sorted(DECISION_SERIALIZERS.items()):
            instance = serializer_class()
            out.append(
                {
                    "slug": slug,
                    "question": getattr(serializer_class, "question", slug),
                    "fields": [
                        {
                            "name": name,
                            "required": field.required,
                            "type": type(field).__name__.replace("Field", "").lower(),
                        }
                        for name, field in instance.fields.items()
                        if name != "explain"
                    ],
                }
            )
        return Response({"results": out})


__all__ = [
    "DecisionCatalogueView",
    "DecisionView",
    "RiskView",
    "SensitivityView",
    "SimulationView",
    "WhatIfView",
]
