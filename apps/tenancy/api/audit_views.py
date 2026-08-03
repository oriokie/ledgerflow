"""Reading the workspace activity trail.

The rows have been written since the audit fix; nothing could read them. In a
shared household that is the question people actually ask — "who deleted that?"
— and answering it is the whole reason the table exists.

Two constraints shape this module.

**Scoping is manual and deliberate.** `common_auditlog` is intentionally not
RLS-protected: it records workspace creation and invitation acceptance, which
happen before a per-request tenant GUC exists, and is read cross-tenant by
trusted workers. The rationale is in
`ledger/migrations/0002_financial_integrity.py`. So every query here filters
`tenant_id` explicitly, and `_scoped()` is the single place that does it —
there is no code path to this data that bypasses it.

**Actors are resolved, not exposed raw.** The table stores `actor_id` only. A
UUID is useless to a person reading their own history, so names are resolved in
one bulk query — never per row, which would make a 50-row page 50 queries.
"""

from __future__ import annotations

from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api_base import TenantScopedAPIView
from apps.common.audit import AuditLog
from apps.common.pagination import CursorPagination
from apps.common.tenant_context import require_current_tenant_id
from apps.tenancy.models import Membership, Role
from apps.tenancy.permissions import IsTenantMember

#: Human labels for the actions recorded so far. A missing entry falls back to
#: the raw action string rather than hiding the row — an unlabelled entry is
#: still evidence, and silently dropping it would make the log lie by omission.
ACTION_LABELS = {
    "workspace.closed": "Closed the workspace",
    "member.removed": "Removed a member",
    "member.role_changed": "Changed a member's role",
    "transaction.voided": "Voided a transaction",
    "security.updated": "Edited a tracked security",
    "security.deleted": "Removed a tracked security",
    "tag.updated": "Renamed a tag",
    "tag.deleted": "Deleted a tag",
}


class AuditEntrySerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    action = serializers.CharField(read_only=True)
    label = serializers.SerializerMethodField()
    actor_id = serializers.UUIDField(read_only=True, allow_null=True)
    actor_name = serializers.SerializerMethodField()
    target_type = serializers.CharField(read_only=True)
    target_id = serializers.UUIDField(read_only=True, allow_null=True)
    changes = serializers.JSONField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    def get_label(self, obj) -> str:
        return ACTION_LABELS.get(obj.action, obj.action)

    def get_actor_name(self, obj) -> str:
        # A null actor is a system action (a scheduled task, a webhook), which
        # is meaningfully different from "someone we can't identify".
        if obj.actor_id is None:
            return "Automation"
        return self.context.get("actors", {}).get(obj.actor_id, "A former member")


class WorkspaceAuditView(TenantScopedAPIView, APIView):
    """Recent activity in this workspace.

    Restricted to roles that can already see who the members are. A VIEWER can
    read the workspace's money but has no business reading a log of who
    administered it — that is governance, not finance.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = AuditEntrySerializer

    def _scoped(self):
        """The only query path to audit rows. See the module docstring."""
        return AuditLog.objects.filter(tenant_id=require_current_tenant_id())

    @extend_schema(operation_id="workspace_audit_list")
    def get(self, request):
        queryset = self._scoped().order_by("-created_at", "-id")

        action = request.query_params.get("action")
        if action:
            queryset = queryset.filter(action=action)
        actor = request.query_params.get("actor_id")
        if actor:
            queryset = queryset.filter(actor_id=actor)
        since = request.query_params.get("since")
        if since:
            parsed = parse_datetime(since)
            if parsed is None:
                return Response(
                    {"since": ["Expected an ISO 8601 timestamp."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(created_at__gte=parsed)

        paginator = CursorPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(
            AuditEntrySerializer(
                page, many=True, context={"actors": _actor_names(page)}
            ).data
        )


def _actor_names(rows) -> dict:
    """Resolve actor ids to display names in one query.

    Members are looked up by tenant rather than globally: a workspace should
    learn nothing about users outside it, even accidentally, and a stale
    `actor_id` from someone since removed simply falls through to the
    "A former member" default rather than leaking their identity.
    """
    ids = {row.actor_id for row in rows if row.actor_id}
    if not ids:
        return {}
    memberships = Membership.objects.filter(
        tenant_id=require_current_tenant_id(), user_id__in=ids
    ).select_related("user")
    return {m.user_id: (m.user.full_name or m.user.email) for m in memberships}
