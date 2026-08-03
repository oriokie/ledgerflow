from __future__ import annotations

import base64

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api_base import TenantScopedAPIView, WriteRequiresMemberMixin
from apps.finance.models import Category, FinancialAccount
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import services
from ..models import Receipt
from .serializers import (
    ConfirmFieldsSerializer,
    ConfirmUploadSerializer,
    LinkReceiptSerializer,
    RequestUploadSerializer,
)


def _receipt_out(r: Receipt) -> dict:
    return {
        "id": r.id,
        "status": r.status,
        "content_type": r.content_type,
        "byte_size": r.byte_size,
        "raw_text": r.raw_text,
        "parsed_fields": r.parsed_fields,
        # The provider's own estimate — the UI should visibly hedge a
        # low-confidence guess rather than present it as fact.
        "confidence": r.confidence,
        "provider": r.provider,
        "error": r.error,
        "confirmed_merchant": r.confirmed_merchant,
        "confirmed_amount_minor": r.confirmed_amount_minor,
        "confirmed_occurred_on": r.confirmed_occurred_on,
        "confirmed_category_id": r.confirmed_category_id,
        "linked_transaction_id": r.linked_transaction_id,
        "financial_account_id": r.financial_account_id,
        "download_url": services.download_url(r),
        "created_at": r.created_at,
    }


class ReceiptUploadRequestView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Step one of the two-step upload: get a presigned URL to PUT to."""

    permission_classes = [IsTenantMember]
    serializer_class = RequestUploadSerializer

    def post(self, request):
        s = RequestUploadSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        account = None
        if v.get("financial_account_id"):
            account = FinancialAccount.objects.filter(id=v["financial_account_id"]).first()
        try:
            receipt, upload_url = services.request_receipt_upload(
                filename=v["filename"],
                content_type=v["content_type"],
                byte_size=v["byte_size"],
                financial_account=account,
            )
        except services.ReceiptError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(
            {**_receipt_out(receipt), "upload_url": upload_url}, status=status.HTTP_201_CREATED
        )


class ReceiptConfirmUploadView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Step two: confirm the PUT succeeded, which queues OCR."""

    permission_classes = [IsTenantMember]
    serializer_class = ConfirmUploadSerializer

    def post(self, request, receipt_id):
        receipt = Receipt.objects.filter(id=receipt_id).first()
        if receipt is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = ConfirmUploadSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        image_b64 = s.validated_data.get("image_base64")
        image_bytes = base64.b64decode(image_b64) if image_b64 else None
        try:
            receipt = services.confirm_receipt_upload(receipt=receipt, image_bytes=image_bytes)
        except services.ReceiptError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_receipt_out(receipt))


class ReceiptDetailView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    def get(self, request, receipt_id):
        receipt = Receipt.objects.filter(id=receipt_id).first()
        if receipt is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(_receipt_out(receipt))


class ReceiptQueueView(TenantScopedAPIView, APIView):
    """Receipts waiting for a person to confirm their fields."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="receipts_queue")
    def get(self, request):
        return Response([_receipt_out(r) for r in services.pending_review(limit=50)])


class ReceiptConfirmFieldsView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = ConfirmFieldsSerializer

    def patch(self, request, receipt_id):
        receipt = Receipt.objects.filter(id=receipt_id).first()
        if receipt is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = ConfirmFieldsSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        category = None
        if v.get("category_id"):
            category = Category.objects.filter(id=v["category_id"]).first()
        try:
            receipt = services.update_confirmed_fields(
                receipt=receipt,
                merchant=v.get("merchant"),
                amount_minor=v.get("amount_minor"),
                occurred_on=v.get("occurred_on"),
                category=category,
            )
        except services.ReceiptError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_receipt_out(receipt))


class ReceiptLinkView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Turn a receipt into a real expense transaction, from confirmed fields
    only."""

    permission_classes = [IsTenantMember]
    serializer_class = LinkReceiptSerializer

    def post(self, request, receipt_id):
        receipt = Receipt.objects.filter(id=receipt_id).first()
        if receipt is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = LinkReceiptSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        account = FinancialAccount.objects.filter(id=v["financial_account_id"]).first()
        category = Category.objects.filter(id=v["category_id"]).first()
        if account is None or category is None:
            return Response({"detail": "Account or category not found."}, status=404)

        try:
            txn = services.link_to_transaction(
                receipt=receipt, financial_account=account, category=category
            )
        except services.ReceiptError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response({"transaction_id": txn.id, "receipt": _receipt_out(receipt)})


class ReceiptDiscardView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = None

    def post(self, request, receipt_id):
        receipt = Receipt.objects.filter(id=receipt_id).first()
        if receipt is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            receipt = services.discard(receipt=receipt)
        except services.ReceiptError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_receipt_out(receipt))
