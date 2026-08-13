"""The Phase 1 API: scenarios, projections and the calculator library.

Gated on `SMART_PLANNING`, the same feature that already covers what-if
modelling and the Financial Review — this is the deep version of that promise,
not a new commercial tier.

Response shapes are assembled explicitly (see `serializers`). Projection
payloads can be large — a forty-year run is 480 points across two legs — so
every projection response carries a `points` array the client can chart
directly and a summary block it can render without walking the array.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.plan_catalogue import PlanFeature
from apps.common.api_base import TenantScopedAPIView, require_feature
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import adapters, calculators, services
from ..events import EventParamError
from ..models import AssumptionSet, Scenario, ScenarioEvent
from .serializers import (
    CALCULATORS,
    AssumptionSetSerializer,
    CompareSerializer,
    ScenarioEventWriteSerializer,
    ScenarioWriteSerializer,
    event_catalogue,
)

PLANNING = require_feature(PlanFeature.SMART_PLANNING)


def _scenario_out(scenario: Scenario) -> dict:
    return {
        "id": str(scenario.id),
        "name": scenario.name,
        "description": scenario.description,
        "status": scenario.status,
        "visibility": scenario.visibility,
        "horizon_months": scenario.horizon_months,
        "assumption_set_id": str(scenario.assumption_set_id) if scenario.assumption_set_id else None,
        "duplicated_from_id": (str(scenario.duplicated_from_id) if scenario.duplicated_from_id else None),
        "created_at": scenario.created_at,
        "updated_at": scenario.updated_at,
        "events": [_event_out(e) for e in scenario.events.all()],
    }


def _event_out(event: ScenarioEvent) -> dict:
    return {
        "id": str(event.id),
        "kind": event.kind,
        "label": str(event),
        "start_month": event.start_month,
        "params": event.params,
        "is_enabled": event.is_enabled,
        "sort_order": event.sort_order,
    }


def _assumptions_out(assumption_set: AssumptionSet) -> dict:
    return {
        "id": str(assumption_set.id),
        "name": assumption_set.name,
        "is_default": assumption_set.is_default,
        "notes": assumption_set.notes,
        "annual_inflation": str(assumption_set.annual_inflation),
        "annual_salary_growth": str(assumption_set.annual_salary_growth),
        "annual_investment_return": str(assumption_set.annual_investment_return),
        "annual_cash_return": str(assumption_set.annual_cash_return),
        "effective_tax_rate": str(assumption_set.effective_tax_rate),
        "annual_property_growth": str(assumption_set.annual_property_growth),
    }


def _projection_out(result) -> dict:
    return {
        "currency": result.currency,
        "as_of": result.as_of,
        "months": result.months,
        "summary": {
            "opening_net_worth_minor": result.opening_net_worth_minor,
            "closing_net_worth_minor": result.closing_net_worth_minor,
            "lowest_liquid_minor": result.lowest_liquid_minor,
            "lowest_liquid_month": result.lowest_liquid_month,
            "first_negative_month": result.first_negative_month,
            "first_negative_on": result.first_negative_on,
            "debt_free_month": result.debt_free_month,
            "total_interest_paid_minor": result.total_interest_paid_minor,
        },
        "points": [
            {
                "month": p.month,
                "on": p.on,
                "income_minor": p.income_minor,
                "expenses_minor": p.expenses_minor,
                "debt_payments_minor": p.debt_payments_minor,
                "net_cashflow_minor": p.net_cashflow_minor,
                "liquid_minor": p.liquid_minor,
                "investment_minor": p.investment_minor,
                "other_assets_minor": p.other_assets_minor,
                "debt_balance_minor": p.debt_balance_minor,
                "net_worth_minor": p.net_worth_minor,
                "events": list(p.events),
            }
            for p in result.points
        ],
        "assumptions": result.assumptions,
        "warnings": result.warnings,
    }


def _run_out(run: services.ScenarioRun) -> dict:
    return {
        "scenario_id": run.scenario_id,
        "scenario_name": run.scenario_name,
        "baseline": _projection_out(run.baseline),
        "scenario": _projection_out(run.scenario),
        "delta": {
            "net_worth_minor": run.net_worth_delta_minor,
            "trough_minor": run.trough_delta_minor,
        },
        "notes": run.notes,
    }


def _position_error(exc: adapters.NoPositionError) -> Response:
    return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)


def _bad_request(exc: DjangoValidationError | Exception) -> Response:
    """Turn a model-level validation failure into a 400.

    `ScenarioEvent.save()` calls `full_clean`, so an event whose parameters do
    not match its schema raises Django's `ValidationError` — which the DRF
    exception handler does not recognise and would render as a 500. The
    parameters came from the request body, so the correct answer is a 400
    naming the offending key.
    """
    if isinstance(exc, DjangoValidationError):
        detail = "; ".join(
            f"{field}: {' '.join(messages)}" for field, messages in getattr(exc, "message_dict", {}).items()
        ) or "; ".join(exc.messages)
    else:
        detail = str(exc)
    return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)


class ScenarioListView(TenantScopedAPIView, APIView):
    """List and create scenarios."""

    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = ScenarioWriteSerializer

    @extend_schema(operation_id="scenario_list")
    def get(self, request):
        scenarios = Scenario.objects.prefetch_related("events").order_by("-updated_at")
        wanted_status = request.query_params.get("status")
        if wanted_status:
            scenarios = scenarios.filter(status=wanted_status)
        return Response({"results": [_scenario_out(s) for s in scenarios]})

    @extend_schema(operation_id="scenario_create")
    def post(self, request):
        s = ScenarioWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        assumption_id = data.pop("assumption_set_id", None)
        assumption_set = get_object_or_404(AssumptionSet, id=assumption_id) if assumption_id else None
        try:
            scenario = services.create_scenario(assumption_set=assumption_set, **data)
        except DjangoValidationError as exc:
            return _bad_request(exc)
        return Response(_scenario_out(scenario), status=status.HTTP_201_CREATED)


class ScenarioDetailView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = ScenarioWriteSerializer

    @extend_schema(operation_id="scenario_detail")
    def get(self, request, scenario_id):
        scenario = get_object_or_404(Scenario.objects.prefetch_related("events"), id=scenario_id)
        return Response(_scenario_out(scenario))

    @extend_schema(operation_id="scenario_update")
    def patch(self, request, scenario_id):
        scenario = get_object_or_404(Scenario, id=scenario_id)
        s = ScenarioWriteSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        for field, value in s.validated_data.items():
            if field == "assumption_set_id":
                scenario.assumption_set = get_object_or_404(AssumptionSet, id=value) if value else None
            else:
                setattr(scenario, field, value)
        try:
            scenario.full_clean(exclude=["tenant_id", "created_by", "updated_by"])
            scenario.save()
        except DjangoValidationError as exc:
            return _bad_request(exc)
        return Response(_scenario_out(scenario))

    @extend_schema(operation_id="scenario_delete")
    def delete(self, request, scenario_id):
        scenario = get_object_or_404(Scenario, id=scenario_id)
        scenario.delete()  # soft delete
        return Response(status=status.HTTP_204_NO_CONTENT)


class ScenarioEventsView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.MEMBER
    serializer_class = ScenarioEventWriteSerializer

    @extend_schema(operation_id="scenario_event_create")
    def post(self, request, scenario_id):
        scenario = get_object_or_404(Scenario, id=scenario_id)
        s = ScenarioEventWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        enabled = data.pop("is_enabled", True)
        try:
            event = services.add_event(scenario=scenario, **data)
        except (services.ScenarioError, EventParamError, DjangoValidationError) as exc:
            return _bad_request(exc)
        if not enabled:
            event.is_enabled = False
            event.save()
        return Response(_event_out(event), status=status.HTTP_201_CREATED)


class ScenarioEventDetailView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.MEMBER
    serializer_class = ScenarioEventWriteSerializer

    @extend_schema(operation_id="scenario_event_update")
    def patch(self, request, scenario_id, event_id):
        event = get_object_or_404(ScenarioEvent, id=event_id, scenario_id=scenario_id)
        s = ScenarioEventWriteSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        for field, value in s.validated_data.items():
            setattr(event, field, value)
        try:
            event.save()
        except DjangoValidationError as exc:
            return _bad_request(exc)
        return Response(_event_out(event))

    @extend_schema(operation_id="scenario_event_delete")
    def delete(self, request, scenario_id, event_id):
        event = get_object_or_404(ScenarioEvent, id=event_id, scenario_id=scenario_id)
        event.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ScenarioRunView(TenantScopedAPIView, APIView):
    """Project a saved scenario against the household's real position."""

    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="scenario_run")
    def get(self, request, scenario_id):
        scenario = get_object_or_404(Scenario.objects.prefetch_related("events"), id=scenario_id)
        try:
            run = services.run(scenario)
        except adapters.NoPositionError as exc:
            return _position_error(exc)
        except services.ScenarioError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_run_out(run))


