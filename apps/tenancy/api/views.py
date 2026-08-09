from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .. import selectors, services
from ..models import Invitation, InvitationStatus, TenantAISettings
from ..services import InsufficientRoleError, InvalidInvitationError, LastOwnerError, TenancyError
from .serializers import (
    AcceptInvitationSerializer,
    ChangeMemberRoleSerializer,
    CreateInvitationSerializer,
    CreateWorkspaceSerializer,
    InvitationPreviewSerializer,
    InvitationSerializer,
    MemberSerializer,
    WorkspaceAISettingsSerializer,
    WorkspaceMembershipSerializer,
)


def _tenancy_error_response(exc: TenancyError) -> Response:
    code = {
        InsufficientRoleError: status.HTTP_403_FORBIDDEN,
        LastOwnerError: status.HTTP_409_CONFLICT,
        InvalidInvitationError: status.HTTP_400_BAD_REQUEST,
    }.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return Response({"detail": str(exc)}, status=code)


class WorkspaceListCreateView(APIView):
    """Not tenant-scoped: a user's workspace list spans tenants by definition,
    and workspace creation happens before a tenant context can exist."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "write"
    serializer_class = CreateWorkspaceSerializer

    def get(self, request):
        memberships = selectors.memberships_for_user(request.user)
        return Response(WorkspaceMembershipSerializer(memberships, many=True).data)

    def post(self, request):
        serializer = CreateWorkspaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = services.create_workspace(owner=request.user, **serializer.validated_data)
        return Response(
            WorkspaceMembershipSerializer(
                selectors.membership_for(user=request.user, tenant_id=tenant.id)
            ).data,
            status=status.HTTP_201_CREATED,
        )


class _TenantScopedControlPlaneView(APIView):
    """Base for tenancy endpoints that are authorized by membership but are
    NOT `TenantScopedAPIView` — `tenancy` itself isn't RLS-protected (see
    Membership/Invitation docstrings), so binding the RLS GUC would be a
    no-op; resolving the actor's membership here is enough."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "write"

    def _require_membership(self, request):
        tenant_id = request.headers.get("X-Tenant-ID")
        if not tenant_id:
            return None, Response(
                {"detail": "X-Tenant-ID header is required."}, status=status.HTTP_400_BAD_REQUEST
            )
        membership = selectors.membership_for(user=request.user, tenant_id=tenant_id)
        if membership is None:
            return None, Response(
                {"detail": "You are not a member of this workspace."}, status=status.HTTP_403_FORBIDDEN
            )
        return membership, None


class WorkspaceMembersView(_TenantScopedControlPlaneView):
    serializer_class = MemberSerializer

    def get(self, request):
        membership, error = self._require_membership(request)
        if error:
            return error
        members = selectors.members_of(membership.tenant)
        return Response(MemberSerializer(members, many=True).data)


