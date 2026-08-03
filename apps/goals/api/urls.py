from __future__ import annotations

from django.urls import path

from .views import (
    GoalAutoContributionView,
    GoalContributionView,
    GoalDetailView,
    GoalForecastListView,
    GoalForecastView,
    GoalRecommendationView,
    GoalView,
)

urlpatterns = [
    path("goals/", GoalView.as_view(), name="goal-list"),
    path("goals/forecast/", GoalForecastListView.as_view(), name="goal-forecast-list"),
    path("goals/recommendations/", GoalRecommendationView.as_view(), name="goal-recommendations"),
    path("goals/<uuid:goal_id>/", GoalDetailView.as_view(), name="goal-detail"),
    path("goals/<uuid:goal_id>/forecast/", GoalForecastView.as_view(), name="goal-forecast"),
    path(
        "goals/<uuid:goal_id>/auto-contribution/",
        GoalAutoContributionView.as_view(),
        name="goal-auto-contribution",
    ),
    path(
        "goals/<uuid:goal_id>/contributions/",
        GoalContributionView.as_view(),
        name="goal-contributions",
    ),
]
