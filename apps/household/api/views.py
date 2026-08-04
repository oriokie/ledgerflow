"""The household API.

Two rules run through every endpoint here, and they are the reason this app
exists rather than the features being bolted onto tenancy:

**Only an owner changes an account's sharing policy.** Not an admin, not the
workspace owner. Role seniority governs the *workspace*; it does not give
anyone the right to expose somebody else's account, and a household where the
person who set up billing can un-private their partner's savings is not one
either of them should trust. The one exception is an account with no owner,
which anybody may claim — that is how the backfilled rows get adopted.

**Aggregates and breakdowns come from different endpoints.** `summary` returns
the household total; `members` returns what the caller may itemise. Keeping
them apart at the URL level means a client cannot accidentally render one with
the other's data.
"""

from __future__ import annotations

from dataclasses import asdict

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api_base import TenantScopedAPIView
from apps.finance.models import FinancialAccount
from apps.tenancy.models import Membership, Role
from apps.tenancy.permissions import IsTenantMember

from .. import analytics, change_requests, visibility
from ..models import AccountSharing, Dependant, HouseholdProfile
from .serializers import (
    AccountSharingSerializer,
    ChangeRequestSerializer,
    DependantSerializer,
    HouseholdProfileSerializer,
)


def _dependant_out(d: Dependant) -> dict:
    return {
        "id": str(d.id),
        "name": d.name,
        "relationship": d.relationship,
        "birth_year": d.birth_year,
        "monthly_cost_minor": d.monthly_cost_minor,
        "support_until_year": d.support_until_year,
        "notes": d.notes,
    }


def _sharing_out(s: AccountSharing) -> dict:
    return {
        "financial_account_id": str(s.financial_account_id),
        "policy": s.policy,
        "is_joint": s.is_joint,
        "owner_membership_id": str(s.owner_id) if s.owner_id else None,
        "visible_to_household": s.visible_to_household,
        "writable_by_household": s.writable_by_household,
    }


class HouseholdSummaryView(TenantScopedAPIView, APIView):
    """The combined position — totals that may include what you cannot itemise."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="household_summary")
    def get(self, request):
        position = analytics.combined_position()
        split = analytics.expense_split()
        cover = analytics.coverage()
        return Response(
            {
                "position": {
                    **{k: v for k, v in asdict(position).items() if k != "members"},
                    "members": [asdict(m) for m in position.members],
                },
                "expense_split": asdict(split),
                "coverage": asdict(cover),
            }
        )


class HouseholdMembersView(TenantScopedAPIView, APIView):
    """Who is in the household, and how each relates to it."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = HouseholdProfileSerializer

    @extend_schema(operation_id="household_members")
    def get(self, request):
        position = analytics.combined_position()
        return Response({"results": [asdict(m) for m in position.members]})

    @extend_schema(operation_id="household_profile_update")
    def patch(self, request):
        """Update *your own* household profile.

        Deliberately has no membership id in the path. Editing a partner's
        stated relationship or their agreed share is not an administrative
        action, it is a claim about them, and it should come from them.
        """
        membership = visibility.current_membership()
        if membership is None:
            return Response(
                {"detail": "No membership resolved for the current user."},
                status=status.HTTP_403_FORBIDDEN,
            )
        s = HouseholdProfileSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        profile, _created = HouseholdProfile.objects.get_or_create(membership=membership)
        for field, value in s.validated_data.items():
            setattr(profile, field, value)
        profile.save()
        return Response(
            {
                "membership_id": str(membership.id),
                "display_name": profile.display_name,
                "relationship": profile.relationship,
                "contribution_share": (
                    str(profile.contribution_share) if profile.contribution_share is not None else None
                ),
            }
        )


class DependantListView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = DependantSerializer

    @extend_schema(operation_id="dependant_list")
    def get(self, request):
        return Response({"results": [_dependant_out(d) for d in Dependant.objects.all()]})

    @extend_schema(operation_id="dependant_create")
    def post(self, request):
        s = DependantSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        dependant = Dependant.objects.create(**s.validated_data)
        return Response(_dependant_out(dependant), status=status.HTTP_201_CREATED)


