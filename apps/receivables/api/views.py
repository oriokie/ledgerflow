from __future__ import annotations

from dataclasses import asdict

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api_base import TenantScopedAPIView, WriteRequiresMemberMixin
from apps.finance.models import FinancialAccount, Transaction
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import selectors, services
from ..models import Receivable
from .serializers import (
    ReceivableCreateSerializer,
    ReceivableUpdateSerializer,
    RepaymentCreateSerializer,
)


def _out(view: selectors.ReceivableView) -> dict:
    return asdict(view) | {"id": view.receivable_id}


def _get(receivable_id) -> Receivable | None:
    return Receivable.objects.filter(id=receivable_id).first()


def _view_for(receivable_id) -> dict | None:
    view = next((v for v in selectors.receivable_views() if v.receivable_id == str(receivable_id)), None)
    return _out(view) if view else None


class ReceivableListView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Everything owed to the household, and where a new claim is recorded."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = ReceivableCreateSerializer

    @extend_schema(operation_id="receivables_list")
    def get(self, request):
        include_closed = request.query_params.get("include_closed", "true").lower() != "false"
        return Response([_out(v) for v in selectors.receivable_views(include_closed=include_closed)])

    @extend_schema(operation_id="receivables_create")
    def post(self, request):
        s = ReceivableCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        account = None
        if v.get("source_account_id"):
            account = FinancialAccount.objects.filter(id=v["source_account_id"]).first()
            if account is None:
                return Response({"detail": "source_account not found"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            receivable = services.create_receivable(
                counterparty=v["counterparty"],
                kind=v["kind"],
                description=v.get("description", ""),
                currency=v["currency"],
                principal_minor=v["principal_minor"],
                lent_on=v["lent_on"],
                due_on=v.get("due_on"),
                source_account=account,
                notes=v.get("notes", ""),
                post_to_ledger=v.get("post_to_ledger", True) and account is not None,
            )
        except services.ReceivableError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(_view_for(receivable.id), status=status.HTTP_201_CREATED)


class ReceivableDetailView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = ReceivableUpdateSerializer

    @extend_schema(operation_id="receivable_retrieve")
    def get(self, request, receivable_id):
        receivable = _get(receivable_id)
        if receivable is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        out = _view_for(receivable_id)
        out["repayments"] = [
            {
                "id": str(p.id),
                "received_on": p.received_on,
                "amount_minor": p.amount_minor,
                "memo": p.memo,
            }
            for p in receivable.repayments.order_by("-received_on")
        ]
        return Response(out)

    @extend_schema(operation_id="receivable_update")
    def patch(self, request, receivable_id):
        receivable = _get(receivable_id)
        if receivable is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = ReceivableUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        fields = dict(s.validated_data)
        if "source_account_id" in fields:
            account_id = fields.pop("source_account_id")
            if account_id is None:
                fields["source_account"] = None
            else:
                account = FinancialAccount.objects.filter(id=account_id).first()
                if account is None:
                    return Response({"detail": "source_account not found"}, status=status.HTTP_400_BAD_REQUEST)
                fields["source_account"] = account
        try:
            services.update_receivable(receivable=receivable, **fields)
        except services.ReceivableError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_view_for(receivable_id))

    @extend_schema(operation_id="receivable_delete")
    def delete(self, request, receivable_id):
        receivable = _get(receivable_id)
        if receivable is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        services.delete_receivable(receivable=receivable)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RepaymentView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Record money received against a claim."""

    permission_classes = [IsTenantMember]
    serializer_class = RepaymentCreateSerializer

    @extend_schema(operation_id="receivable_repayment_create")
    def post(self, request, receivable_id):
        receivable = _get(receivable_id)
        if receivable is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = RepaymentCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        txn = None
        if v.get("transaction_id"):
            txn = Transaction.objects.filter(id=v["transaction_id"]).first()
        account = None
        if v.get("deposit_account_id"):
            account = FinancialAccount.objects.filter(id=v["deposit_account_id"]).first()
            if account is None:
                return Response({"detail": "deposit_account not found"}, status=status.HTTP_400_BAD_REQUEST)
        can_post = account is not None or receivable.source_account_id is not None
        try:
            services.record_repayment(
                receivable=receivable,
                amount_minor=v["amount_minor"],
                received_on=v["received_on"],
                transaction_ref=txn,
                deposit_account=account,
                post_to_ledger=v.get("post_to_ledger", True) and txn is None and can_post,
                memo=v.get("memo", ""),
            )
        except services.ReceivableError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_view_for(receivable_id), status=status.HTTP_201_CREATED)


class WriteOffView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Give up on the outstanding balance, without forgetting it happened."""

    permission_classes = [IsTenantMember]
    serializer_class = None

    @extend_schema(operation_id="receivable_write_off")
    def post(self, request, receivable_id):
        receivable = _get(receivable_id)
        if receivable is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            services.write_off(receivable=receivable)
        except services.ReceivableError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_view_for(receivable_id))


class ReceivableSummaryView(TenantScopedAPIView, APIView):
    """Headline figures.

    204 when nothing has ever been recorded: "you are owed nothing" and "you
    haven't told us about anything" are different statements, and only one of
    them is a finding.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="receivables_summary")
    def get(self, request):
        result = selectors.summary()
        if result is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(asdict(result))
