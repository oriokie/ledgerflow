from __future__ import annotations

from django.urls import path

from .views import InsuranceSummaryView, PolicyDetailView, PolicyListView

urlpatterns = [
    path("", PolicyListView.as_view(), name="insurance-list"),
    path("summary/", InsuranceSummaryView.as_view(), name="insurance-summary"),
    path("<uuid:policy_id>/", PolicyDetailView.as_view(), name="insurance-detail"),
]