class DependantDetailView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = DependantSerializer

    @extend_schema(operation_id="dependant_update")
    def patch(self, request, dependant_id):
        dependant = get_object_or_404(Dependant, id=dependant_id)
        s = DependantSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        for field, value in s.validated_data.items():
            setattr(dependant, field, value)
        dependant.save()
        return Response(_dependant_out(dependant))

    @extend_schema(operation_id="dependant_delete")
    def delete(self, request, dependant_id):
        get_object_or_404(Dependant, id=dependant_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AccountSharingView(TenantScopedAPIView, APIView):
    """Read and set an account's sharing policy.

    The GET lists only accounts the caller may see — an unshared account should
    not become discoverable through the very endpoint that governs sharing.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = AccountSharingSerializer

    @extend_schema(operation_id="account_sharing_list")
    def get(self, request):
        allowed = visibility.visible_account_ids()
        rows = AccountSharing.objects.all()
        if allowed is not None:
            rows = rows.filter(financial_account_id__in=allowed)
        return Response({"results": [_sharing_out(s) for s in rows]})

    @extend_schema(operation_id="account_sharing_set")
    def put(self, request, account_id):
        account = get_object_or_404(
            visibility.restrict_accounts(FinancialAccount.objects.all()), id=account_id
        )
        s = AccountSharingSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        sharing, _created = AccountSharing.objects.get_or_create(financial_account=account)
        membership = visibility.current_membership()

        # Only the owner may change a policy. Role seniority governs the
        # workspace; it does not confer the right to expose somebody else's
        # account. An unowned account may be claimed by anyone — that is how
        # backfilled rows get adopted.
        if sharing.owner_id is not None and membership is not None and sharing.owner_id != membership.id:
            return Response(
                {
                    "detail": "Only the account's owner can change how it is shared, "
                    "whatever your role in the workspace."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        data = s.validated_data
        sharing.policy = data["policy"]
        sharing.is_joint = data.get("is_joint", False)
        if "owner_membership_id" in data:
            owner_id = data["owner_membership_id"]
            sharing.owner = get_object_or_404(Membership, id=owner_id) if owner_id else None
        elif sharing.owner_id is None and membership is not None and not sharing.is_joint:
            # Claiming an unowned, non-joint account makes you its owner.
            sharing.owner = membership
        sharing.save()
        return Response(_sharing_out(sharing))


class SharingBackfillView(TenantScopedAPIView, APIView):
    """Give every account an explicit sharing row.

    Run when a second person joins, which is the moment the distinction starts
    to matter. Not a migration: at migration time nobody knows who owns what,
    and guessing would assign somebody's account to their partner.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.ADMIN
    serializer_class = None

    @extend_schema(operation_id="household_sharing_backfill")
    def post(self, request):
        created = visibility.ensure_sharing_rows()
        return Response(
            {
                "created": created,
                "detail": (
                    f"{created} account(s) now have an explicit sharing setting. "
                    "None were assigned an owner — that is for each member to claim."
                ),
            }
        )


def _change_request_out(request_obj) -> dict:
    return {
        "id": str(request_obj.id),
        "financial_account_id": str(request_obj.account_sharing.financial_account_id),
        "summary": request_obj.summary,
        "payload": request_obj.payload,
        "status": request_obj.status,
        "requested_by_id": str(request_obj.requested_by_id),
        "resolved_by_id": str(request_obj.resolved_by_id) if request_obj.resolved_by_id else None,
        "resolved_at": request_obj.resolved_at,
        "created_at": request_obj.created_at,
    }


class ChangeRequestListView(TenantScopedAPIView, APIView):
    """The approval queue: what you have been asked, and what you have asked for.

    Scoped to the owner and the requester only. A workspace's approval queue is
    not a noticeboard — a third member seeing that one partner asked another to
    un-hide an account learns something that is not theirs.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = ChangeRequestSerializer

    @extend_schema(operation_id="change_request_list")
    def get(self, request):
        queryset = change_requests.visible_to_me()
        wanted = request.query_params.get("status")
        if wanted:
            queryset = queryset.filter(status=wanted)
        return Response({"results": [_change_request_out(r) for r in queryset]})

    @extend_schema(operation_id="change_request_create")
    def post(self, request):
        s = ChangeRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        # The account has to be one the caller can see before they can ask
        # anything about it — otherwise the endpoint confirms that a private
        # account exists, which is the leak the whole phase exists to prevent.
        get_object_or_404(
            visibility.restrict_accounts(FinancialAccount.objects.all()),
            id=data["financial_account_id"],
        )
        try:
            created = change_requests.submit(
                account_id=data["financial_account_id"],
                payload=data["payload"],
                summary=data.get("summary", ""),
            )
        except change_requests.ChangeRequestError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_change_request_out(created), status=status.HTTP_201_CREATED)


class ChangeRequestResolveView(TenantScopedAPIView, APIView):
    """Approve or decline. The owner's alone, whatever anyone's role is."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    def _load(self, request_id):
        return get_object_or_404(change_requests.visible_to_me(), id=request_id)

    @extend_schema(operation_id="change_request_approve")
    def post(self, request, request_id, action):
        change_request = self._load(request_id)
        try:
            if action == "approve":
                applied = change_requests.approve(change_request)
                return Response({**_change_request_out(applied.request), "applied": applied.changes})
            if action == "decline":
                return Response(_change_request_out(change_requests.decline(change_request)))
        except change_requests.ChangeRequestError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response({"detail": f"Unknown action {action!r}."}, status=status.HTTP_404_NOT_FOUND)
