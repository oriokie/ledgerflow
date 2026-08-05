from __future__ import annotations

from django.urls import path

from .views import (
    ReceivableDetailView,
    ReceivableListView,
    ReceivableSummaryView,
    RepaymentView,
    WriteOffView,
)

urlpatterns = [
    path("", ReceivableListView.as_view(), name="receivable-list"),
    path("summary/", ReceivableSummaryView.as_view(), name="receivable-summary"),
    path("<uuid:receivable_id>/", ReceivableDetailView.as_view(), name="receivable-detail"),
    path("<uuid:receivable_id>/repayments/", RepaymentView.as_view(), name="receivable-repayments"),
    path("<uuid:receivable_id>/write-off/", WriteOffView.as_view(), name="receivable-write-off"),
]
