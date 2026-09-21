from __future__ import annotations

from dataclasses import asdict

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assets.models import Asset
from apps.common.api_base import TenantScopedAPIView, WriteRequiresMemberMixin
from apps.finance.models import Bill, FinancialAccount, RecurringTransaction
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import selectors, services
from ..models import InsurancePolicy
from .serializers import PolicyCreateSerializer, PolicyUpdateSerializer


def _out(view: selectors.PolicyView) -> dict:
    return asdict(view) | {
        "id": view.policy_id,
        "underinsured": view.underinsured,
    }


def _get(policy_id) -> InsurancePolicy | None:
    return InsurancePolicy.objects.filter(id=policy_id).first()


def _view_for(policy_id) -> dict | None:
    view = next((v for v in selectors.policy_views() if v.policy_id == str(policy_id)), None)
    return _out(view) if view else None


def _resolve_links(payload: dict) -> dict:
    """Turn optional UUIDs into model instances, or 400 via the caller."""
    errors: dict[str, str] = {}
    if "covers_asset_id" in payload:
        asset_id = payload.pop("covers_asset_id")
        payload["covers_asset"] = Asset.objects.filter(id=asset_id).first() if asset_id else None
        if asset_id and payload["covers_asset"] is None:
            errors["covers_asset_id"] = "Asset not found."
    if "covers_account_id" in payload:
        account_id = payload.pop("covers_account_id")
        payload["covers_account"] = (
            FinancialAccount.objects.filter(id=account_id).first() if account_id else None
        )
        if account_id and payload["covers_account"] is None:
            errors["covers_account_id"] = "Account not found."
    if "bill_id" in payload:
        bill_id = payload.pop("bill_id")
        payload["bill"] = Bill.objects.filter(id=bill_id).first() if bill_id else None
        if bill_id and payload["bill"] is None:
            errors["bill_id"] = "Bill not found."
    if "recurring_transaction_id" in payload:
        rec_id = payload.pop("recurring_transaction_id")
        payload["recurring_transaction"] = (
            RecurringTransaction.objects.filter(id=rec_id).first() if rec_id else None
        )
        if rec_id and payload["recurring_transaction"] is None:
            errors["recurring_transaction_id"] = "Recurring transaction not found."
    return errors


class PolicyListView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = PolicyCreateSerializer

    @extend_schema(operation_id="insurance_list")
    def get(self, request):
        return Response([_out(v) for v in selectors.policy_views()])

    @extend_schema(operation_id="insurance_create")
    def post(self, request):
        s = PolicyCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        payload = dict(s.validated_data)
        errors = _resolve_links(payload)
        if errors:
            return Response({"detail": errors}, status=status.HTTP_400_BAD_REQUEST)
        try:
            policy = services.create_policy(**payload)
        except services.InsuranceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_view_for(policy.id), status=status.HTTP_201_CREATED)


class PolicyDetailView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = PolicyUpdateSerializer

    @extend_schema(operation_id="insurance_retrieve")
    def get(self, request, policy_id):
        if _get(policy_id) is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(_view_for(policy_id))

    @extend_schema(operation_id="insurance_update")
    def patch(self, request, policy_id):
        policy = _get(policy_id)
        if policy is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = PolicyUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        changes = dict(s.validated_data)
        errors = _resolve_links(changes)
        if errors:
            return Response({"detail": errors}, status=status.HTTP_400_BAD_REQUEST)
        try:
            services.update_policy(policy=policy, **changes)
        except services.InsuranceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_view_for(policy_id))

    @extend_schema(operation_id="insurance_delete")
    def delete(self, request, policy_id):
        policy = _get(policy_id)
        if policy is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        services.delete_policy(policy=policy)
        return Response(status=status.HTTP_204_NO_CONTENT)


class InsuranceSummaryView(TenantScopedAPIView, APIView):
    """Headline figures. 204 when nothing has been recorded."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="insurance_summary")
    def get(self, request):
        result = selectors.summary()
        if result is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(asdict(result))
