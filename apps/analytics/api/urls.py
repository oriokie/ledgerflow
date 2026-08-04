from __future__ import annotations

from django.urls import path

from .views import (
    FinancialIndependenceView,
    ReportCatalogView,
    ReportExportView,
    ReportView,
    ScenarioPreviewView,
)

urlpatterns = [
    path("reports/", ReportCatalogView.as_view(), name="report-catalog"),
    path("scenarios/preview/", ScenarioPreviewView.as_view(), name="scenario-preview"),
    path(
        "financial-independence/",
        FinancialIndependenceView.as_view(),
        name="financial-independence",
    ),
    path("reports/<slug:slug>/", ReportView.as_view(), name="report-run"),
    path("reports/<slug:slug>/export/", ReportExportView.as_view(), name="report-export"),
]
