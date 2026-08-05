from __future__ import annotations

from django.urls import path

from .views import (
    BorrowingCostView,
    ConsolidationSimulationView,
    DebtAnalyticsView,
    DebtDetailView,
    DebtListView,
    DebtStressView,
    DebtSummaryView,
    DebtTermsView,
    ExtraPaymentCurveView,
    OffsetAccountsView,
    PayoffExportView,
    PayoffPdfView,
    PayoffPlanView,
    RateHistoryView,
    RefinanceSimulationView,
    ScenarioComparisonView,
    TrackedLiabilitiesView,
)

urlpatterns = [
    path("debts/", DebtListView.as_view(), name="debt-list"),
    path("debts/summary/", DebtSummaryView.as_view(), name="debt-summary"),
    path("debts/tracked/", TrackedLiabilitiesView.as_view(), name="debt-tracked"),
    path("debts/payoff/", PayoffPlanView.as_view(), name="debt-payoff"),
    path("debts/extra-payment-curve/", ExtraPaymentCurveView.as_view(), name="debt-curve"),
    path("debts/stress/", DebtStressView.as_view(), name="debt-stress"),
    path("debts/analytics/", DebtAnalyticsView.as_view(), name="debt-analytics"),
    path("debts/payoff/export/", PayoffExportView.as_view(), name="debt-payoff-export"),
    path("debts/payoff/export.pdf", PayoffPdfView.as_view(), name="debt-payoff-pdf"),
    path("debts/borrowing-cost/", BorrowingCostView.as_view(), name="debt-borrowing-cost"),
    path("debts/scenarios/", ScenarioComparisonView.as_view(), name="debt-scenarios"),
    path("debts/consolidate/", ConsolidationSimulationView.as_view(), name="debt-consolidate"),
    path("debts/<uuid:account_id>/", DebtDetailView.as_view(), name="debt-detail"),
    path("debts/<uuid:account_id>/rates/", RateHistoryView.as_view(), name="debt-rates"),
    path("debts/<uuid:account_id>/offsets/", OffsetAccountsView.as_view(), name="debt-offsets"),
    path("debts/<uuid:account_id>/refinance/", RefinanceSimulationView.as_view(), name="debt-refinance"),
    path("debts/<uuid:account_id>/terms/", DebtTermsView.as_view(), name="debt-terms"),
]
