from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from apps.common.api_base import TenantScopedAPIView
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import selectors, services
from ..services import LedgerError, LineInput
from .serializers import AccountSerializer, PostEntrySerializer


class AccountViewSet(TenantScopedAPIView, ViewSet):
    """Views stay thin: validate -> call service/selector -> serialize."""

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER  # writing needs at least MEMBER
    throttle_scope = "write"
    serializer_class = AccountSerializer

    def list(self, request):
        accounts = selectors.list_accounts()
        return Response(AccountSerializer(accounts, many=True).data)

    def create(self, request):
        data = request.data
        account = services.create_account(
            name=data["name"],
            kind=data["kind"],
            currency=data["currency"],
        )
        return Response(AccountSerializer(account).data, status=status.HTTP_201_CREATED)


class JournalEntryViewSet(TenantScopedAPIView, ViewSet):
    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    throttle_scope = "write"
    serializer_class = PostEntrySerializer

    def create(self, request):
        serializer = PostEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        try:
            entry = services.post_journal_entry(
                occurred_at=v["occurred_at"],
                idempotency_key=v["idempotency_key"],
                memo=v.get("memo", ""),
                lines=[
                    LineInput(str(line["account_id"]), line["direction"], line["amount_minor"])
                    for line in v["lines"]
                ],
            )
        except LedgerError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response({"id": str(entry.id)}, status=status.HTTP_201_CREATED)

    def list(self, request):
        entries = selectors.list_entries()
        return Response(
            [
                {
                    "id": str(e.id),
                    "occurred_at": e.occurred_at,
                    "currency": e.currency,
                    "memo": e.memo,
                    "lines": [
                        {
                            "account_id": str(line.account_id),
                            "direction": line.direction,
                            "amount_minor": line.amount_minor,
                        }
                        for line in e.lines.all()
                    ],
                }
                for e in entries
            ]
        )
