from __future__ import annotations

from django.urls import path

from .advisor_views import (
    DecisionCatalogueView,
    DecisionExportPdfView,
    DecisionExportXlsxView,
    DecisionShareCreateView,
    DecisionView,
    GuestCatalogueView,
    GuestDecisionView,
    GuestKenyaRatesView,
    KenyaRatesView,
    RiskView,
    SensitivityView,
    SharedDecisionPdfView,
    SharedDecisionView,
    SharedDecisionXlsxView,
    SimulationView,
    WhatIfView,
)
from .views import (
    AssumptionSetView,
    BaselineProjectionView,
    CalculatorView,
    EventCatalogueView,
    PlanningProfileView,
    ScenarioArchiveView,
    ScenarioCompareView,
    ScenarioDetailView,
    ScenarioDuplicateView,
    ScenarioEventDetailView,
    ScenarioEventsView,
    ScenarioListView,
    ScenarioRunView,
)

urlpatterns = [
    # Static segments first: `scenarios/compare/` must not be captured by the
    # `<uuid:scenario_id>` pattern.
    path("baseline/", BaselineProjectionView.as_view(), name="projection-baseline"),
    path("assumptions/", AssumptionSetView.as_view(), name="projection-assumptions"),
    path("planning-profile/", PlanningProfileView.as_view(), name="projection-planning-profile"),
    path("event-catalogue/", EventCatalogueView.as_view(), name="projection-event-catalogue"),
    path("calculators/<slug:slug>/", CalculatorView.as_view(), name="projection-calculator"),
    # --- Phase 2: decision support -------------------------------------
    path("simulate/", SimulationView.as_view(), name="projection-simulate"),
    path("sensitivity/", SensitivityView.as_view(), name="projection-sensitivity"),
    path("what-if/", WhatIfView.as_view(), name="projection-what-if"),
    path("risk/", RiskView.as_view(), name="projection-risk"),
    path("kenya-rates/", KenyaRatesView.as_view(), name="projection-kenya-rates"),
    path("guest/questions/", GuestCatalogueView.as_view(), name="guest-decision-catalogue"),
    path("guest/kenya-rates/", GuestKenyaRatesView.as_view(), name="guest-kenya-rates"),
    path("guest/questions/<slug:slug>/", GuestDecisionView.as_view(), name="guest-decision-ask"),
    path("questions/", DecisionCatalogueView.as_view(), name="decision-catalogue"),
    path("questions/<slug:slug>/export.pdf", DecisionExportPdfView.as_view(), name="decision-export-pdf"),
    path(
        "questions/<slug:slug>/export.xlsx",
        DecisionExportXlsxView.as_view(),
        name="decision-export-xlsx",
    ),
    path("questions/<slug:slug>/share/", DecisionShareCreateView.as_view(), name="decision-share-create"),
    path("questions/<slug:slug>/", DecisionView.as_view(), name="decision-ask"),
    path("shared/<str:token>/export.pdf", SharedDecisionPdfView.as_view(), name="decision-share-pdf"),
    path("shared/<str:token>/export.xlsx", SharedDecisionXlsxView.as_view(), name="decision-share-xlsx"),
    path("shared/<str:token>/", SharedDecisionView.as_view(), name="decision-share"),
    path("scenarios/", ScenarioListView.as_view(), name="scenario-list"),
    path("scenarios/compare/", ScenarioCompareView.as_view(), name="scenario-compare"),
    path("scenarios/<uuid:scenario_id>/", ScenarioDetailView.as_view(), name="scenario-detail"),
    path("scenarios/<uuid:scenario_id>/run/", ScenarioRunView.as_view(), name="scenario-run"),
    path(
        "scenarios/<uuid:scenario_id>/duplicate/",
        ScenarioDuplicateView.as_view(),
        name="scenario-duplicate",
    ),
    path(
        "scenarios/<uuid:scenario_id>/archive/",
        ScenarioArchiveView.as_view(),
        name="scenario-archive",
    ),
    path(
        "scenarios/<uuid:scenario_id>/events/",
        ScenarioEventsView.as_view(),
        name="scenario-event-create",
    ),
    path(
        "scenarios/<uuid:scenario_id>/events/<uuid:event_id>/",
        ScenarioEventDetailView.as_view(),
        name="scenario-event-detail",
    ),
]
