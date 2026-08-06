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


class ContributionView(TenantScopedAPIView, APIView):
    """How the household divides its shared costs, and how that is going.

    GET returns the plan, the fairness comparison and the derived figures in
    one response, because they are meaningless apart: a plan without actuals is
    an aspiration, and actuals without a plan are a list of transfers.

    PUT re-agrees the split. MEMBER, not admin — deciding how two people divide
    their own costs is not a permission the person who set up billing should
    hold over the other.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = None

    @extend_schema(operation_id="household_contributions")
    def get(self, request):
        from .. import contributions

        overview = contributions.overview()
        plan = overview.plan
        fairness = overview.fairness
        return Response(
            {
                "agreement_id": overview.agreement_id,
                "review_on": overview.review_on,
                "plan": {
                    "mode": str(plan.mode),
                    "currency": plan.currency,
                    "target_minor": plan.target_minor,
                    "is_complete": plan.is_complete,
                    "shortfall_minor": plan.shortfall_minor,
                    "blockers": list(plan.blockers),
                    "notes": list(plan.notes),
                    "contributions": [
                        {
                            "membership_id": c.membership_id,
                            "display_name": c.display_name,
                            "amount_minor": c.amount_minor,
                            "share_of_total": c.share_of_total,
                            "basis": c.basis,
                        }
                        for c in plan.contributions
                    ],
                },
                "fairness": {
                    "is_balanced": fairness.is_balanced,
                    "summary": fairness.summary,
                    "worst_gap_minor": fairness.worst_gap_minor,
                    "lines": [
                        {
                            "membership_id": line.membership_id,
                            "display_name": line.display_name,
                            "expected_minor": line.expected_minor,
                            "actual_minor": line.actual_minor,
                            "delta_minor": line.delta_minor,
                        }
                        for line in fairness.lines
                    ],
                },
                "derived_target_minor": overview.derived_target_minor,
                "unattributed_income_minor": overview.unattributed_income_minor,
            }
        )

    @extend_schema(operation_id="household_set_contributions")
    def put(self, request):
        from decimal import Decimal, InvalidOperation

        from .. import contributions

        terms: dict[str, dict] = {}
        for membership_id, values in (request.data.get("terms") or {}).items():
            entry: dict = {}
            if values.get("share") not in (None, ""):
                try:
                    entry["share"] = Decimal(str(values["share"]))
                except (InvalidOperation, TypeError):
                    return Response(
                        {"detail": f"{values['share']!r} is not a valid share."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            if values.get("fixed_minor") not in (None, ""):
                entry["fixed_minor"] = int(values["fixed_minor"])
            terms[str(membership_id)] = entry

        try:
            agreement = contributions.set_agreement(
                mode=request.data.get("mode", ""),
                currency=request.data.get("currency") or "KES",
                target_minor=request.data.get("target_minor"),
                review_on=request.data.get("review_on") or None,
                notes=request.data.get("notes", ""),
                terms=terms,
            )
        except contributions.ContributionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"agreement_id": str(agreement.id)}, status=status.HTTP_200_OK)


class HouseholdActivityView(TenantScopedAPIView, APIView):
    """The household's activity log.

    VIEWER, deliberately the lowest role that can read anything: an audit trail
    only one party can consult is not a trust mechanism. Private events appear
    with their summaries written to omit the specifics — see `audit.timeline`.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="household_activity")
    def get(self, request):
        from .. import audit

        try:
            limit = min(int(request.query_params.get("limit", 100)), 500)
        except (TypeError, ValueError):
            limit = 100

        events = audit.timeline(limit=limit, subject_type=request.query_params.get("subject_type"))
        return Response(
            [
                {
                    "id": str(e.id),
                    "occurred_at": e.created_at,
                    "actor": e.actor_label,
                    "action": e.action,
                    "subject_type": e.subject_type,
                    "subject_id": str(e.subject_id) if e.subject_id else None,
                    "summary": e.summary,
                    "is_private": e.is_private,
                    "detail": e.detail,
                }
                for e in events
            ]
        )


