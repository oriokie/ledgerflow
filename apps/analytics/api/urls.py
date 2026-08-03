from __future__ import annotations

from django.urls import path

from .views import ReportCatalogView, ReportExportView, ReportView

urlpatterns = [
    path("reports/", ReportCatalogView.as_view(), name="report-catalog"),
    path("reports/<slug:slug>/", ReportView.as_view(), name="report-run"),
    path("reports/<slug:slug>/export/", ReportExportView.as_view(), name="report-export"),
]
