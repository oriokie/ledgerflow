from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api_base import TenantScopedAPIView, WriteRequiresMemberMixin
from apps.finance.models import FinancialAccount, Transaction
from apps.tenancy.permissions import IsTenantMember

from .. import selectors, services
from ..models import IncomeDeduction, IncomeReceipt, IncomeSource
from .serializers import (
    DeductionCreateSerializer,
    IncomeSourceCreateSerializer,
    IncomeSourceUpdateSerializer,
    ReceiptCreateSerializer,
)


def _source_out(view: selectors.SourceView) -> dict:
    """One source as the client sees it.

    ``expected_is_observed`` and ``is_speculative`` are part of the payload
    rather than something the client re-derives: how certain a figure is has to
    travel with the figure, or a screen somewhere will eventually render a
    guess as a fact.
    """
    return {
        "id": view.source_id,
        "name": view.name,
        "kind": view.kind,
        "payer": view.payer,
        "currency": view.currency,
        "frequency": view.frequency,
        "reliability": view.reliability,
        "is_active": view.is_active,
        "stated_net_minor": view.stated_net_minor,
        "stated_gross_minor": view.stated_gross_minor,
        "observed_mean_minor": view.observed_mean_minor,
        "observed_stdev_minor": view.observed_stdev_minor,
        "receipt_count": view.receipt_count,
        "last_received_on": view.last_received_on,
        "expected_net_minor": view.expected_net_minor,
        "expected_is_observed": view.expected_is_observed,
        "monthly_net_minor": view.monthly_net_minor,
        "deductions_minor": view.deductions_minor,
        "variance_pct": view.variance_pct,
        "is_speculative": view.is_speculative,
    }


class IncomeSourceView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = IncomeSourceCreateSerializer

    def get(self, request):
        currency = request.query_params.get("currency") or None
        return Response([_source_out(v) for v in selectors.source_views(currency=currency)])

    def post(self, request):
        s = IncomeSourceCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        account = None
        if v.get("deposit_account_id"):
            account = FinancialAccount.objects.filter(id=v["deposit_account_id"]).first()
            if account is None:
                return Response(
                    {"detail": "deposit_account not found"}, status=status.HTTP_400_BAD_REQUEST
                )
        try:
            source = services.create_source(
                name=v["name"],
                kind=v["kind"],
                payer=v.get("payer", ""),
                currency=v["currency"],
                net_minor=v["net_minor"],
                gross_minor=v.get("gross_minor"),
                reliability=v.get("reliability"),
                frequency=v["frequency"],
                pay_day=v.get("pay_day"),
                second_pay_day=v.get("second_pay_day"),
                starts_on=v["starts_on"],
                ends_on=v.get("ends_on"),
                deposit_account=account,
                notes=v.get("notes", ""),
            )
        except services.IncomeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        view = next(v for v in selectors.source_views() if v.source_id == str(source.id))
        return Response(_source_out(view), status=status.HTTP_201_CREATED)