class ScenarioDuplicateView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.MEMBER
    serializer_class = None

    @extend_schema(operation_id="scenario_duplicate")
    def post(self, request, scenario_id):
        scenario = get_object_or_404(Scenario, id=scenario_id)
        copy = services.duplicate_scenario(scenario, name=request.data.get("name"))
        return Response(_scenario_out(copy), status=status.HTTP_201_CREATED)


class ScenarioArchiveView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.MEMBER
    serializer_class = None

    @extend_schema(operation_id="scenario_archive")
    def post(self, request, scenario_id):
        scenario = get_object_or_404(Scenario, id=scenario_id)
        return Response(_scenario_out(services.archive_scenario(scenario)))


class ScenarioCompareView(TenantScopedAPIView, APIView):
    """Run several scenarios against one shared snapshot of the position."""

    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = CompareSerializer

    @extend_schema(operation_id="scenario_compare")
    def post(self, request):
        s = CompareSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        ids = [str(i) for i in s.validated_data["scenario_ids"]]
        scenarios = list(Scenario.objects.prefetch_related("events").filter(id__in=ids))
        if len(scenarios) != len(ids):
            return Response(
                {"detail": "One or more scenarios could not be found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Preserve the caller's ordering: a comparison table that reorders
        # itself between requests is disorienting.
        by_id = {str(s_.id): s_ for s_ in scenarios}
        ordered = [by_id[i] for i in ids]
        try:
            comparison = services.compare(ordered)
        except adapters.NoPositionError as exc:
            return _position_error(exc)
        except services.ScenarioError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "as_of": comparison.as_of,
                "currency": comparison.currency,
                "runs": [_run_out(r) for r in comparison.runs],
                "notes": comparison.notes,
            }
        )


