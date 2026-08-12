from __future__ import annotations

from dataclasses import asdict
from datetime import date

from django.http import FileResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.plan_catalogue import PlanFeature
from apps.common.api_base import TenantScopedAPIView, WriteRequiresMemberMixin, require_feature
from apps.common.pagination import CursorPagination
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import attachments as attachment_service
from .. import bills as bills_service
from .. import cashflow_calendar as calendar_selectors
from .. import payees as payee_service
from .. import reconciliation, selectors, services
from .. import recurring as recurring_service
from .. import tagging as tag_service
from .. import wallets as wallet_service
from ..attachments import AttachmentError
from ..models import (
    Attachment,
    Category,
    FinancialAccount,
    Payee,
    RecurringTransaction,
    Tag,
    Transaction,
    Wallet,
)
from ..payees import PayeeError
from ..tagging import TagError
from .serializers import (
    AttachmentConfirmSerializer,
    AttachmentRequestSerializer,
    AttachmentSerializer,
    BillCreateSerializer,
    BillPaySerializer,
    CashflowCalendarQuerySerializer,
    CategoryCreateSerializer,
    CategorySerializer,
    CategoryUpdateSerializer,
    DateRangeQuerySerializer,
    FinancialAccountCreateSerializer,
    FinancialAccountSerializer,
    FinancialAccountUpdateSerializer,
    PayeeCreateSerializer,
    PayeeSerializer,
    ReconcileSerializer,
    RecurringCreateSerializer,
    RecurringSerializer,
    RecurringUpdateSerializer,
    SetTransactionTagsSerializer,
    StatementQuerySerializer,
    TagCreateSerializer,
    TagSerializer,
    TransactionBulkSerializer,
    TransactionCreateSerializer,
    TransactionReclassifyTransferSerializer,
    TransactionSerializer,
    TransactionSplitSerializer,
    TransactionUpdateSerializer,
    TransferCreateSerializer,
    WalletAssignAccountSerializer,
    WalletCreateSerializer,
    WalletSerializer,
)


def _finance_error(exc) -> Response:
    body = {"detail": str(exc)}
    # An overdraft refusal carries the figures behind it, so the client can
    # offer the fix ("you're 1,200 short") rather than only repeating the
    # sentence. `code` lets the UI single it out from other 422s.
    if isinstance(exc, services.InsufficientFundsError):
        body |= {
            "code": "insufficient_funds",
            "account_name": exc.account_name,
            "available_minor": exc.available_minor,
            "shortfall_minor": exc.shortfall_minor,
        }
    return Response(body, status=status.HTTP_422_UNPROCESSABLE_ENTITY)