class IncomeSourceDetailView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = None

    @extend_schema(operation_id="income_source_retrieve")
    def get(self, request, source_id):
        view = next(
            (v for v in selectors.source_views() if v.source_id == str(source_id)),
            None,
        )
        if view is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        out = _source_out(view)
        out["deductions"] = [
            {
                "id": str(d.id),
                "kind": d.kind,
                "label": d.label,
                "amount_minor": d.amount_minor,
                "percent_bp": d.percent_bp,
            }
            for d in IncomeDeduction.objects.filter(source_id=source_id)
        ]
        out["receipts"] = [
            {
                "id": str(r.id),
                "occurred_on": r.occurred_on,
                "net_minor": r.net_minor,
                "gross_minor": r.gross_minor,
                "memo": r.memo,
            }
            for r in IncomeReceipt.objects.filter(source_id=source_id).order_by("-occurred_on")[:24]
        ]
        return Response(out)

    @extend_schema(request=IncomeSourceUpdateSerializer)
    def patch(self, request, source_id):
        source = IncomeSource.objects.filter(id=source_id).first()
        if source is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = IncomeSourceUpdateSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        try:
            source = services.update_source(source=source, **s.validated_data)
        except services.IncomeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        view = next(v for v in selectors.source_views() if v.source_id == str(source.id))
        return Response(_source_out(view))

    def delete(self, request, source_id):
        """Soft delete. A source that ended is history worth keeping — it is
        the evidence behind every past figure this module produced."""
        source = IncomeSource.objects.filter(id=source_id).first()
        if source is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        source.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeductionView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = DeductionCreateSerializer

    def post(self, request, source_id):
        source = IncomeSource.objects.filter(id=source_id).first()
        if source is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = DeductionCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            deduction = services.add_deduction(
                source=source,
                kind=v["kind"],
                label=v.get("label", ""),
                amount_minor=v.get("amount_minor"),
                percent_bp=v.get("percent_bp"),
            )
        except services.IncomeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(
            {
                "id": str(deduction.id),
                "kind": deduction.kind,
                "label": deduction.label,
                "amount_minor": deduction.amount_minor,
                "percent_bp": deduction.percent_bp,
            },
            status=status.HTTP_201_CREATED,
        )


class DeductionDetailView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = None

    def delete(self, request, source_id, deduction_id):
        deduction = IncomeDeduction.objects.filter(id=deduction_id, source_id=source_id).first()
        if deduction is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        deduction.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReceiptView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = ReceiptCreateSerializer

    def post(self, request, source_id):
        source = IncomeSource.objects.filter(id=source_id).first()
        if source is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = ReceiptCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        txn = None
        if v.get("transaction_id"):
            txn = Transaction.objects.filter(id=v["transaction_id"]).first()
            if txn is None:
                return Response({"detail": "transaction not found"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            receipt = services.record_receipt(
                source=source,
                occurred_on=v["occurred_on"],
                net_minor=v["net_minor"],
                gross_minor=v.get("gross_minor"),
                transaction_ref=txn,
                memo=v.get("memo", ""),
            )
        except services.IncomeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(
            {
                "id": str(receipt.id),
                "occurred_on": receipt.occurred_on,
                "net_minor": receipt.net_minor,
                "gross_minor": receipt.gross_minor,
                "memo": receipt.memo,
            },
            status=status.HTTP_201_CREATED,
        )


class IncomeSummaryView(TenantScopedAPIView, APIView):
    """The household's income position and how much of it is already spoken for.

    Returns 204 rather than a zeroed payload when nothing is recorded. A body
    full of zeros is a claim that the household earns nothing; the absence of
    one is the truth, which is that they have not told us yet.
    """

    permission_classes = [IsTenantMember]
    serializer_class = None

    def get(self, request):
        currency = request.query_params.get("currency") or None
        summary = selectors.income_summary(currency=currency)
        if summary is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        committed = selectors.committed_income(currency=summary.currency)
        return Response(
            {
                "currency": summary.currency,
                "monthly_net_minor": summary.monthly_net_minor,
                "monthly_gross_minor": summary.monthly_gross_minor,
                "monthly_fixed_minor": summary.monthly_fixed_minor,
                "monthly_variable_minor": summary.monthly_variable_minor,
                "monthly_deductions_minor": summary.monthly_deductions_minor,
                "take_home_rate": summary.take_home_rate,
                "concentration_pct": summary.concentration_pct,
                "source_count": summary.source_count,
                "ad_hoc_count": summary.ad_hoc_count,
                "speculative_count": summary.speculative_count,
                "committed": None
                if committed is None
                else {
                    "committed_minor": committed.committed_minor,
                    "free_minor": committed.free_minor,
                    "committed_pct": committed.committed_pct,
                    "committed_against_fixed_pct": committed.committed_against_fixed_pct,
                    "bills_minor": committed.bills_minor,
                    "debt_minimums_minor": committed.debt_minimums_minor,
                    "recurring_expenses_minor": committed.recurring_expenses_minor,
                },
            }
        )
