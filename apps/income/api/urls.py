from __future__ import annotations

from django.urls import path

from .views import (
    DeductionDetailView,
    DeductionView,
    IncomeSourceDetailView,
    IncomeSourceView,
    IncomeSummaryView,
    ReceiptView,
)

urlpatterns = [
    path("sources/", IncomeSourceView.as_view(), name="income-source-list"),
    path("summary/", IncomeSummaryView.as_view(), name="income-summary"),
    path("sources/<uuid:source_id>/", IncomeSourceDetailView.as_view(), name="income-source-detail"),
    path(
        "sources/<uuid:source_id>/deductions/",
        DeductionView.as_view(),
        name="income-deductions",
    ),
    path(
        "sources/<uuid:source_id>/deductions/<uuid:deduction_id>/",
        DeductionDetailView.as_view(),
        name="income-deduction-detail",
    ),
    path("sources/<uuid:source_id>/receipts/", ReceiptView.as_view(), name="income-receipts"),
]
