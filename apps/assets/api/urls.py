from __future__ import annotations

from django.urls import path

from .views import (
    AssetDetailView,
    AssetListView,
    AssetSummaryView,
    ValuationDetailView,
    ValuationView,
)

urlpatterns = [
    path("", AssetListView.as_view(), name="asset-list"),
    path("summary/", AssetSummaryView.as_view(), name="asset-summary"),
    path("<uuid:asset_id>/", AssetDetailView.as_view(), name="asset-detail"),
    path("<uuid:asset_id>/valuations/", ValuationView.as_view(), name="asset-valuations"),
    path(
        "<uuid:asset_id>/valuations/<uuid:valuation_id>/",
        ValuationDetailView.as_view(),
        name="asset-valuation-detail",
    ),
]