class WorkspaceMemberDetailView(_TenantScopedControlPlaneView):
    serializer_class = ChangeMemberRoleSerializer

    def patch(self, request, membership_id):
        actor_membership, error = self._require_membership(request)
        if error:
            return error
        target = selectors.members_of(actor_membership.tenant)
        target = next((m for m in target if str(m.id) == str(membership_id)), None)
        if target is None:
            return Response({"detail": "Member not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = ChangeMemberRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.change_member_role(
                actor_membership=actor_membership,
                target_membership=target,
                new_role=serializer.validated_data["role"],
            )
        except TenancyError as exc:
            return _tenancy_error_response(exc)
        return Response(MemberSerializer(updated).data)

    def delete(self, request, membership_id):
        actor_membership, error = self._require_membership(request)
        if error:
            return error
        members = selectors.members_of(actor_membership.tenant)
        target = next((m for m in members if str(m.id) == str(membership_id)), None)
        if target is None:
            return Response({"detail": "Member not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            services.remove_member(actor_membership=actor_membership, target_membership=target)
        except TenancyError as exc:
            return _tenancy_error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspaceInvitationsView(_TenantScopedControlPlaneView):
    serializer_class = CreateInvitationSerializer

    def get(self, request):
        membership, error = self._require_membership(request)
        if error:
            return error
        invitations = Invitation.objects.filter(
            tenant=membership.tenant, status=InvitationStatus.PENDING
        ).order_by("-created_at")
        return Response(InvitationSerializer(invitations, many=True).data)

    def post(self, request):
        membership, error = self._require_membership(request)
        if error:
            return error
        serializer = CreateInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            invitation, _raw_token = services.create_invitation(
                tenant=membership.tenant, invited_by_membership=membership, **serializer.validated_data
            )
        except TenancyError as exc:
            return _tenancy_error_response(exc)
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)


class WorkspaceInvitationDetailView(_TenantScopedControlPlaneView):
    serializer_class = None  # DELETE-only; no request body

    def delete(self, request, invitation_id):
        membership, error = self._require_membership(request)
        if error:
            return error
        try:
            invitation = Invitation.objects.get(id=invitation_id, tenant=membership.tenant)
        except Invitation.DoesNotExist:
            return Response({"detail": "Invitation not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            services.revoke_invitation(invitation=invitation, actor_membership=membership)
        except TenancyError as exc:
            return _tenancy_error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvitationPreviewView(APIView):
    """Public. Lets an invitee see what they're being asked to join -- workspace
    name, inviter, role -- before they commit, without accepting anything or
    requiring them to be signed in yet. Mirrors `PasswordResetConfirmView`'s
    posture: a public, token-gated read."""

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def get(self, request, token):
        try:
            invitation = services.get_invitation_preview(raw_token=token)
        except TenancyError as exc:
            return _tenancy_error_response(exc)
        return Response(InvitationPreviewSerializer(invitation).data)


class AcceptInvitationView(APIView):
    """Deliberately NOT tenant-scoped: the whole point is the caller has no
    membership in the target workspace yet."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "write"
    serializer_class = AcceptInvitationSerializer

    def post(self, request):
        serializer = AcceptInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            membership = services.accept_invitation(
                raw_token=serializer.validated_data["token"], user=request.user
            )
        except TenancyError as exc:
            return _tenancy_error_response(exc)
        return Response(WorkspaceMembershipSerializer(membership).data, status=status.HTTP_201_CREATED)


class WorkspaceDetailView(APIView):
    """Owner-facing management of a specific workspace by id:
    GET  ...export/  -> portable JSON of the workspace's data (GDPR)
    DELETE           -> close the workspace (soft; async erasure)."""

    permission_classes = [IsAuthenticated]

    def _owner_membership(self, request, tenant_id):
        from ..models import Role

        membership = selectors.membership_for(user=request.user, tenant_id=tenant_id)
        if membership is None:
            return None, Response({"detail": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)
        if membership.role != Role.OWNER:
            return None, Response(
                {"detail": "Only an owner can manage this workspace."}, status=status.HTTP_403_FORBIDDEN
            )
        return membership, None

    def delete(self, request, tenant_id):
        membership, err = self._owner_membership(request, tenant_id)
        if err:
            return err
        try:
            services.close_workspace(tenant=membership.tenant, actor_membership=membership)
        except TenancyError as exc:
            return _tenancy_error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def patch(self, request, tenant_id):
        membership, err = self._owner_membership(request, tenant_id)
        if err:
            return err
        try:
            tenant = services.update_workspace(
                tenant=membership.tenant,
                actor_membership=membership,
                name=request.data.get("name"),
                base_currency=request.data.get("base_currency"),
                block_overdrafts=request.data.get("block_overdrafts"),
            )
        except TenancyError as exc:
            return _tenancy_error_response(exc)
        return Response(
            {
                "id": str(tenant.id),
                "name": tenant.name,
                "type": tenant.type,
                "base_currency": tenant.base_currency,
                "base_currency_chosen_at": tenant.base_currency_chosen_at,
                "block_overdrafts": tenant.block_overdrafts,
            }
        )


class WorkspaceExportView(WorkspaceDetailView):
    def get(self, request, tenant_id):
        from ..data_export import export_workspace_data

        membership, err = self._owner_membership(request, tenant_id)
        if err:
            return err
        return Response(export_workspace_data(tenant=membership.tenant))


class WorkspaceAISettingsView(APIView):
    """A workspace's own model choice — read and write, owner only.

    `Tenant.ai_enabled` lets an owner decline AI; this lets them substitute it,
    which is the request that follows: a household that would rather run a
    local model than send anything to a vendor, or one that has its own
    provider account and would sooner spend its own quota.

    Owner-gated for the same reason `ai_enabled` is. Choosing where a
    household's finances get sent is decided for everyone in the household, so
    it is not a per-member preference — see apps/tenancy/models.TenantAISettings.
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "write"
    serializer_class = WorkspaceAISettingsSerializer

    def _owner_membership(self, request, tenant_id):
        from ..models import Role

        membership = selectors.membership_for(user=request.user, tenant_id=tenant_id)
        if membership is None:
            return None, Response({"detail": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)
        if membership.role != Role.OWNER:
            return None, Response(
                {"detail": "Only an owner can change where this workspace's data is sent."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return membership, None

    def get(self, request, tenant_id):
        membership, err = self._owner_membership(request, tenant_id)
        if err:
            return err
        row = TenantAISettings.objects.filter(tenant=membership.tenant).first()
        if row is None:
            # Nothing chosen yet is a valid state, not a 404: the workspace
            # inherits the platform's configuration.
            return Response({"provider": "", "model": "", "base_url": "", "api_key_set": False})
        return Response(WorkspaceAISettingsSerializer(row).data)

    def put(self, request, tenant_id):
        membership, err = self._owner_membership(request, tenant_id)
        if err:
            return err
        serializer = WorkspaceAISettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        row, _ = TenantAISettings.objects.get_or_create(tenant=membership.tenant)
        for field in ("provider", "model", "base_url"):
            if field in data:
                setattr(row, field, data[field])
        # Absent means "leave the stored key alone"; empty string means "remove
        # it". Conflating the two would wipe a working key on every save of an
        # unrelated field.
        if "api_key" in data:
            row.set_api_key(data["api_key"])
        row.save()
        return Response(WorkspaceAISettingsSerializer(row).data)
