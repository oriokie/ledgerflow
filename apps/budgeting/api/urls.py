from django.urls import path

from .views import (
    BudgetDetailView,
    BudgetLineDetailView,
    BudgetLineView,
    BudgetStatusView,
    BudgetView,
)

urlpatterns = [
    path("budgets/", BudgetView.as_view(), name="budgets"),
    path("budgets/<uuid:budget_id>/", BudgetDetailView.as_view(), name="budget-detail"),
    path("budgets/<uuid:budget_id>/lines/", BudgetLineView.as_view(), name="budget-lines"),
    path(
        "budgets/<uuid:budget_id>/lines/<uuid:line_id>/",
        BudgetLineDetailView.as_view(),
        name="budget-line-detail",
    ),
    path("budgets/<uuid:budget_id>/status/", BudgetStatusView.as_view(), name="budget-status"),
]