class BaselineProjectionView(TenantScopedAPIView, APIView):
    """The household's position projected forward with no scenario at all.

    The dashboard's opening view: where this trajectory leads if nothing
    changes, which is the question every scenario is measured against.
    """

    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="projection_baseline")
    def get(self, request):
        try:
            months = int(request.query_params.get("months", 120))
        except ValueError:
            return Response({"detail": "months must be an integer."}, status=400)
        if not 1 <= months <= calculators.MAX_HORIZON_MONTHS:
            return Response(
                {"detail": f"months must be between 1 and {calculators.MAX_HORIZON_MONTHS}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            position = adapters.current_position()
        except adapters.NoPositionError as exc:
            return _position_error(exc)

        assumption_set = services.ensure_default_assumption_set()
        result = adapters.project_live(
            position=position,
            assumptions=services.to_engine_assumptions(assumption_set),
            months=months,
        )
        return Response(
            {
                "position": {
                    "currency": position.currency,
                    "as_of": position.as_of,
                    "liquid_minor": position.liquid_minor,
                    "investment_minor": position.investment_minor,
                    "other_assets_minor": position.other_assets_minor,
                    "monthly_net_income_minor": position.monthly_net_income_minor,
                    "monthly_expenses_minor": position.monthly_expenses_minor,
                    "net_worth_minor": position.net_worth_minor,
                    "debts": [
                        {
                            "label": d.label,
                            "balance_minor": d.balance_minor,
                            "annual_rate": d.annual_rate,
                            "monthly_payment_minor": d.monthly_payment_minor,
                        }
                        for d in position.debts
                    ],
                },
                "projection": _projection_out(result),
            }
        )


class AssumptionSetView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = AssumptionSetSerializer

    @extend_schema(operation_id="assumptions_get")
    def get(self, request):
        return Response(_assumptions_out(services.ensure_default_assumption_set()))

    @extend_schema(operation_id="assumptions_update")
    def patch(self, request):
        assumption_set = services.ensure_default_assumption_set()
        s = AssumptionSetSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        try:
            updated = services.update_assumption_set(assumption_set, **s.validated_data)
        except services.ScenarioError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_assumptions_out(updated))


class EventCatalogueView(TenantScopedAPIView, APIView):
    """The fifteen life events and their parameter schemas.

    The scenario builder renders its forms from this, so adding a sixteenth
    life event is a backend change alone.
    """

    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="event_catalogue")
    def get(self, request):
        return Response({"results": event_catalogue()})


class CalculatorView(TenantScopedAPIView, APIView):
    """The calculator library, one endpoint per slug.

    POST rather than GET: the inputs are a structured body, and a mortgage
    quote in a query string is both unreadable and logged in places financial
    inputs should not be.
    """

    permission_classes = [IsTenantMember, PLANNING]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="calculator_run")
    def post(self, request, slug):
        entry = CALCULATORS.get(slug)
        if entry is None:
            return Response(
                {"detail": f"Unknown calculator {slug!r}.", "available": sorted(CALCULATORS)},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer_class, func_name = entry
        s = serializer_class(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            result = getattr(calculators, func_name)(**s.validated_data)
        except calculators.CalculatorError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_calculator_out(result))


def _calculator_out(result) -> dict:
    """Flatten a calculator dataclass, expanding the nested schedule types.

    Written by hand rather than with `dataclasses.asdict` so the wire format is
    a deliberate contract: `asdict` would expose every internal field and make
    a refactor a breaking change.
    """
    from dataclasses import fields, is_dataclass

    out: dict = {}
    for f in fields(result):
        value = getattr(result, f.name)
        if is_dataclass(value):
            out[f.name] = _calculator_out(value)
        elif isinstance(value, list) and value and is_dataclass(value[0]):
            out[f.name] = [_calculator_out(v) for v in value]
        else:
            out[f.name] = value
    # Convenience properties the dataclass exposes but `fields()` does not.
    if hasattr(result, "interest_share"):
        out["interest_share"] = result.interest_share
    return out
