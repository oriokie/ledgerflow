from __future__ import annotations

from dataclasses import asdict

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api_base import TenantScopedAPIView, WriteRequiresMemberMixin
from apps.finance.models import FinancialAccount
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import selectors, services
from ..models import Asset, Valuation
from .serializers import AssetCreateSerializer, AssetUpdateSerializer, ValuationCreateSerializer


def _out(view: selectors.AssetView) -> dict:
    return asdict(view) | {
        "id": view.asset_id,
        # Derived, and sent rather than re-derived on the client so the rule
        # for "unanswerable" lives in one place.
        "equity_minor": view.equity_minor,
        "loan_to_value_pct": view.loan_to_value_pct,
        "gain_minor": view.gain_minor,
    }


def _get(asset_id) -> Asset | None:
    return Asset.objects.filter(id=asset_id).first()


def _view_for(asset_id) -> dict | None:
    view = next((v for v in selectors.asset_views() if v.asset_id == str(asset_id)), None)
    return _out(view) if view else None


class AssetListView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Everything owned that is not an account, and where a new one is added."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = AssetCreateSerializer

    @extend_schema(operation_id="assets_list")
    def get(self, request):
        return Response([_out(v) for v in selectors.asset_views()])

    @extend_schema(operation_id="assets_create")
    def post(self, request):
        s = AssetCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = dict(s.validated_data)

        debt = None
        if v.pop("secured_by_debt_id", None):
            debt = FinancialAccount.objects.filter(id=s.validated_data["secured_by_debt_id"]).first()
            if debt is None:
                return Response({"detail": "secured_by_debt not found"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            asset = services.create_asset(secured_by_debt=debt, **v)
        except services.AssetError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_view_for(asset.id), status=status.HTTP_201_CREATED)


class AssetDetailView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = AssetUpdateSerializer

    @extend_schema(operation_id="asset_retrieve")
    def get(self, request, asset_id):
        asset = _get(asset_id)
        if asset is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        out = _view_for(asset_id)
        out["valuations"] = [
            {
                "id": str(p.id),
                "as_of": p.as_of,
                "value_minor": p.value_minor,
                "source": p.source,
                "notes": p.notes,
            }
            for p in asset.valuations.order_by("-as_of")
        ]
        return Response(out)

    @extend_schema(operation_id="asset_update")
    def patch(self, request, asset_id):
        asset = _get(asset_id)
        if asset is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = AssetUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        changes = dict(s.validated_data)
        if "secured_by_debt_id" in changes:
            debt_id = changes.pop("secured_by_debt_id")
            changes["secured_by_debt"] = (
                FinancialAccount.objects.filter(id=debt_id).first() if debt_id else None
            )
        try:
            services.update_asset(asset=asset, **changes)
        except services.AssetError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_view_for(asset_id))

    @extend_schema(operation_id="asset_delete")
    def delete(self, request, asset_id):
        asset = _get(asset_id)
        if asset is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        services.delete_asset(asset=asset)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ValuationView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Record what an asset is judged to be worth."""

    permission_classes = [IsTenantMember]
    serializer_class = ValuationCreateSerializer

    @extend_schema(operation_id="asset_valuation_create")
    def post(self, request, asset_id):
        asset = _get(asset_id)
        if asset is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = ValuationCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            services.record_valuation(asset=asset, **s.validated_data)
        except services.AssetError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_view_for(asset_id), status=status.HTTP_201_CREATED)


class ValuationDetailView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = None

    @extend_schema(operation_id="asset_valuation_delete")
    def delete(self, request, asset_id, valuation_id):
        valuation = Valuation.objects.filter(id=valuation_id, asset_id=asset_id).first()
        if valuation is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        services.delete_valuation(valuation=valuation)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AssetSummaryView(TenantScopedAPIView, APIView):
    """Headline figures. 204 when nothing has been recorded — "you own nothing"
    and "you haven't told us about anything" are different statements."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="assets_summary")
    def get(self, request):
        result = selectors.summary()
        if result is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(asdict(result))