def _parse_txn_filters(request) -> selectors.TransactionFilters:
    """Translate query params into a TransactionFilters. Unknown/blank params
    are ignored; malformed ints/dates are dropped rather than erroring, so a
    stray query string never 500s the list — the worst case is a wider result
    set, which the caller can see and correct."""
    from datetime import datetime

    from django.utils.dateparse import parse_datetime

    qp = request.query_params

    def _int(name):
        raw = qp.get(name)
        try:
            return int(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def _dt(name):
        raw = qp.get(name)
        if not raw:
            return None
        parsed = parse_datetime(raw)
        if parsed is None:
            try:  # accept a bare date (YYYY-MM-DD) too
                parsed = datetime.fromisoformat(raw)
            except ValueError:
                return None
        return parsed

    def _bool(name):
        raw = qp.get(name)
        if raw is None or raw == "":
            return None
        return raw.lower() in ("1", "true", "yes")

    return selectors.TransactionFilters(
        category_id=qp.get("category_id") or None,
        payee_id=qp.get("payee_id") or None,
        tag_id=qp.get("tag_id") or None,
        status=qp.get("status") or None,
        txn_type=qp.get("type") or None,
        start=_dt("start"),
        end=_dt("end"),
        min_amount_minor=_int("min_amount_minor"),
        max_amount_minor=_int("max_amount_minor"),
        search=qp.get("search") or qp.get("q") or None,
        needs_review=_bool("needs_review"),
    )


def _txn_out(txn: Transaction, *, levels: dict | None = None) -> dict:
    """One shape for a transaction, redacted for the acting household member.

    Redaction happens *here*, at the single point every transaction response
    passes through, rather than in each endpoint. Nine call sites format
    transactions; asking each to remember which fields are sensitive is asking
    for the one that forgets.

    `levels` is an optimisation, not a switch. Passing the map from
    `redaction_levels()` avoids a query per row on a listing; omitting it costs
    a query and redacts anyway. Forgetting to pass it makes the endpoint
    slower, never more revealing — which is the direction that mistake should
    fail in.
    """
    from apps.household import transaction_privacy

    payload = {
        "id": txn.id,
        "financial_account_id": txn.financial_account_id,
        "amount_minor": txn.amount_minor,
        "currency": txn.currency,
        "occurred_at": txn.occurred_at,
        "status": txn.status,
        "source": txn.source,
        "category_id": txn.category_id,
        "payee_id": txn.payee_id,
        "counter_account_id": txn.counter_account_id,
        "transfer_group": txn.transfer_group,
        "split_group": txn.split_group,
        # Lets the client pre-empt a reclassify-as-transfer 422 (see
        # services.reclassify_as_transfer) instead of only finding out after
        # a round trip.
        "reconciled_at": txn.reconciled_at,
        # Flagged by an import or a rule that could not decide. Exposed so the
        # ledger can show *which* rows need a look and why, rather than only
        # letting them be filtered for.
        "needs_review": txn.needs_review,
        "review_reason": txn.review_reason,
        "memo": txn.memo,
        # Expose only explicitly supported audit metadata, not the JSON field
        # wholesale: future internal keys must not silently cross the privacy
        # boundary this formatter owns.
        "metadata": (
            {"mpesa_receipt": txn.metadata["mpesa_receipt"]}
            if isinstance(txn.metadata.get("mpesa_receipt"), str)
            else {}
        ),
    }
    if levels is None:
        levels = transaction_privacy.redaction_levels()
    return transaction_privacy.apply(payload, levels.get(txn.id))


def _account_payload(account: FinancialAccount) -> dict:
    """One shape for an account, used by every account endpoint so list, create
    and update responses can never drift apart.

    Always rendered through FinancialAccountSerializer by `_account_response`,
    so a client sees identical field *types* everywhere — returning a raw UUID
    from create while the list returns a string is the kind of inconsistency
    that quietly breaks client-side identity comparisons.
    """
    return {
        "id": account.id,
        "name": account.name,
        "account_type": account.account_type,
        "currency": account.currency,
        "balance_minor": selectors.account_current_balance_minor(account),
        "mask": account.mask,
        "color": account.color,
        "icon": account.icon,
        "notes": account.notes,
        "is_hidden": account.is_hidden,
        "is_archived": account.is_archived,
        "include_in_net_worth": account.include_in_net_worth,
        "include_in_budgets": account.include_in_budgets,
    }


def _account_response(account: FinancialAccount, status_code: int = status.HTTP_200_OK) -> Response:
    return Response(FinancialAccountSerializer(_account_payload(account)).data, status=status_code)


# ------------------------------------------------------------------ accounts
# ---------------------------------------------------------------------------
# Household member-visibility perimeter.
#
# `apps.household.visibility` decides which accounts the acting member may see
# and touch inside a shared workspace. That module existed before this edge
# did — Phase 3 enforced it in the household analytics and nowhere the user
# actually looks, which made a "private" account private on the summary page
# and fully visible in the accounts list. The perimeter belongs here, at the
# HTTP boundary, so the finance domain stays independent of household while
# every itemised surface applies the workspace's policy.
#
# The read rule is uniform on purpose: an account the member may not see
# behaves exactly like an account that does not exist — same 404, same "not
# found", including as a transfer leg or a counter account. Anything softer
# (a 403, a redacted row) confirms the account exists, which is the leak.
# ---------------------------------------------------------------------------
def _visible_accounts():
    """`FinancialAccount` queryset narrowed to what the acting member may see."""
    from apps.household.visibility import restrict_accounts

    return restrict_accounts(FinancialAccount.objects.all())


def _member_visible_ids():
    """Visible account ids, or None when no member filtering applies."""
    from apps.household.visibility import visible_account_ids

    return visible_account_ids()


def _txn_account_visible(txn) -> bool:
    """Whether the transaction's account is one the member may see. A txn
    reached by id must not confirm a private account's activity exists."""
    allowed = _member_visible_ids()
    return allowed is None or txn.financial_account_id in allowed


def _member_write_block(account_id) -> Response | None:
    """A 403 explaining why the write is refused, or None to proceed.

    Only reachable for accounts the member can *see* — invisible ones already
    404ed at resolution — so the message can safely acknowledge the account
    exists and say who controls it.
    """
    from apps.household.visibility import can_write_account, needs_approval

    if account_id is None or can_write_account(account_id):
        return None
    if needs_approval(account_id):
        detail = (
            "This account's owner requires approval for changes. Propose it "
            "through the household change-request flow instead of editing directly."
        )
    else:
        detail = "This account is read-only to you; only its owner can change it."
    return Response({"detail": detail}, status=status.HTTP_403_FORBIDDEN)


class AccountView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = FinancialAccountSerializer

    def get(self, request):
        """Active accounts by default. `?include_archived=1` returns closed
        accounts too, for the settings surface where a user reopens one."""
        qs = _visible_accounts().select_related("ledger_account__balance")
        if request.query_params.get("include_archived") not in ("1", "true"):
            qs = qs.filter(archived_at__isnull=True)
        data = [_account_payload(a) for a in qs]
        return Response(FinancialAccountSerializer(data, many=True).data)

    def post(self, request):
        s = FinancialAccountCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        account = services.create_financial_account(
            name=v["name"],
            account_type=v["account_type"],
            currency=v["currency"].upper(),
            mask=v.get("mask", ""),
            color=v.get("color", ""),
            icon=v.get("icon", ""),
            notes=v.get("notes", ""),
            include_in_net_worth=v.get("include_in_net_worth", True),
            include_in_budgets=v.get("include_in_budgets", True),
            opening_balance_minor=v.get("opening_balance_minor", 0),
            opening_balance_at=v.get("opening_balance_at"),
        )
        return _account_response(account, status.HTTP_201_CREATED)


class AccountDetailView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Presentation/inclusion updates and the archive lifecycle.

    DELETE archives rather than destroys: the ledger lines behind an account are
    immutable and still belong in historical reports, so a closed account keeps
    every entry it ever had.
    """

    permission_classes = [IsTenantMember]
    serializer_class = FinancialAccountUpdateSerializer

    def _get(self, account_id) -> FinancialAccount:
        return get_object_or_404(_visible_accounts(), pk=account_id)

    def patch(self, request, account_id):
        account = self._get(account_id)
        if (blocked := _member_write_block(account.id)) is not None:
            return blocked
        s = FinancialAccountUpdateSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        account = services.update_financial_account(financial_account=account, **s.validated_data)
        return _account_response(account)

    def delete(self, request, account_id):
        account = self._get(account_id)
        if (blocked := _member_write_block(account.id)) is not None:
            return blocked
        services.archive_financial_account(financial_account=account)
        return _account_response(account)


class AccountUnarchiveView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = FinancialAccountSerializer

    def post(self, request, account_id):
        account = get_object_or_404(_visible_accounts(), pk=account_id)
        if (blocked := _member_write_block(account.id)) is not None:
            return blocked
        services.unarchive_financial_account(financial_account=account)
        return _account_response(account)


class AccountPurgeView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Permanent removal — distinct from `AccountDetailView.delete`, which
    archives. Only reachable when the account has no transactions, recurring
    schedule, or bill autopay reference left pointing at it."""

    permission_classes = [IsTenantMember]

    def delete(self, request, account_id):
        account = get_object_or_404(_visible_accounts(), pk=account_id)
        if (blocked := _member_write_block(account.id)) is not None:
            return blocked
        try:
            services.delete_financial_account(financial_account=account)
        except services.FinanceError as exc:
            return _finance_error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AccountStatementView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = StatementQuerySerializer

    def get(self, request, account_id):
        account = _visible_accounts().filter(id=account_id).first()
        if account is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        q = StatementQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        opening, rows = selectors.account_statement(
            financial_account=account, start=q.validated_data["start"], end=q.validated_data["end"]
        )
        return Response(
            {
                "opening_balance_minor": opening,
                "lines": [{**_txn_out(txn), "running_balance_minor": running} for txn, running in rows],
            }
        )


# ------------------------------------------------------------------ categories
class CategoryView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = CategorySerializer

    def get(self, request):
        categories = Category.objects.all().order_by("path")
        return Response(
            CategorySerializer(
                [
                    {
                        "id": c.id,
                        "name": c.name,
                        "kind": c.kind,
                        "path": c.path,
                        "depth": c.depth,
                        "parent_id": c.parent_id,
                    }
                    for c in categories
                ],
                many=True,
            ).data
        )

    def post(self, request):
        s = CategoryCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        parent = None
        if v.get("parent_id"):
            parent = Category.objects.filter(id=v["parent_id"]).first()
            if parent is None:
                return Response({"detail": "parent not found"}, status=status.HTTP_400_BAD_REQUEST)
        category = services.create_category(
            name=v["name"],
            kind=v["kind"],
            currency=v["currency"].upper(),
            parent=parent,
            color=v.get("color", ""),
            icon=v.get("icon", ""),
        )
        return Response(
            {
                "id": category.id,
                "name": category.name,
                "kind": category.kind,
                "path": category.path,
                "depth": category.depth,
                "parent_id": category.parent_id,
            },
            status=status.HTTP_201_CREATED,
        )


class CategoryDetailView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Edit (name/color/icon) or delete a single category. `kind` is immutable
    by design; deletion is guarded (system categories, children, and
    in-use categories are protected — see services.archive_category)."""

    permission_classes = [IsTenantMember]
    serializer_class = CategoryUpdateSerializer

    def patch(self, request, category_id):
        category = Category.objects.filter(id=category_id).first()
        if category is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = CategoryUpdateSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        kwargs = {k: v[k] for k in ("name", "color", "icon") if k in v}
        if "parent_id" in v:
            parent = Category.objects.filter(id=v["parent_id"]).first() if v["parent_id"] else None
            if v["parent_id"] and parent is None:
                return Response({"detail": "parent not found"}, status=status.HTTP_400_BAD_REQUEST)
            kwargs["parent"] = parent

        try:
            category = services.update_category(category=category, **kwargs)
        except services.FinanceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(
            {
                "id": category.id,
                "name": category.name,
                "kind": category.kind,
                "path": category.path,
                "depth": category.depth,
                "parent_id": category.parent_id,
            }
        )

    def delete(self, request, category_id):
        category = Category.objects.filter(id=category_id).first()
        if category is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            services.archive_category(category=category)
        except services.FinanceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ transactions
class TransactionCursorPagination(CursorPagination):
    """`-created_at` (the generic default) isn't the right chronology for a
    transaction list — users expect it ordered by when the money moved
    (`occurred_at`), not when the row was inserted (e.g. an imported/backfilled
    transaction). `-id` is the required unique tiebreaker for stable cursors
    (UUIDv7 is time-ordered, so it's also a correct secondary sort)."""

    ordering = ("-occurred_at", "-id")


class TransactionView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = TransactionSerializer
    pagination_class = TransactionCursorPagination

    def get(self, request):
        account_id = request.query_params.get("account_id")
        account = _visible_accounts().filter(id=account_id).first() if account_id else None
        txns = selectors.list_transactions(financial_account=account, filters=_parse_txn_filters(request))
        # A private account's activity must not surface through the unfiltered
        # ledger. The account-scoped path is already covered by the resolution
        # above; this covers the "all transactions" page.
        allowed = _member_visible_ids()
        if allowed is not None:
            txns = txns.filter(financial_account_id__in=allowed)
        # Then the line-level rule, inside accounts the member may already see.
        # Only fully-private lines are dropped; partially-redacted ones stay and
        # are blunted by `_txn_out`, because removing them would leave the same
        # unexplained gap while telling the partner less.
        from apps.household import transaction_privacy

        txns = transaction_privacy.restrict_transactions(txns)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(txns, request, view=self)
        # Levels fetched once for the page rather than once per row.
        levels = transaction_privacy.redaction_levels()
        return paginator.get_paginated_response([_txn_out(t, levels=levels) for t in page])

    def post(self, request):
        s = TransactionCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        account = _visible_accounts().filter(id=v["financial_account_id"]).first()
        category = Category.objects.filter(id=v["category_id"]).first()
        if account is None or category is None:
            return Response({"detail": "account or category not found"}, status=status.HTTP_400_BAD_REQUEST)
        if (blocked := _member_write_block(account.id)) is not None:
            return blocked
        fn = services.record_expense if v["type"] == "expense" else services.record_income
        try:
            txn = fn(
                financial_account=account,
                category=category,
                amount_minor=v["amount_minor"],
                occurred_at=v["occurred_at"],
                memo=v.get("memo", ""),
                idempotency_key=v.get("idempotency_key") or None,
            )
        except services.FinanceError as exc:
            return _finance_error(exc)
        return Response(_txn_out(txn), status=status.HTTP_201_CREATED)


class TransactionReviewCountView(TenantScopedAPIView, APIView):
    """How many transactions are flagged for review.

    A count, not a page. The list endpoint is cursor-paginated — deliberately,
    because a ledger has no natural end — and cursor pagination cannot report a
    total. Anything that wants to say "12 need a look" therefore needs to ask
    the question directly rather than counting a page and hoping.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="finance_transaction_review_count")
    def get(self, request):
        count = Transaction.objects.filter(needs_review=True).count()
        return Response({"count": count})


class TransactionDetailView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """GET a single transaction; PATCH edits category/payee/memo only —
    everything ledger-affecting (amount, account, direction) is immutable
    here by design. See `services.update_transaction`."""

    permission_classes = [IsTenantMember]
    serializer_class = TransactionUpdateSerializer

    @extend_schema(operation_id="finance_transaction_retrieve")
    def get(self, request, txn_id):
        txn = (
            Transaction.objects.filter(id=txn_id)
            .select_related("category", "counter_account", "payee")
            .first()
        )
        if txn is None or not _txn_account_visible(txn):
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(_txn_out(txn))

    def patch(self, request, txn_id):
        txn = Transaction.objects.filter(id=txn_id).first()
        if txn is None or not _txn_account_visible(txn):
            return Response(status=status.HTTP_404_NOT_FOUND)
        if (blocked := _member_write_block(txn.financial_account_id)) is not None:
            return blocked
        s = TransactionUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        kwargs = {}
        if "category_id" in v:
            kwargs["category"] = (
                Category.objects.filter(id=v["category_id"]).first() if v["category_id"] else None
            )
            if v["category_id"] and kwargs["category"] is None:
                return Response({"detail": "category not found"}, status=status.HTTP_400_BAD_REQUEST)
        if "payee_id" in v:
            kwargs["payee"] = Payee.objects.filter(id=v["payee_id"]).first() if v["payee_id"] else None
            if v["payee_id"] and kwargs["payee"] is None:
                return Response({"detail": "payee not found"}, status=status.HTTP_400_BAD_REQUEST)
        if "memo" in v:
            kwargs["memo"] = v["memo"]

        try:
            txn = services.update_transaction(txn=txn, **kwargs)
        except services.FinanceError as exc:
            return _finance_error(exc)
        return Response(_txn_out(txn))


class TransactionVoidView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = TransactionSerializer

    def post(self, request, txn_id):
        txn = Transaction.objects.filter(id=txn_id).first()
        if txn is None or not _txn_account_visible(txn):
            return Response(status=status.HTTP_404_NOT_FOUND)
        if (blocked := _member_write_block(txn.financial_account_id)) is not None:
            return blocked
        try:
            services.void_transaction(txn=txn)
        except services.FinanceError as exc:
            return _finance_error(exc)
        txn.refresh_from_db()
        return Response(_txn_out(txn))


class TransactionReclassifyTransferView(TenantScopedAPIView, APIView):
    """Fix a statement-import row that was actually a transfer between two of
    the household's own accounts — voids the misposted expense/income row and
    reposts it as a real linked transfer. See `services.reclassify_as_transfer`."""

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = TransactionReclassifyTransferSerializer

    def post(self, request, txn_id):
        txn = Transaction.objects.filter(id=txn_id).first()
        if txn is None or not _txn_account_visible(txn):
            return Response(status=status.HTTP_404_NOT_FOUND)
        if (blocked := _member_write_block(txn.financial_account_id)) is not None:
            return blocked
        s = TransactionReclassifyTransferSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        counter_account = _visible_accounts().filter(id=v["counter_account_id"]).first()
        if counter_account is None:
            return Response({"detail": "account not found"}, status=status.HTTP_400_BAD_REQUEST)
        if (blocked := _member_write_block(counter_account.id)) is not None:
            return blocked
        try:
            out_txn, in_txn = services.reclassify_as_transfer(
                txn=txn,
                counter_account=counter_account,
                idempotency_key=v.get("idempotency_key") or None,
            )
        except services.FinanceError as exc:
            return _finance_error(exc)
        return Response({"out": _txn_out(out_txn), "in": _txn_out(in_txn)})


class TransactionBulkView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Batch categorize/void in one request instead of N round-trips. The id
    lookup is RLS-scoped to the tenant, so cross-tenant ids simply don't resolve
    and are reported back as failures; per-row domain errors (kind mismatch,
    un-voidable rows) are collected too. The whole thing runs in the view's
    single atomic transaction."""

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = TransactionBulkSerializer

    def post(self, request):
        s = TransactionBulkSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        ids = [str(i) for i in v["ids"]]

        txns = list(Transaction.objects.filter(id__in=ids))
        found = {str(t.id) for t in txns}
        failed = [{"id": i, "error": "not found"} for i in ids if i not in found]

        if v["action"] == "categorize":
            category = None
            if v.get("category_id"):
                category = Category.objects.filter(id=v["category_id"]).first()
                if category is None:
                    return Response({"detail": "category not found"}, status=status.HTTP_400_BAD_REQUEST)
            result = services.bulk_categorize_transactions(txns=txns, category=category)
        else:
            result = services.bulk_void_transactions(txns=txns)

        failed.extend(result["failed"])
        return Response({"requested": len(ids), "updated": result["updated"], "failed": failed})


class TransferView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = TransferCreateSerializer

    def post(self, request):
        s = TransferCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        from_account = _visible_accounts().filter(id=v["from_account_id"]).first()
        to_account = _visible_accounts().filter(id=v["to_account_id"]).first()
        if from_account is None or to_account is None:
            return Response({"detail": "account not found"}, status=status.HTTP_400_BAD_REQUEST)
        # Both legs move money, so both need to be writable — a transfer out of
        # a read-only account is exactly the write its policy exists to stop.
        for leg in (from_account, to_account):
            if (blocked := _member_write_block(leg.id)) is not None:
                return blocked
        try:
            out_txn, in_txn = services.record_transfer(
                from_account=from_account,
                to_account=to_account,
                amount_minor=v["amount_minor"],
                occurred_at=v["occurred_at"],
                memo=v.get("memo", ""),
                idempotency_key=v.get("idempotency_key") or None,
            )
        except services.FinanceError as exc:
            return _finance_error(exc)
        return Response({"out": _txn_out(out_txn), "in": _txn_out(in_txn)}, status=status.HTTP_201_CREATED)


# ------------------------------------------------------------------ recurring
class RecurringView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = RecurringSerializer

    def get(self, request):
        recs = RecurringTransaction.objects.filter(is_active=True).order_by("next_run_on")
        return Response(RecurringSerializer(recs, many=True).data)

    def post(self, request):
        s = RecurringCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        account = _visible_accounts().filter(id=v["financial_account_id"]).first()
        counter = (
            _visible_accounts().filter(id=v["counter_account_id"]).first()
            if v.get("counter_account_id")
            else None
        )
        category = Category.objects.filter(id=v["category_id"]).first() if v.get("category_id") else None
        try:
            rec = recurring_service.create_recurring_transaction(
                txn_type=v["txn_type"],
                financial_account=account,
                counter_account=counter,
                category=category,
                amount_minor=v["amount_minor"],
                currency=v["currency"].upper(),
                frequency=v["frequency"],
                interval=v.get("interval", 1),
                starts_on=v["starts_on"],
                ends_on=v.get("ends_on"),
                max_occurrences=v.get("max_occurrences"),
                memo=v.get("memo", ""),
            )
        except services.FinanceError as exc:
            return _finance_error(exc)
        return Response(RecurringSerializer(rec).data, status=status.HTTP_201_CREATED)


class RecurringDetailView(TenantScopedAPIView, APIView):
    """Edit (PATCH), pause/resume (PATCH is_active) or cancel (DELETE) a
    schedule — the levers for correcting and trimming recurring spend.

    Editing changes the plan from here on; it never rewrites the occurrences
    already posted from the template. See ``recurring.update_recurring_transaction``.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = RecurringUpdateSerializer

    def patch(self, request, rec_id):
        rec = RecurringTransaction.objects.filter(id=rec_id).first()
        if rec is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = RecurringUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = dict(s.validated_data)

        # Pausing is its own operation, not a field edit: it has to work on a
        # schedule whose plan is otherwise untouched, and it is the one change
        # that must never re-anchor `next_run_on`.
        active = v.pop("is_active", None)

        if v:
            changes = {}
            if "category_id" in v:
                cid = v.pop("category_id")
                changes["category"] = Category.objects.filter(id=cid).first() if cid else None
            if "counter_account_id" in v:
                aid = v.pop("counter_account_id")
                changes["counter_account"] = _visible_accounts().filter(id=aid).first() if aid else None
            changes.update(v)
            try:
                rec = recurring_service.update_recurring_transaction(rec=rec, **changes)
            except services.FinanceError as exc:
                return _finance_error(exc)

        if active is not None:
            rec = recurring_service.set_recurring_active(rec=rec, active=active)

        return Response(RecurringSerializer(rec).data)

    def delete(self, request, rec_id):
        rec = RecurringTransaction.objects.filter(id=rec_id).first()
        if rec is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        recurring_service.cancel_recurring(rec=rec)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ calculations
class NetWorthView(TenantScopedAPIView, APIView):
    """Assets, liabilities and net worth, per currency.

    `assets_minor` and `net_minor` are **book value**, read straight from the
    ledger, and investments are carried at cost there — that is what keeps the
    ledger internally consistent and free of unposted gains.

    A portfolio that has grown is therefore understated by those figures, so the
    unrealised gain is returned alongside as an explicit overlay rather than
    folded in. The client chooses which to show, and the two never get confused:
    one is what the books say, the other is what the market says.

    `unrealized_gain_minor` is 0 when nothing is held or nothing is priced — the
    overlay never claims a gain on a position nobody has valued.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    def get(self, request):
        from apps.assets import selectors as asset_selectors
        from apps.investments import selectors as investment_selectors

        rows = []
        for n in selectors.net_worth():
            unrealized = investment_selectors.unrealized_gain_for_net_worth(currency=n.currency)
            # Assets a household owns but does not transact through — a house, a
            # car. A second overlay rather than a ledger balance, for the same
            # reason as the first: their worth changes because somebody
            # re-estimated it, not because money moved. Unvalued assets
            # contribute nothing, so this never claims a value nobody supplied.
            owned = asset_selectors.total_value_minor(currency=n.currency)
            rows.append(
                {
                    "currency": n.currency,
                    "assets_minor": n.assets_minor,
                    "liabilities_minor": n.liabilities_minor,
                    "net_minor": n.net_minor,
                    # The overlay: what the same position is worth today.
                    "unrealized_gain_minor": unrealized,
                    "asset_value_minor": owned,
                    "market_assets_minor": n.assets_minor + unrealized + owned,
                    "market_net_minor": n.net_minor + unrealized + owned,
                }
            )
        return Response(rows)


class CashFlowView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = DateRangeQuerySerializer

    def get(self, request):
        q = DateRangeQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        return Response(
            [
                {
                    "currency": c.currency,
                    "income_minor": c.income_minor,
                    "expense_minor": c.expense_minor,
                    "net_minor": c.net_minor,
                }
                for c in selectors.cash_flow(start=q.validated_data["start"], end=q.validated_data["end"])
            ]
        )


class CategoryBreakdownView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = DateRangeQuerySerializer

    def get(self, request):
        q = DateRangeQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        expense = request.query_params.get("type", "expense") != "income"
        rows = selectors.category_breakdown(
            start=q.validated_data["start"], end=q.validated_data["end"], expense=expense
        )
        return Response(
            [
                {
                    "category_id": r.category_id,
                    "category_name": r.category_name,
                    "amount_minor": r.amount_minor,
                }
                for r in rows
            ]
        )


class CategoryTrendView(TenantScopedAPIView, APIView):
    """Monthly spend (or income) for a single category over the trailing N
    months — the drill-down series behind the analytics category chart."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    def get(self, request):
        category_id = request.query_params.get("category_id")
        if not category_id:
            return Response({"detail": "category_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        raw = request.query_params.get("months", "6")
        months = int(raw) if raw.isdigit() else 6
        months = max(1, min(24, months))
        expense = request.query_params.get("type", "expense") != "income"
        rows = selectors.category_monthly_trend(category_id=category_id, months=months, expense=expense)
        return Response(rows)


# ------------------------------------------------------------------ wallets
def _wallet_out(wallet: Wallet) -> dict:
    balances = selectors.wallet_balances(wallet)
    return {
        "id": wallet.id,
        "name": wallet.name,
        "icon": wallet.icon,
        "color": wallet.color,
        "is_default": wallet.is_default,
        "balances": [{"currency": b.currency, "balance_minor": b.balance_minor} for b in balances],
    }


class WalletView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = WalletSerializer

    def get(self, request):
        wallets = Wallet.objects.all().order_by("name")
        return Response([_wallet_out(w) for w in wallets])

    def post(self, request):
        s = WalletCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        wallet = wallet_service.create_wallet(**v)
        return Response(_wallet_out(wallet), status=status.HTTP_201_CREATED)


class WalletAccountAssignmentView(TenantScopedAPIView, APIView):
    """A single endpoint moves an account into a wallet (`wallet_id` given)
    or out of any wallet (`wallet_id` omitted/null) — one operation, not two
    separate "assign"/"unassign" verbs for what is really the same state
    transition."""

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = WalletAssignAccountSerializer

    def post(self, request):
        s = WalletAssignAccountSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        account = _visible_accounts().filter(id=v["financial_account_id"]).first()
        if account is None:
            return Response({"detail": "account not found"}, status=status.HTTP_400_BAD_REQUEST)
        wallet = None
        if v.get("wallet_id"):
            wallet = Wallet.objects.filter(id=v["wallet_id"]).first()
            if wallet is None:
                return Response({"detail": "wallet not found"}, status=status.HTTP_400_BAD_REQUEST)
        account = wallet_service.assign_account_to_wallet(financial_account=account, wallet=wallet)
        return Response({"financial_account_id": account.id, "wallet_id": account.wallet_id})


class WalletBalanceView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="finance_wallet_retrieve")
    def get(self, request, wallet_id):
        wallet = Wallet.objects.filter(id=wallet_id).first()
        if wallet is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(_wallet_out(wallet))


# ------------------------------------------------------------------ payees
class PayeeView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = PayeeSerializer

    def get(self, request):
        payees = Payee.objects.all().order_by("name")
        return Response(PayeeSerializer(payees, many=True).data)

    def post(self, request):
        s = PayeeCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        default_category = None
        if v.get("default_category_id"):
            default_category = Category.objects.filter(id=v["default_category_id"]).first()
            if default_category is None:
                return Response({"detail": "default_category not found"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            payee = payee_service.create_payee(name=v["name"], default_category=default_category)
        except PayeeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(PayeeSerializer(payee).data, status=status.HTTP_201_CREATED)


# ------------------------------------------------------------------ tags
class TagView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = TagSerializer

    def get(self, request):
        tags = Tag.objects.all().order_by("name")
        return Response(TagSerializer(tags, many=True).data)

    def post(self, request):
        s = TagCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            tag = tag_service.create_tag(**v)
        except TagError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(TagSerializer(tag).data, status=status.HTTP_201_CREATED)


class ReconciliationView(TenantScopedAPIView, APIView):
    """Where an account stands against a statement.

    Pass `statement_balance_minor` to get the difference — the number the user
    is driving to zero. Without it the response still reports reconciled vs
    uncleared, which is useful on its own.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="account_reconciliation")
    def get(self, request, account_id):
        account = _visible_accounts().filter(id=account_id).first()
        if account is None:
            return Response({"detail": "Account not found."}, status=status.HTTP_404_NOT_FOUND)

        raw = request.query_params.get("statement_balance_minor")
        statement = None
        if raw not in (None, ""):
            try:
                statement = int(raw)
            except ValueError:
                return Response(
                    {"statement_balance_minor": ["Expected an integer in minor units."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        summary = reconciliation.reconciliation_summary(account=account, statement_balance_minor=statement)
        uncleared = reconciliation.uncleared_transactions(account=account)[:200]
        return Response(
            {
                **asdict(summary),
                "is_balanced": summary.is_balanced,
                "uncleared": [
                    {
                        "id": str(t.id),
                        "occurred_at": t.occurred_at,
                        "amount_minor": t.amount_minor,
                        "currency": t.currency,
                        "memo": t.memo,
                        "category": t.category.name if t.category_id else None,
                    }
                    for t in uncleared
                ],
            }
        )


class ReconcileMarkView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Confirm (or un-confirm) transactions against a statement.

    Takes a list because the natural unit of the task is "everything I just
    ticked", not one row per request.
    """

    permission_classes = [IsTenantMember]
    serializer_class = ReconcileSerializer

    @extend_schema(operation_id="transactions_reconcile")
    def post(self, request):
        payload = ReconcileSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ids = payload.validated_data["transaction_ids"]

        rows = list(Transaction.objects.filter(id__in=ids))
        if len(rows) != len(set(ids)):
            return Response(
                {"transaction_ids": ["One or more transactions were not found."]},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            count = reconciliation.set_reconciled(
                transactions=rows,
                reconciled=payload.validated_data["reconciled"],
                actor_id=request.user.id,
            )
        except reconciliation.ReconciliationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response({"updated": count})


class TagDetailView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Rename or remove a tag. Tags were previously create-only."""

    permission_classes = [IsTenantMember]
    serializer_class = TagCreateSerializer

    def _get(self, tag_id):
        return Tag.objects.filter(id=tag_id).first()

    def patch(self, request, tag_id):
        tag = self._get(tag_id)
        if tag is None:
            return Response({"detail": "Tag not found."}, status=status.HTTP_404_NOT_FOUND)
        payload = TagCreateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        try:
            tag = tag_service.update_tag(tag=tag, **payload.validated_data)
        except TagError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(TagSerializer(tag).data)

    def delete(self, request, tag_id):
        tag = self._get(tag_id)
        if tag is not None:
            tag_service.delete_tag(tag=tag)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TransactionTagsView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = SetTransactionTagsSerializer

    def put(self, request, txn_id):
        txn = Transaction.objects.filter(id=txn_id).first()
        if txn is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = SetTransactionTagsSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        tag_ids = s.validated_data["tag_ids"]
        tags = list(Tag.objects.filter(id__in=tag_ids))
        if len(tags) != len(set(tag_ids)):
            return Response({"detail": "one or more tags not found"}, status=status.HTTP_400_BAD_REQUEST)
        tags = tag_service.set_transaction_tags(txn=txn, tags=tags)
        return Response(TagSerializer(tags, many=True).data)


# ------------------------------------------------------------------ attachments
class AttachmentUploadRequestView(TenantScopedAPIView, APIView):
    """Step 1 of the upload flow: request a presigned PUT URL. See
    `apps.finance.attachments` for the full lifecycle rationale."""

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = AttachmentRequestSerializer

    def post(self, request, txn_id):
        txn = Transaction.objects.filter(id=txn_id).first()
        if txn is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = AttachmentRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            attachment, upload_url = attachment_service.request_attachment_upload(txn=txn, **s.validated_data)
        except AttachmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(
            {**AttachmentSerializer(attachment).data, "upload_url": upload_url},
            status=status.HTTP_201_CREATED,
        )


class AttachmentConfirmView(TenantScopedAPIView, APIView):
    """Step 2: the client confirms once its direct upload to object storage
    succeeds."""

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = AttachmentConfirmSerializer

    def post(self, request, attachment_id):
        attachment = Attachment.objects.filter(id=attachment_id).first()
        if attachment is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = AttachmentConfirmSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        attachment = attachment_service.confirm_attachment_upload(attachment=attachment, **s.validated_data)
        return Response(AttachmentSerializer(attachment).data)


class TransactionAttachmentsView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = AttachmentSerializer

    def get(self, request, txn_id):
        attachments = Attachment.objects.filter(transaction_id=txn_id).order_by("-created_at")
        return Response(AttachmentSerializer(attachments, many=True).data)


class AttachmentUploadView(TenantScopedAPIView, APIView):
    """Direct server-side upload — the fallback for backends that can't presign
    (local dev / tests). The client POSTs the bytes here and we stream them to
    default_storage and mark the attachment UPLOADED. In production the client
    PUTs straight to S3 via the presigned URL and never reaches this view."""

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = AttachmentSerializer

    def post(self, request, attachment_id):
        attachment = Attachment.objects.filter(id=attachment_id).first()
        if attachment is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        upload = request.FILES.get("file")
        data = upload.read() if upload is not None else request.body
        try:
            attachment = attachment_service.store_attachment_bytes(attachment=attachment, data=data)
        except AttachmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(AttachmentSerializer(attachment).data)


class AttachmentDownloadView(TenantScopedAPIView, APIView):
    """Fetch a stored receipt. Redirects to a short-lived presigned GET URL when
    the backend supports it (S3 — keeps bytes off the app server); otherwise
    streams the file directly (local dev / tests)."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER

    def get(self, request, attachment_id):
        attachment = Attachment.objects.filter(id=attachment_id).first()
        if attachment is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        presigned = attachment_service.presigned_download_url(attachment=attachment)
        if presigned:
            return HttpResponseRedirect(presigned)

        try:
            fileobj, content_type = attachment_service.open_attachment(attachment=attachment)
        except AttachmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        response = FileResponse(fileobj, content_type=content_type or "application/octet-stream")
        response["Content-Disposition"] = "inline"
        return response


# ------------------------------------------------------------------ splits
class TransactionSplitView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = TransactionSplitSerializer

    @extend_schema(request=TransactionSplitSerializer)
    def post(self, request, txn_id):
        txn = Transaction.objects.filter(id=txn_id).first()
        if txn is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = TransactionSplitSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        parts = []
        for part in s.validated_data["parts"]:
            category = Category.objects.filter(id=part["category_id"]).first()
            if category is None:
                return Response(
                    {"detail": f"category {part['category_id']} not found"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            parts.append(
                services.SplitPart(
                    category=category, amount_minor=part["amount_minor"], memo=part.get("memo", "")
                )
            )
        try:
            created = services.split_transaction(txn=txn, parts=parts)
        except services.FinanceError as exc:
            return _finance_error(exc)
        return Response([_txn_out(t) for t in created], status=status.HTTP_201_CREATED)


# ------------------------------------------------------------------ bills
def _bill_out(bill) -> dict:
    return {
        "id": bill.id,
        "name": bill.name,
        "amount_minor": bill.amount_minor,
        "currency": bill.currency,
        "due_on": bill.due_on,
        "status": bill.status,
        "payee_id": bill.payee_id,
        "category_id": bill.category_id,
        "recurrence_frequency": bill.recurrence_frequency,
        "autopay_account_id": bill.autopay_account_id,
        "paid_at": bill.paid_at,
        "notes": bill.notes,
    }


class BillView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = BillCreateSerializer

    def get(self, request):

        status_filter = request.query_params.get("status")
        upcoming = request.query_params.get("upcoming")
        if upcoming:
            within = int(upcoming) if upcoming.isdigit() else 30
            rows = bills_service.upcoming_bills(within_days=within)
            return Response([{**_bill_out(ub.bill), "days_until_due": ub.days_until_due} for ub in rows])
        qs = bills_service.list_bills(status=status_filter)
        return Response([_bill_out(b) for b in qs])

    def post(self, request):
        s = BillCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        payee = Payee.objects.filter(id=v["payee_id"]).first() if v.get("payee_id") else None
        category = Category.objects.filter(id=v["category_id"]).first() if v.get("category_id") else None
        autopay = (
            _visible_accounts().filter(id=v["autopay_account_id"]).first()
            if v.get("autopay_account_id")
            else None
        )
        try:
            bill = bills_service.create_bill(
                name=v["name"],
                amount_minor=v["amount_minor"],
                currency=v["currency"].upper(),
                due_on=v["due_on"],
                payee=payee,
                category=category,
                recurrence_frequency=v.get("recurrence_frequency", ""),
                recurrence_interval=v.get("recurrence_interval", 1),
                autopay_account=autopay,
                notes=v.get("notes", ""),
            )
        except bills_service.BillError as exc:
            return _finance_error(exc)
        return Response(_bill_out(bill), status=status.HTTP_201_CREATED)


class BillDetailView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = None

    @extend_schema(operation_id="finance_bill_retrieve")
    def get(self, request, bill_id):
        from ..models import Bill

        bill = Bill.objects.filter(id=bill_id).first()
        if bill is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(_bill_out(bill))

    def delete(self, request, bill_id):
        from ..models import Bill

        bill = Bill.objects.filter(id=bill_id).first()
        if bill is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        bills_service.cancel_bill(bill=bill)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BillPayView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = BillPaySerializer

    @extend_schema(request=BillPaySerializer)
    def post(self, request, bill_id):
        from ..models import Bill

        bill = Bill.objects.filter(id=bill_id).first()
        if bill is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = BillPaySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        from_account = (
            _visible_accounts().filter(id=v["from_account_id"]).first() if v.get("from_account_id") else None
        )
        try:
            bill, txn = bills_service.mark_bill_paid(
                bill=bill,
                from_account=from_account,
                amount_minor=v.get("amount_minor"),
                occurred_at=v.get("occurred_at"),
                record_expense=v.get("record_expense", True),
            )
        except services.FinanceError as exc:
            return _finance_error(exc)
        return Response({"bill": _bill_out(bill), "settling_transaction_id": txn.id if txn else None})


class BillImportView(TenantScopedAPIView, APIView):
    """Bulk-create bills from an uploaded .xlsx sheet — a human filling in a
    spreadsheet, not a bank export (see import_xlsx.py). MEMBER — it creates
    money obligations."""

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = None

    @extend_schema(operation_id="bill_import_template")
    def get(self, request):
        from django.http import HttpResponse

        from .. import import_xlsx

        response = HttpResponse(
            import_xlsx.bills_template_xlsx(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="ledgerflow-bills-template.xlsx"'
        return response

    def post(self, request):
        from .. import import_xlsx

        upload = request.FILES.get("file")
        if upload is None:
            return Response(
                {"detail": "Attach the .xlsx file as 'file'."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            result = import_xlsx.import_bills_xlsx(file_bytes=upload.read())
        except import_xlsx.ImportError_ as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result.as_dict(), status=status.HTTP_201_CREATED)


class RecurringImportView(TenantScopedAPIView, APIView):
    """Bulk-create recurring schedules from an uploaded .xlsx sheet. MEMBER —
    it creates schedules that post real transactions going forward."""

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = None

    @extend_schema(operation_id="recurring_import_template")
    def get(self, request):
        from django.http import HttpResponse

        from .. import import_xlsx

        response = HttpResponse(
            import_xlsx.recurring_template_xlsx(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="ledgerflow-recurring-template.xlsx"'
        return response

    def post(self, request):
        from .. import import_xlsx

        upload = request.FILES.get("file")
        if upload is None:
            return Response(
                {"detail": "Attach the .xlsx file as 'file'."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            result = import_xlsx.import_recurring_xlsx(file_bytes=upload.read())
        except import_xlsx.ImportError_ as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result.as_dict(), status=status.HTTP_201_CREATED)


# ------------------------------------------------------------------ export
class TransactionExportView(TenantScopedAPIView, APIView):
    """CSV export of transactions honoring the same filters as the list.

    Data portability is close to mandatory for a product holding someone's
    financial history. Streams so a large account doesn't buffer the whole
    export in memory. VIEWER can export — it's their data to read.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    def get(self, request):
        import csv

        from django.http import StreamingHttpResponse

        account_id = request.query_params.get("account_id")
        account = _visible_accounts().filter(id=account_id).first() if account_id else None
        # Evaluate under the request's tenant/RLS context now (the generator
        # below would otherwise lazily hit the DB after context teardown).
        rows = list(
            selectors.list_transactions(
                financial_account=account, filters=_parse_txn_filters(request)
            ).values(
                "id",
                "occurred_at",
                "amount_minor",
                "currency",
                "status",
                "source",
                "category__name",
                "payee__name",
                "memo",
            )
        )

        class _Echo:
            def write(self, value):
                return value

        writer = csv.writer(_Echo())
        header = [
            "id",
            "occurred_at",
            "amount",
            "amount_minor",
            "currency",
            "status",
            "source",
            "category",
            "payee",
            "memo",
        ]

        def _major(amount_minor: int, currency: str) -> str:
            from apps.fx.currencies import get_currency

            meta = get_currency(currency)
            digits = meta.digits if meta else 2
            scale = 10**digits
            return f"{amount_minor / scale:.{digits}f}"

        def _stream():
            yield writer.writerow(header)
            for r in rows:
                yield writer.writerow(
                    [
                        r["id"],
                        r["occurred_at"].isoformat() if r["occurred_at"] else "",
                        _major(r["amount_minor"], r["currency"]),
                        r["amount_minor"],
                        r["currency"],
                        r["status"],
                        r["source"],
                        r["category__name"] or "",
                        r["payee__name"] or "",
                        r["memo"],
                    ]
                )

        response = StreamingHttpResponse(_stream(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="transactions.csv"'
        return response


class BillExportView(TenantScopedAPIView, APIView):
    """CSV export of bills — same portability rationale as TransactionExportView."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    def get(self, request):
        import csv

        from django.http import StreamingHttpResponse

        status_filter = request.query_params.get("status")
        rows = list(bills_service.list_bills(status=status_filter).select_related("payee", "category"))

        class _Echo:
            def write(self, value):
                return value

        writer = csv.writer(_Echo())
        header = ["id", "name", "amount_minor", "currency", "due_on", "status", "payee", "category", "notes"]

        def _stream():
            yield writer.writerow(header)
            for b in rows:
                yield writer.writerow(
                    [
                        b.id,
                        b.name,
                        b.amount_minor,
                        b.currency,
                        b.due_on.isoformat() if b.due_on else "",
                        b.status,
                        b.payee.name if b.payee_id else "",
                        b.category.name if b.category_id else "",
                        b.notes,
                    ]
                )

        response = StreamingHttpResponse(_stream(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="bills.csv"'
        return response


class RecurringExportView(TenantScopedAPIView, APIView):
    """CSV export of recurring schedules — same portability rationale as
    TransactionExportView."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    def get(self, request):
        import csv

        from django.http import StreamingHttpResponse

        rows = list(
            RecurringTransaction.objects.filter(is_active=True)
            .select_related("category", "payee", "financial_account", "counter_account")
            .order_by("next_run_on")
        )

        class _Echo:
            def write(self, value):
                return value

        writer = csv.writer(_Echo())
        header = [
            "id",
            "txn_type",
            "account",
            "counter_account",
            "category",
            "payee",
            "amount_minor",
            "currency",
            "frequency",
            "interval",
            "starts_on",
            "ends_on",
            "next_run_on",
            "memo",
        ]

        def _stream():
            yield writer.writerow(header)
            for r in rows:
                yield writer.writerow(
                    [
                        r.id,
                        r.txn_type,
                        r.financial_account.name,
                        r.counter_account.name if r.counter_account_id else "",
                        r.category.name if r.category_id else "",
                        r.payee.name if r.payee_id else "",
                        r.amount_minor,
                        r.currency,
                        r.frequency,
                        r.interval,
                        r.starts_on.isoformat() if r.starts_on else "",
                        r.ends_on.isoformat() if r.ends_on else "",
                        r.next_run_on.isoformat() if r.next_run_on else "",
                        r.memo,
                    ]
                )

        response = StreamingHttpResponse(_stream(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="recurring.csv"'
        return response


# ------------------------------------------------------------------ import
class TransactionImportView(TenantScopedAPIView, APIView):
    """Import transactions from an uploaded CSV into an account.

    Accepts multipart file upload (`file`) or a raw `content` string field, plus
    `account_id` and optional `default_category_id`. Idempotent: re-importing
    the same file skips already-seen rows. MEMBER — it writes money movements.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = None

    @extend_schema(operation_id="transaction_import_template")
    def get(self, request):
        """The blank template, as a CSV download.

        A file format described only in prose is one people get wrong on the
        first try and then blame the importer for. Served from the same module
        that parses it, so the columns handed out cannot drift from the columns
        accepted.
        """
        from django.http import HttpResponse

        from .. import import_csv

        response = HttpResponse(import_csv.template_csv(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="ledgerflow-import-template.csv"'
        return response

    def post(self, request):
        from .. import import_csv

        account_id = request.data.get("account_id")
        account = _visible_accounts().filter(id=account_id).first() if account_id else None
        if account is None:
            return Response(
                {"detail": "account_id is required and must exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        default_category = None
        if request.data.get("default_category_id"):
            default_category = Category.objects.filter(id=request.data["default_category_id"]).first()

        upload = request.FILES.get("file")
        content = upload.read().decode("utf-8-sig") if upload is not None else request.data.get("content")
        if not content:
            return Response(
                {"detail": "provide a CSV file upload ('file') or 'content' string"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = import_csv.import_transactions_csv(
                financial_account=account,
                file_content=content,
                default_category=default_category,
            )
        except import_csv.ImportError_ as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result.as_dict(), status=status.HTTP_201_CREATED)


def _parse_iso_date(raw):
    """ "" or None -> None; 'YYYY-MM-DD' -> date. Anything else raises.

    Blank is "no bound", which is different from a bad value: an empty form
    field must not be read as 1 January of year one.
    """
    from datetime import date as _date

    if raw in (None, ""):
        return None
    if isinstance(raw, _date):
        return raw
    return _date.fromisoformat(str(raw).strip())


class MpesaImportView(TenantScopedAPIView, APIView):
    """Import a Safaricom M-Pesa PDF statement.

    Separate from the CSV importer rather than a mode of it, because almost
    nothing is shared: the file is an encrypted PDF, the identity of a row is
    a composite key, and Fuliza rows have to become debt rather than income.

    Two steps, deliberately. `?preview=1` parses and describes the file without
    writing anything — uploading three months of your financial life is not a
    step to take on trust, and the preview is what makes the reconciliation
    check visible *before* 866 rows land in the books. POST without it imports.

    The password is read from the request, used to decrypt, and dropped. It is
    never stored, never logged, and never echoed back in a response.

    MEMBER — it writes money movements.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.MEMBER
    serializer_class = None

    @extend_schema(operation_id="mpesa_import")
    def post(self, request):
        from ..import_mpesa import MpesaParseError, parse_statement
        from ..import_mpesa_service import preview_statement

        upload = request.FILES.get("file")
        if upload is None:
            return Response(
                {"detail": "Attach the M-Pesa statement PDF as 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Safaricom statements run to a few hundred KB; a cap keeps a hostile
        # or mistaken upload from becoming a memory problem, since parsing
        # holds the whole document.
        if upload.size and upload.size > 20 * 1024 * 1024:
            return Response(
                {"detail": "That file is larger than 20MB — it is unlikely to be a statement."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        password = request.data.get("password", "") or ""
        file_bytes = upload.read()

        preview = str(request.query_params.get("preview", "")).lower() in {"1", "true", "yes"}
        try:
            if preview:
                return Response(
                    preview_statement(file_bytes=file_bytes, password=password),
                    status=status.HTTP_200_OK,
                )

            account_id = request.data.get("account_id")
            account = _visible_accounts().filter(id=account_id).first() if account_id else None
            if account is None:
                return Response(
                    {"detail": "account_id is required and must exist."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # A window is the user's protection against double-counting a
            # period they already entered by hand: an imported row carries an
            # external_id and a typed one never will, so the two can never be
            # reconciled automatically and both would survive.
            try:
                from_date = _parse_iso_date(request.data.get("from_date"))
                to_date = _parse_iso_date(request.data.get("to_date"))
            except ValueError:
                return Response(
                    {"detail": "from_date and to_date must be in YYYY-MM-DD form."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if from_date and to_date and from_date > to_date:
                return Response(
                    {"detail": "from_date is after to_date — that window contains nothing."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Parsed here, posted in a task. A real statement is 866 rows and
            # ~25 seconds of double-entry posting, against gunicorn's 30s
            # timeout — the request was being killed mid-import and returning a
            # 500 for work that was actually succeeding. Parsing costs ~6s,
            # comfortably inside the timeout, and keeping it here means the
            # statement password is used and dropped in the web process rather
            # than travelling to the queue.
            from apps.common.tenant_context import get_current_actor_id, require_current_tenant_id
            from apps.finance.tasks import import_mpesa_statement_task

            statement = parse_statement(file_bytes, password)
            payload = {
                "rows": [
                    {
                        "receipt": r.receipt,
                        "completed_at": r.completed_at.isoformat(),
                        "details": r.details,
                        "status": r.status,
                        "amount_minor": r.amount_minor,
                        "balance_minor": r.balance_minor,
                        "kind": str(r.kind),
                        "counterparty": r.counterparty,
                    }
                    for r in statement.rows
                ],
                "customer_name": statement.customer_name,
                "mobile_number": statement.mobile_number,
                "period_start": statement.period_start,
                "period_end": statement.period_end,
                "declared_paid_in_minor": statement.declared_paid_in_minor,
                "declared_withdrawn_minor": statement.declared_withdrawn_minor,
                "from_date": from_date.isoformat() if from_date else None,
                "to_date": to_date.isoformat() if to_date else None,
                "actor_id": str(get_current_actor_id() or ""),
            }

            task = import_mpesa_statement_task.delay(
                str(require_current_tenant_id()), str(account.id), payload
            )
            return Response(
                {
                    "queued": True,
                    "task_id": task.id,
                    "rows_found": len(statement.rows),
                    "reconciles": statement.reconciles,
                    "discrepancy": statement.discrepancy(),
                    "detail": (
                        f"Importing {len(statement.rows)} transactions in the background. "
                        "They will appear in your ledger shortly."
                    ),
                },
                status=status.HTTP_202_ACCEPTED,
            )
        except MpesaParseError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        finally:
            # Not security theatre: `request.data` can outlive this frame in
            # error reporting and middleware, and this is a live credential for
            # somebody's bank statement.
            password = ""
            del file_bytes


class CashflowStatementView(TenantScopedAPIView, APIView):
    """Monthly liquidity statement: inflow/outflow/net + ending liquid balance."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    def get(self, request):
        try:
            months = min(24, max(1, int(request.query_params.get("months", 6))))
        except ValueError:
            months = 6
        stmt = selectors.cashflow_statement(months=months)
        if stmt is None:
            return Response({"currency": None, "liquid_balance_minor": 0, "rows": []})
        return Response(
            {
                "currency": stmt.currency,
                "liquid_balance_minor": stmt.liquid_balance_minor,
                "rows": [
                    {
                        "period_start": r.period_start.isoformat(),
                        "inflow_minor": r.inflow_minor,
                        "outflow_minor": r.outflow_minor,
                        "net_minor": r.net_minor,
                        "ending_balance_minor": r.ending_balance_minor,
                    }
                    for r in stmt.rows
                ],
            }
        )


class NetWorthBaseView(TenantScopedAPIView, APIView):
    """Net worth consolidated into the workspace base currency via FX."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    def get(self, request):
        from apps.tenancy.models import Tenant

        base = (
            Tenant.objects.filter(id=request.tenant_id).values_list("base_currency", flat=True).first()
            or "USD"
        )
        return Response(selectors.net_worth_in_base(base))


# ------------------------------------------------------------------ cash flow calendar
def _event_out(event) -> dict:
    return {
        "occurs_on": event.occurs_on,
        # Signed: positive is money in. The client renders colour from the sign
        # and the icon from `source`, so neither has to re-derive direction.
        "amount_minor": event.amount_minor,
        "description": event.description,
        "source": event.source,
        "currency": event.currency,
        "account_id": event.account_id,
        "account_name": event.account_name,
        "category_name": event.category_name,
        "is_overdue": event.is_overdue,
        "bill_id": event.bill_id,
        "recurring_id": event.recurring_id,
    }


def _day_out(day) -> dict:
    return {
        "day": day.day,
        "opening_minor": day.opening_minor,
        "closing_minor": day.closing_minor,
        "inflow_minor": day.inflow_minor,
        "outflow_minor": day.outflow_minor,
        "net_minor": day.net_minor,
        "is_negative": day.is_negative,
        # Where the balance lands once ordinary unscheduled spending is
        # included. Null — not equal to `closing_minor` — when there is too
        # little history to measure it.
        "expected_minor": day.expected_minor,
        "expected_low_minor": day.expected_low_minor,
        "expected_high_minor": day.expected_high_minor,
        "events": [_event_out(e) for e in day.events],
    }


class CashflowCalendarView(TenantScopedAPIView, APIView):
    """Day-by-day projected liquid balance.

    Single-currency by design, matching net-worth and the cashflow statement:
    the response names the currency it projected rather than silently summing
    across them. Returns 204 when the workspace holds no liquid account, since
    an empty calendar would imply a zero balance rather than an absence.
    """

    permission_classes = [IsTenantMember, require_feature(PlanFeature.CASHFLOW_FORECAST)]
    required_role = Role.VIEWER
    serializer_class = CashflowCalendarQuerySerializer

    @extend_schema(operation_id="cashflow_calendar", parameters=[CashflowCalendarQuerySerializer])
    def get(self, request):
        q = CashflowCalendarQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        v = q.validated_data

        calendar = calendar_selectors.cashflow_calendar(
            start=v.get("start"),
            days=v.get("days") or calendar_selectors.DEFAULT_HORIZON_DAYS,
            currency=v.get("currency"),
        )
        if calendar is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response(
            {
                "currency": calendar.currency,
                "start": calendar.start,
                "end": calendar.end,
                "opening_balance_minor": calendar.opening_balance_minor,
                "closing_balance_minor": calendar.closing_balance_minor,
                # The trough, not the closing balance, is what tells a user
                # whether they survive the window.
                "lowest_balance_minor": calendar.lowest_balance_minor,
                "safe_to_spend_minor": calendar.safe_to_spend_minor,
                "safe_to_spend_basis": calendar.safe_to_spend_basis,
                "lowest_balance_on": calendar.lowest_balance_on,
                "first_negative_on": calendar.first_negative_on,
                "negative_day_count": calendar.negative_day_count,
                # How the band was measured, so the UI can state its basis
                # rather than drawing an unexplained shaded region.
                "everyday": (
                    None
                    if calendar.everyday is None
                    else {
                        "mean_minor": calendar.everyday.mean_minor,
                        "stdev_minor": calendar.everyday.stdev_minor,
                        "median_minor": calendar.everyday.median_minor,
                        "observed_days": calendar.everyday.observed_days,
                        "active_days": calendar.everyday.active_days,
                    }
                ),
                "days": [_day_out(d) for d in calendar.days],
            }
        )


class CashflowDayView(TenantScopedAPIView, APIView):
    """One day's projected detail, with the running balance it inherits."""

    permission_classes = [IsTenantMember, require_feature(PlanFeature.CASHFLOW_FORECAST)]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="cashflow_calendar_day")
    def get(self, request, day):
        # The path captures a string; parse it here so a malformed date is a
        # clean 400 rather than a 500 deep inside the projection.
        try:
            target = date.fromisoformat(day)
        except (TypeError, ValueError):
            return Response(
                {"detail": "Expected a date in YYYY-MM-DD format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        detail = calendar_selectors.cashflow_day(day=target)
        if detail is None:
            # Either the day is in the past (read the ledger instead) or there's
            # nothing liquid to project.
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(_day_out(detail))


# ------------------------------------------------------------------ quick add
class QuickAddSerializer(serializers.Serializer):
    amount_minor = serializers.IntegerField(min_value=1)
    merchant = serializers.CharField(max_length=160)
    is_income = serializers.BooleanField(required=False, default=False)
    financial_account_id = serializers.UUIDField(required=False, allow_null=True)
    category_id = serializers.UUIDField(required=False, allow_null=True)
    occurred_at = serializers.DateTimeField(required=False, allow_null=True)
    #: Client-generated, and resent unchanged on every retry of the same
    #: entry — what makes it safe for the offline queue to replay a submission
    #: whose response never arrived without risking a double post.
    idempotency_key = serializers.CharField(max_length=200, required=False, allow_blank=True)


class QuickAddView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Post a transaction from the minimum viable input: an amount and who it
    was to. See `apps.finance.quick_add` for what's inferred and why."""

    permission_classes = [IsTenantMember]
    serializer_class = QuickAddSerializer

    @extend_schema(operation_id="finance_quick_add", request=QuickAddSerializer)
    def post(self, request):
        from .. import quick_add as quick_add_service
        from ..models import Category

        s = QuickAddSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        account = None
        if v.get("financial_account_id"):
            account = _visible_accounts().filter(id=v["financial_account_id"]).first()
        category = None
        if v.get("category_id"):
            category = Category.objects.filter(id=v["category_id"]).first()

        try:
            result = quick_add_service.quick_add(
                amount_minor=v["amount_minor"],
                merchant=v["merchant"],
                is_income=v.get("is_income", False),
                financial_account=account,
                category=category,
                occurred_at=v.get("occurred_at"),
                idempotency_key=v.get("idempotency_key") or None,
            )
        except quick_add_service.QuickAddError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        txn = result.transaction
        return Response(
            {
                "transaction_id": txn.id,
                "amount_minor": txn.amount_minor,
                "financial_account_id": txn.financial_account_id,
                "financial_account_name": txn.financial_account.name,
                "category_id": txn.category_id,
                "category_name": txn.category.name if txn.category else None,
                "payee_name": txn.payee.name if txn.payee else None,
                "occurred_at": txn.occurred_at,
                # Surfaced explicitly, never silent — a user who typed one word
                # and an amount deserves to see what was guessed on their
                # behalf before it settles into their history.
                "account_was_inferred": result.account_was_inferred,
                "category_was_inferred": result.category_was_inferred,
                "category_confidence": result.category_confidence,
            },
            status=status.HTTP_201_CREATED,
        )


class RecentMerchantsView(TenantScopedAPIView, APIView):
    """Recently-used payee names, for a Quick Add autocomplete."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="finance_recent_merchants")
    def get(self, request):
        from .. import quick_add as quick_add_service

        return Response(quick_add_service.recent_merchants())
