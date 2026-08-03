from __future__ import annotations

from django.urls import path

from .views import (
    ReceiptConfirmFieldsView,
    ReceiptConfirmUploadView,
    ReceiptDetailView,
    ReceiptDiscardView,
    ReceiptLinkView,
    ReceiptQueueView,
    ReceiptUploadRequestView,
)

urlpatterns = [
    path("upload/", ReceiptUploadRequestView.as_view(), name="receipt-upload-request"),
    path("queue/", ReceiptQueueView.as_view(), name="receipt-queue"),
    path("<uuid:receipt_id>/", ReceiptDetailView.as_view(), name="receipt-detail"),
    path(
        "<uuid:receipt_id>/confirm-upload/",
        ReceiptConfirmUploadView.as_view(),
        name="receipt-confirm-upload",
    ),
    path(
        "<uuid:receipt_id>/fields/",
        ReceiptConfirmFieldsView.as_view(),
        name="receipt-confirm-fields",
    ),
    path("<uuid:receipt_id>/link/", ReceiptLinkView.as_view(), name="receipt-link"),
    path("<uuid:receipt_id>/discard/", ReceiptDiscardView.as_view(), name="receipt-discard"),
]