class ApprovalRuleView(TenantScopedAPIView, APIView):
    """The household's spending thresholds.

    MEMBER, not admin: agreeing "let's check with each other over 20,000" is a
    pact between partners, not a permission one holds over the other.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = None

    @extend_schema(operation_id="household_approval_rules")
    def get(self, request):
        from ..models import ApprovalRule

        return Response(
            [
                {
                    "id": str(r.id),
                    "name": str(r),
                    "scope": r.scope,
                    "currency": r.currency,
                    "min_amount_minor": r.min_amount_minor,
                    "expires_after_hours": r.expires_after_hours,
                    "is_active": r.is_active,
                }
                for r in ApprovalRule.objects.filter(is_active=True)
            ]
        )

    @extend_schema(operation_id="household_create_approval_rule")
    def post(self, request):
        from ..models import ApprovalRule, ApprovalScope

        try:
            threshold = int(request.data.get("min_amount_minor", 0))
        except (TypeError, ValueError):
            return Response({"detail": "min_amount_minor must be a number."}, status=400)
        if threshold <= 0:
            return Response({"detail": "A threshold has to be above zero."}, status=400)

        rule = ApprovalRule.objects.create(
            name=request.data.get("name", ""),
            scope=request.data.get("scope") or ApprovalScope.JOINT,
            financial_account_id=request.data.get("financial_account_id") or None,
            currency=(request.data.get("currency") or "KES")[:3].upper(),
            min_amount_minor=threshold,
            expires_after_hours=int(request.data.get("expires_after_hours") or 48),
        )
        from .. import audit
        from ..models import AuditAction

        audit.record(
            action=AuditAction.CREATED,
            subject_type="approval_rule",
            subject_id=rule.id,
            summary=f"Set an approval threshold at {rule.currency} {threshold / 100:,.0f}.",
        )
        return Response({"id": str(rule.id)}, status=status.HTTP_201_CREATED)


class SpendApprovalListView(TenantScopedAPIView, APIView):
    """Open approvals, and the history behind them."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="household_approvals")
    def get(self, request):
        from .. import approvals

        rows = approvals.pending() if request.query_params.get("status") == "pending" else approvals.history()
        return Response([_approval_json(a) for a in rows])

    @extend_schema(operation_id="household_request_approval")
    def post(self, request):
        from .. import approvals

        try:
            approval = approvals.request_approval(
                amount_minor=int(request.data.get("amount_minor", 0)),
                currency=request.data.get("currency") or "KES",
                description=request.data.get("description", ""),
                account_id=request.data.get("financial_account_id") or None,
                rule=approvals.matching_rule(
                    amount_minor=int(request.data.get("amount_minor", 0)),
                    account_id=request.data.get("financial_account_id") or None,
                ),
            )
        except (approvals.ApprovalError, TypeError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_approval_json(approval), status=status.HTTP_201_CREATED)


class SpendApprovalDetailView(TenantScopedAPIView, APIView):
    """Answer an approval: approve, decline, suggest, withdraw, or comment."""

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = None

    @extend_schema(operation_id="household_resolve_approval")
    def post(self, request, approval_id):
        from .. import approvals
        from ..models import SpendApproval

        approval = get_object_or_404(SpendApproval, id=approval_id)
        action = (request.data.get("action") or "").lower()
        note = request.data.get("note", "")

        try:
            if action == "approve":
                approvals.approve(approval=approval, note=note)
            elif action == "decline":
                approvals.decline(approval=approval, note=note)
            elif action == "withdraw":
                approvals.withdraw(approval=approval)
            elif action == "suggest":
                approvals.suggest(
                    approval=approval,
                    amount_minor=int(request.data.get("amount_minor", 0)),
                    note=note,
                )
            elif action == "comment":
                approvals.comment(approval=approval, body=note)
            else:
                return Response(
                    {"detail": "action must be approve, decline, suggest, withdraw or comment."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except (approvals.ApprovalError, TypeError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        approval.refresh_from_db()
        return Response(_approval_json(approval))


def _approval_json(a) -> dict:
    return {
        "id": str(a.id),
        "kind": a.kind,
        "status": a.status,
        "amount_minor": a.amount_minor,
        "suggested_amount_minor": a.suggested_amount_minor,
        "currency": a.currency,
        "description": a.description,
        "requested_by": a.requested_by_label,
        "resolved_by": a.resolved_by_label,
        "expires_at": a.expires_at,
        "resolved_at": a.resolved_at,
        "created_at": a.created_at,
        "comments": [
            {"author": c.author_label, "body": c.body, "at": c.created_at} for c in a.comments.all()
        ],
    }
