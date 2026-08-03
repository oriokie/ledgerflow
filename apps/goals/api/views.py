from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api_base import TenantScopedAPIView, WriteRequiresMemberMixin
from apps.finance.models import FinancialAccount, Transaction
from apps.finance.services import FinanceError
from apps.tenancy.permissions import IsTenantMember

from .. import forecasting, recommendations, selectors, services
from ..models import SavingsGoal
from .serializers import (
    AutoContributionSerializer,
    ContributionCreateSerializer,
    GoalCreateSerializer,
    GoalUpdateSerializer,
)


def _goal_out(goal: SavingsGoal, status_view=None) -> dict:
    status_view = status_view or selectors.goal_status(goal)
    return {
        "id": goal.id,
        "name": goal.name,
        "currency": goal.currency,
        "target_minor": goal.target_minor,
        "target_date": goal.target_date,
        "tracking": goal.tracking,
        "linked_account_id": goal.linked_account_id,
        "status": goal.status,
        "notes": goal.notes,
        "saved_minor": status_view.saved_minor,
        "remaining_minor": status_view.remaining_minor,
        "percent": status_view.percent,
        "is_met": status_view.is_met,
        "required_monthly_minor": status_view.required_monthly_minor(),
        "kind": goal.kind,
        "priority": goal.priority,
        "planned_monthly_minor": goal.planned_monthly_minor,
        "auto_contribute_enabled": goal.auto_contribute_enabled,
        "auto_contribute_minor": goal.auto_contribute_minor,
        "auto_contribute_day": goal.auto_contribute_day,
    }


def _forecast_out(f: forecasting.GoalForecast) -> dict:
    """Serialised forecast.

    `success_probability` is null whenever there isn't enough history to
    estimate one — clients must render the absence, not substitute a zero.
    """
    return {
        "goal_id": f.goal_id,
        "currency": f.currency,
        "saved_minor": f.saved_minor,
        "target_minor": f.target_minor,
        "remaining_minor": f.remaining_minor,
        "percent": f.percent,
        "required_monthly_minor": f.required_monthly_minor,
        "planned_monthly_minor": f.planned_monthly_minor,
        "observed_monthly_minor": f.observed_monthly_minor,
        "monthly_shortfall_minor": f.monthly_shortfall_minor,
        "projected_completion": f.projected_completion,
        "target_date": f.target_date,
        "on_track": f.on_track,
        "success_probability": f.success_probability,
        "consistency": f.consistency,
    }


class GoalView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = GoalCreateSerializer

    def get(self, request):
        include_archived = request.query_params.get("include_archived", "").lower() in (
            "1",
            "true",
            "yes",
        )
        goals = selectors.list_goals(include_archived=include_archived)
        return Response([_goal_out(g) for g in goals])

    def post(self, request):
        s = GoalCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        linked = None
        if v.get("linked_account_id"):
            linked = FinancialAccount.objects.filter(id=v["linked_account_id"]).first()
            if linked is None:
                return Response({"detail": "linked_account not found"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            goal = services.create_goal(
                name=v["name"],
                currency=v["currency"].upper(),
                target_minor=v["target_minor"],
                target_date=v.get("target_date"),
                tracking=v["tracking"],
                linked_account=linked,
                notes=v.get("notes", ""),
                kind=v.get("kind"),
                priority=v.get("priority"),
                planned_monthly_minor=v.get("planned_monthly_minor"),
            )
        except services.GoalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_goal_out(goal), status=status.HTTP_201_CREATED)


class GoalDetailView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = None

    @extend_schema(operation_id="goal_retrieve")
    def get(self, request, goal_id):
        goal = SavingsGoal.objects.filter(id=goal_id).first()
        if goal is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(_goal_out(goal))

    @extend_schema(request=GoalUpdateSerializer)
    def patch(self, request, goal_id):
        goal = SavingsGoal.objects.filter(id=goal_id).first()
        if goal is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = GoalUpdateSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        try:
            goal = services.update_goal(goal=goal, **s.validated_data)
        except services.GoalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_goal_out(goal))

    def delete(self, request, goal_id):
        """Archive (soft state change), not a hard delete — goal history is
        worth keeping."""
        goal = SavingsGoal.objects.filter(id=goal_id).first()
        if goal is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        services.archive_goal(goal=goal)
        return Response(status=status.HTTP_204_NO_CONTENT)


