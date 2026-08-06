from __future__ import annotations

from django.urls import path

from .views import (
    AccountSharingView,
    ApprovalRuleView,
    ChangeRequestListView,
    ChangeRequestResolveView,
    ContributionView,
    DependantDetailView,
    DependantListView,
    HouseholdActivityView,
    HouseholdMembersView,
    HouseholdSummaryView,
    SharingBackfillView,
    SpendApprovalDetailView,
    SpendApprovalListView,
)

urlpatterns = [
    path("summary/", HouseholdSummaryView.as_view(), name="household-summary"),
    path("members/", HouseholdMembersView.as_view(), name="household-members"),
    path("dependants/", DependantListView.as_view(), name="dependant-list"),
    path("dependants/<uuid:dependant_id>/", DependantDetailView.as_view(), name="dependant-detail"),
    path("sharing/", AccountSharingView.as_view(), name="account-sharing-list"),
    path("sharing/<uuid:account_id>/", AccountSharingView.as_view(), name="account-sharing-set"),
    path("sharing/backfill/", SharingBackfillView.as_view(), name="sharing-backfill"),
    path("change-requests/", ChangeRequestListView.as_view(), name="change-request-list"),
    path(
        "change-requests/<uuid:request_id>/<slug:action>/",
        ChangeRequestResolveView.as_view(),
        name="change-request-resolve",
    ),
    path("contributions/", ContributionView.as_view(), name="household-contributions"),
    path("activity/", HouseholdActivityView.as_view(), name="household-activity"),
    path("approval-rules/", ApprovalRuleView.as_view(), name="household-approval-rules"),
    path("approvals/", SpendApprovalListView.as_view(), name="household-approvals"),
    path(
        "approvals/<uuid:approval_id>/", SpendApprovalDetailView.as_view(), name="household-approval-detail"
    ),
]
