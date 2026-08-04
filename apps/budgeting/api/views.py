from __future__ import annotations

from datetime import date

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.plan_catalogue import PlanFeature
from apps.common.api_base import TenantScopedAPIView, WriteRequiresMemberMixin, require_feature
from apps.finance.models import Category
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import selectors, services
from ..models import Budget, BudgetLine
from .serializers import (
    BudgetCreateSerializer,
    BudgetLineCreateSerializer,
    BudgetLineUpdateSerializer,
    BudgetSerializer,
)


class BudgetView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = BudgetSerializer

    def get(self, request):
        budgets = Budget.objects.filter(is_active=True).order_by("name")
        return Response(BudgetSerializer(budgets, many=True).data)

    def post(self, request):
        s = BudgetCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        budget = services.create_budget(
            name=v["name"], currency=v["currency"].upper(), starts_on=v["starts_on"], period=v["period"]
        )
        return Response(BudgetSerializer(budget).data, status=status.HTTP_201_CREATED)


class BudgetLineView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = BudgetLineCreateSerializer

    def post(self, request, budget_id):
        budget = Budget.objects.filter(id=budget_id).first()
        if budget is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = BudgetLineCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        category = Category.objects.filter(id=v["category_id"]).first()
        if category is None:
            return Response({"detail": "category not found"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            line = services.add_budget_line(
                budget=budget, category=category, limit_minor=v["limit_minor"], rollover=v["rollover"]
            )
        except services.BudgetError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(
            {
                "id": line.id,
                "category_id": line.category_id,
                "limit_minor": line.limit_minor,
                "rollover": line.rollover,
            },
            status=status.HTTP_201_CREATED,
        )


class BudgetDetailView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = BudgetSerializer

    def delete(self, request, budget_id):
        budget = Budget.objects.filter(id=budget_id).first()
        if budget is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        services.archive_budget(budget=budget)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BudgetLineDetailView(TenantScopedAPIView, APIView):
    """Edit a line's limit/rollover (PATCH) or remove it (DELETE) — the fast
    in-place editing the budget screen leans on."""

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = BudgetLineUpdateSerializer

    def patch(self, request, budget_id, line_id):
        line = (
            BudgetLine.objects.filter(id=line_id, budget_id=budget_id)
            .select_related("budget", "category")
            .first()
        )
        if line is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = BudgetLineUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            line = services.update_budget_line(line=line, **s.validated_data)
        except services.BudgetError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(
            {
                "id": line.id,
                "category_id": line.category_id,
                "limit_minor": line.limit_minor,
                "rollover": line.rollover,
            }
        )

    def delete(self, request, budget_id, line_id):
        line = BudgetLine.objects.filter(id=line_id, budget_id=budget_id).first()
        if line is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        services.remove_budget_line(line=line)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BudgetStatusView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    def get(self, request, budget_id):
        budget = Budget.objects.filter(id=budget_id).first()
        if budget is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        as_of_raw = request.query_params.get("as_of")
        as_of = date.fromisoformat(as_of_raw) if as_of_raw else timezone.localdate()
        statuses = selectors.budget_status(budget, as_of=as_of)
        period_start, period_end = selectors.period_bounds(
            period=budget.period, starts_on=budget.starts_on, as_of=as_of
        )
        return Response(
            {
                "budget_id": str(budget.id),
                "as_of": as_of.isoformat(),
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "lines": [
                    {
                        "line_id": st.line_id,
                        "category_id": st.category_id,
                        "category_name": st.category_name,
                        "limit_minor": st.limit_minor,
                        "carried_minor": st.carried_minor,
                        "effective_limit_minor": st.effective_limit_minor,
                        "actual_minor": st.actual_minor,
                        "remaining_minor": st.remaining_minor,
                        "percent_used": st.percent_used,
                        "over_budget": st.over_budget,
                    }
                    for st in statuses
                ],
            }
        )


class SmartBudgetView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Propose a budget from history, commitments, income and goals — and
    create it on request.

    GET is a pure read: the proposal is recomputed from live data each time and
    stored nowhere, so looking never commits anyone to anything. POST applies
    the current proposal as a real budget the user then owns and edits.
    """

    permission_classes = [IsTenantMember, require_feature(PlanFeature.SMART_PLANNING)]
    throttle_scope = "write"
    serializer_class = None  # bespoke shapes; see _serialize

    @staticmethod
    def _serialize(proposal) -> dict:
        return {
            "currency": proposal.currency,
            "as_of": proposal.as_of.isoformat(),
            "months_considered": proposal.months_considered,
            "income_minor": proposal.income_minor,
            "income_known": proposal.income_known,
            "debt_minimums_minor": proposal.debt_minimums_minor,
            "savings_target_minor": proposal.savings_target_minor,
            "envelope_minor": proposal.envelope_minor,
            "total_minor": proposal.total_minor,
            "left_over_minor": proposal.left_over_minor,
            "trim_factor": proposal.trim_factor,
            "deficit": proposal.deficit,
            "lines": [
                {
                    "category_id": line.category_id,
                    "category_name": line.category_name,
                    "limit_minor": line.limit_minor,
                    "floor_minor": line.floor_minor,
                    "history_minor": line.history_minor,
                    "observed_months": line.observed_months,
                    "rationale": line.rationale,
                }
                for line in proposal.lines
            ],
        }

    def get(self, request):
        from .. import smart

        try:
            proposal = smart.propose_budget()
        except smart.NothingToProposeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(self._serialize(proposal))

    def post(self, request):
        from .. import smart

        starts_on = None
        raw = request.data.get("starts_on")
        if raw:
            try:
                starts_on = date.fromisoformat(str(raw))
            except ValueError:
                return Response(
                    {"detail": "starts_on must be an ISO date (YYYY-MM-DD)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        try:
            proposal = smart.propose_budget()
        except smart.NothingToProposeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        budget = smart.apply_proposal(proposal, starts_on=starts_on)
        return Response(
            {"budget": BudgetSerializer(budget).data, "proposal": self._serialize(proposal)},
            status=status.HTTP_201_CREATED,
        )
