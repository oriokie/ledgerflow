from django.urls import path

from .audit_views import WorkspaceAuditView
from .views import (
    AcceptInvitationView,
    WorkspaceAISettingsView,
    WorkspaceDetailView,
    WorkspaceExportView,
    WorkspaceInvitationDetailView,
    WorkspaceInvitationsView,
    WorkspaceListCreateView,
    WorkspaceMemberDetailView,
    WorkspaceMembersView,
)

urlpatterns = [
    path("workspaces/", WorkspaceListCreateView.as_view(), name="workspace-list-create"),
    path(
        "workspaces/activity/",
        WorkspaceAuditView.as_view(),
        name="workspace-activity",
    ),
    path("workspaces/members/", WorkspaceMembersView.as_view(), name="workspace-members"),
    path(
        "workspaces/members/<uuid:membership_id>/",
        WorkspaceMemberDetailView.as_view(),
        name="workspace-member-detail",
    ),
    path("workspaces/invitations/", WorkspaceInvitationsView.as_view(), name="workspace-invitations"),
    path(
        "workspaces/invitations/<uuid:invitation_id>/",
        WorkspaceInvitationDetailView.as_view(),
        name="workspace-invitation-detail",
    ),
    path("workspaces/<uuid:tenant_id>/", WorkspaceDetailView.as_view(), name="workspace-detail"),
    path("workspaces/<uuid:tenant_id>/export/", WorkspaceExportView.as_view(), name="workspace-export"),
    path("workspaces/<uuid:tenant_id>/ai/", WorkspaceAISettingsView.as_view(), name="workspace-ai-settings"),
    path("invitations/accept/", AcceptInvitationView.as_view(), name="invitation-accept"),
]