class GoalContributionView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = ContributionCreateSerializer

    @extend_schema(operation_id="goal_contributions_list")
    def get(self, request, goal_id):
        """Recent contributions for a goal — the momentum timeline. Most recent
        first (by date, then insertion)."""
        goal = SavingsGoal.objects.filter(id=goal_id).first()
        if goal is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        contributions = goal.contributions.order_by("-occurred_on", "-created_at")[:50]
        return Response(
            [
                {
                    "id": c.id,
                    "amount_minor": c.amount_minor,
                    "occurred_on": c.occurred_on,
                    "memo": c.memo,
                }
                for c in contributions
            ]
        )

    @extend_schema(request=ContributionCreateSerializer)
    def post(self, request, goal_id):
        goal = SavingsGoal.objects.filter(id=goal_id).first()
        if goal is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = ContributionCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        source_txn = None
        if v.get("source_transaction_id"):
            source_txn = Transaction.objects.filter(id=v["source_transaction_id"]).first()

        # Resolved through the tenant-scoped manager, so a foreign account id
        # reads as "not found" rather than reaching another workspace's ledger.
        from_account = to_account = None
        if v.get("from_account_id"):
            from_account = FinancialAccount.objects.filter(id=v["from_account_id"]).first()
            if from_account is None:
                return Response(
                    {"detail": "That funding account doesn't exist."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        if v.get("to_account_id"):
            to_account = FinancialAccount.objects.filter(id=v["to_account_id"]).first()
            if to_account is None:
                return Response(
                    {"detail": "That destination account doesn't exist."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        try:
            contribution = services.add_contribution(
                goal=goal,
                amount_minor=v["amount_minor"],
                occurred_on=v.get("occurred_on"),
                memo=v.get("memo", ""),
                source_transaction=source_txn,
                from_account=from_account,
                to_account=to_account,
            )
        except (services.GoalError, FinanceError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        goal.refresh_from_db()
        return Response(
            {
                "id": contribution.id,
                "goal_id": goal.id,
                "amount_minor": contribution.amount_minor,
                "occurred_on": contribution.occurred_on,
                "funded": contribution.source_transaction_id is not None,
                "goal": _goal_out(goal),
            },
            status=status.HTTP_201_CREATED,
        )


class GoalForecastView(TenantScopedAPIView, APIView):
    """Forecast for a single goal: pace, projection, and likelihood."""

    permission_classes = [IsTenantMember]
    serializer_class = None

    @extend_schema(operation_id="goal_forecast")
    def get(self, request, goal_id):
        goal = SavingsGoal.objects.filter(id=goal_id).first()
        if goal is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        data = _forecast_out(forecasting.forecast(goal))
        data["projection"] = [
            {
                "month": p.month,
                "projected_minor": p.projected_minor,
                "target_minor": p.target_minor,
            }
            for p in forecasting.projection_series(goal)
        ]
        data["history"] = [
            {"month": h.month, "amount_minor": h.amount_minor}
            for h in forecasting.monthly_contribution_history(goal)
        ]
        return Response(data)


class GoalForecastListView(TenantScopedAPIView, APIView):
    """Forecasts for every live goal, in funding order."""

    permission_classes = [IsTenantMember]
    serializer_class = None

    @extend_schema(operation_id="goal_forecast_list")
    def get(self, request):
        return Response([_forecast_out(f) for f in forecasting.forecast_active_goals()])


class GoalRecommendationView(TenantScopedAPIView, APIView):
    """Suggested goals derived from this workspace's own figures.

    Returns an empty list rather than filler when the data doesn't support an
    honest recommendation.
    """

    permission_classes = [IsTenantMember]
    serializer_class = None

    @extend_schema(operation_id="goal_recommendations")
    def get(self, request):
        return Response(
            [
                {
                    "kind": r.kind,
                    "title": r.title,
                    "rationale": r.rationale,
                    "suggested_target_minor": r.suggested_target_minor,
                    "suggested_monthly_minor": r.suggested_monthly_minor,
                    "currency": r.currency,
                    "priority": r.priority,
                }
                for r in recommendations.recommend_goals()
            ]
        )


class GoalAutoContributionView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Standing monthly contribution rule for a goal."""

    permission_classes = [IsTenantMember]
    serializer_class = AutoContributionSerializer

    def put(self, request, goal_id):
        goal = SavingsGoal.objects.filter(id=goal_id).first()
        if goal is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = AutoContributionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            goal = services.set_auto_contribution(
                goal=goal,
                enabled=v["enabled"],
                amount_minor=v.get("amount_minor"),
                day_of_month=v.get("day_of_month"),
            )
        except services.GoalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_goal_out(goal))
