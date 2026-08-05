from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.plan_catalogue import PlanFeature
from apps.common.api_base import TenantScopedAPIView, WriteRequiresMemberMixin, require_feature
from apps.finance.models import FinancialAccount
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import selectors, services
from ..models import InvestmentTransaction, Security
from .serializers import (
    DividendSerializer,
    PriceSerializer,
    RedemptionScheduleSerializer,
    RedemptionSerializer,
    SecurityCreateSerializer,
    SecurityTermsSerializer,
    SecurityUpdateSerializer,
    SplitSerializer,
    TradeSerializer,
)


def _security_out(security: Security) -> dict:
    return {
        "id": security.id,
        "symbol": security.symbol,
        "name": security.name,
        "asset_class": security.asset_class,
        "sector": security.sector,
        "currency": security.currency,
        "exchange": security.exchange,
    }


def _valuation_out(v) -> dict:
    return {
        "holding_id": v.holding_id,
        "account_id": v.account_id,
        "account_name": v.account_name,
        "security_id": v.security_id,
        "symbol": v.symbol,
        "security_name": v.security_name,
        "asset_class": v.asset_class,
        "sector": v.sector,
        "currency": v.currency,
        "quantity": str(v.quantity),
        "cost_basis_minor": v.cost_basis_minor,
        # Null, not zero, when unpriced — the client must render the absence.
        "price_minor": v.price_minor,
        # How old that price is. Quotes are entered by hand, so without this
        # the client cannot tell a valuation taken this morning from one taken
        # in March, and shows both as what the holding is worth today.
        "priced_as_of": v.priced_as_of,
        "market_value_minor": v.market_value_minor,
        "unrealized_gain_minor": v.unrealized_gain_minor,
        "unrealized_gain_pct": v.unrealized_gain_pct,
        "is_priced": v.is_priced,
    }


def _resolve(model, pk):
    return model.objects.filter(id=pk).first()


class SecurityView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    serializer_class = SecurityCreateSerializer

    @extend_schema(operation_id="securities_list")
    def get(self, request):
        return Response([_security_out(s) for s in Security.objects.order_by("symbol")])

    def post(self, request):
        s = SecurityCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            security = services.create_security(
                symbol=v["symbol"],
                name=v.get("name") or v["symbol"],
                asset_class=v["asset_class"],
                currency=v["currency"],
                sector=v.get("sector", ""),
                exchange=v.get("exchange", ""),
            )
        except services.InvestmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_security_out(security), status=status.HTTP_201_CREATED)


class SecurityDetailView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Correct or remove a tracked security.

    Without this a mistyped ticker was permanent — and blocked creating the
    right one, because the duplicate check is case-insensitive on symbol.
    """

    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    serializer_class = SecurityUpdateSerializer

    def _get(self, security_id):
        return Security.objects.filter(id=security_id).first()

    @extend_schema(operation_id="security_update")
    def patch(self, request, security_id):
        security = self._get(security_id)
        if security is None:
            return Response({"detail": "Security not found."}, status=status.HTTP_404_NOT_FOUND)
        payload = SecurityUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        try:
            security = services.update_security(security=security, **payload.validated_data)
        except services.InvestmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_security_out(security))

    @extend_schema(operation_id="security_delete")
    def delete(self, request, security_id):
        security = self._get(security_id)
        if security is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        try:
            services.delete_security(security=security)
        except services.InvestmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(status=status.HTTP_204_NO_CONTENT)


class HoldingsView(TenantScopedAPIView, APIView):
    """Every open position, valued at the latest available price."""

    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="holdings_list")
    def get(self, request):
        return Response([_valuation_out(v) for v in selectors.holding_valuations()])


class PortfolioView(TenantScopedAPIView, APIView):
    """Headline figures plus allocation breakdowns.

    Returns 204 when there are no holdings: an all-zero portfolio reads as one
    that lost everything rather than one that doesn't exist.
    """

    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="portfolio_summary")
    def get(self, request):
        summary = selectors.portfolio_summary()
        if summary is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        def slices(items):
            return [
                {"label": s.label, "market_value_minor": s.market_value_minor, "percent": s.percent}
                for s in items
            ]

        return Response(
            {
                "currency": summary.currency,
                "cost_basis_minor": summary.cost_basis_minor,
                "market_value_minor": summary.market_value_minor,
                "unrealized_gain_minor": summary.unrealized_gain_minor,
                "unrealized_gain_pct": summary.unrealized_gain_pct,
                "realized_gain_minor": summary.realized_gain_minor,
                "dividend_income_minor": summary.dividend_income_minor,
                "total_return_minor": summary.total_return_minor,
                "holding_count": summary.holding_count,
                "unpriced_count": summary.unpriced_count,
                # Oldest quote behind the total, not the newest: a sum is only
                # as current as its stalest input.
                "priced_as_of": summary.priced_as_of,
                "stale_count": summary.stale_count,
                "asset_allocation": slices(selectors.asset_allocation()),
                "sector_allocation": slices(selectors.sector_allocation()),
                "account_allocation": slices(selectors.account_allocation()),
            }
        )


class PortfolioHistoryView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="portfolio_history")
    def get(self, request):
        months = min(int(request.query_params.get("months", 12)), 60)
        return Response(
            [
                {
                    "as_of": p.as_of,
                    "market_value_minor": p.market_value_minor,
                    "cost_basis_minor": p.cost_basis_minor,
                    "unrealized_gain_minor": p.unrealized_gain_minor,
                }
                for p in selectors.valuation_history(months=months)
            ]
        )


class TradeView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Buy or sell. The action is the final path segment."""

    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    serializer_class = TradeSerializer

    @extend_schema(operation_id="investment_trade", request=TradeSerializer)
    def post(self, request, action):
        if action not in ("buy", "sell"):
            return Response({"detail": f"Unknown action {action!r}."}, status=400)
        s = TradeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        account = _resolve(FinancialAccount, v["financial_account_id"])
        security = _resolve(Security, v["security_id"])
        if account is None or security is None:
            return Response({"detail": "Account or security not found."}, status=404)
        cash = _resolve(FinancialAccount, v["cash_account_id"]) if v.get("cash_account_id") else None

        fn = services.buy if action == "buy" else services.sell
        try:
            txn = fn(
                financial_account=account,
                security=security,
                quantity=v["quantity"],
                amount_minor=v["amount_minor"],
                fee_minor=v.get("fee_minor", 0),
                occurred_on=v.get("occurred_on"),
                cash_account=cash,
                memo=v.get("memo", ""),
            )
        except services.InvestmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(
            {
                "id": txn.id,
                "txn_type": txn.txn_type,
                "quantity": str(txn.quantity),
                "amount_minor": txn.amount_minor,
                "fee_minor": txn.fee_minor,
                "realized_gain_minor": txn.realized_gain_minor,
                "occurred_on": txn.occurred_on,
            },
            status=status.HTTP_201_CREATED,
        )


class DividendView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    serializer_class = DividendSerializer

    def post(self, request):
        s = DividendSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        account = _resolve(FinancialAccount, v["financial_account_id"])
        security = _resolve(Security, v["security_id"])
        if account is None or security is None:
            return Response({"detail": "Account or security not found."}, status=404)
        try:
            txn = services.record_dividend(
                financial_account=account,
                security=security,
                amount_minor=v["amount_minor"],
                occurred_on=v.get("occurred_on"),
                cash_account=(
                    _resolve(FinancialAccount, v["cash_account_id"]) if v.get("cash_account_id") else None
                ),
                memo=v.get("memo", ""),
            )
        except services.InvestmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(
            {"id": txn.id, "amount_minor": txn.amount_minor, "occurred_on": txn.occurred_on},
            status=status.HTTP_201_CREATED,
        )


class InterestView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Record an interest payment from a holding — an MMF distribution, a bond
    coupon. Same shape as a dividend; a separate endpoint because the two are
    taxed and reported differently."""

    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    serializer_class = DividendSerializer

    def post(self, request):
        s = DividendSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        account = _resolve(FinancialAccount, v["financial_account_id"])
        security = _resolve(Security, v["security_id"])
        if account is None or security is None:
            return Response({"detail": "Account or security not found."}, status=404)
        try:
            txn = services.record_interest(
                financial_account=account,
                security=security,
                amount_minor=v["amount_minor"],
                occurred_on=v.get("occurred_on"),
                cash_account=(
                    _resolve(FinancialAccount, v["cash_account_id"]) if v.get("cash_account_id") else None
                ),
                memo=v.get("memo", ""),
            )
        except services.InvestmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(
            {"id": txn.id, "amount_minor": txn.amount_minor, "occurred_on": txn.occurred_on},
            status=status.HTTP_201_CREATED,
        )


def _income_out(v) -> dict:
    return {
        "security_id": v.security_id,
        "symbol": v.symbol,
        "name": v.name,
        "currency": v.currency,
        "income_kind": v.income_kind,
        "quantity": v.quantity,
        "coupon_rate_bp": v.coupon_rate_bp,
        "payment_frequency": v.payment_frequency,
        "matures_on": v.matures_on,
        "next_payment_on": v.next_payment_on,
        "next_payment_minor": v.next_payment_minor,
        "outstanding_principal_minor": v.outstanding_principal_minor,
        "received_minor": v.received_minor,
        "received_over_days": v.received_over_days,
        "realised_yield_bp": v.realised_yield_bp,
        # Travels with the figures so a client cannot re-derive it wrongly:
        # only a fixed coupon has a payment that may be stated in advance.
        "is_projectable": v.is_projectable,
    }


class SecurityTermsView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """The contract behind an income-producing security."""

    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    serializer_class = SecurityTermsSerializer

    @extend_schema(operation_id="security_terms_set")
    def put(self, request, security_id):
        security = _resolve(Security, security_id)
        if security is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = SecurityTermsSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            services.set_security_terms(security=security, **s.validated_data)
        except services.InvestmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RedemptionScheduleView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """The dates on which part of the principal comes back."""

    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    serializer_class = RedemptionScheduleSerializer

    @extend_schema(operation_id="redemption_schedule_set")
    def put(self, request, security_id):
        security = _resolve(Security, security_id)
        if security is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        s = RedemptionScheduleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        entries = [(e["on_date"], e["portion_bp"]) for e in s.validated_data["entries"]]
        try:
            services.set_redemption_schedule(security=security, entries=entries)
        except services.InvestmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RedemptionView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Record principal handed back — a partial redemption, or maturity."""

    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    serializer_class = RedemptionSerializer

    @extend_schema(operation_id="redemption_record")
    def post(self, request):
        s = RedemptionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        account = _resolve(FinancialAccount, v["financial_account_id"])
        security = _resolve(Security, v["security_id"])
        if account is None or security is None:
            return Response({"detail": "Account or security not found."}, status=404)
        try:
            txn = services.record_redemption(
                financial_account=account,
                security=security,
                amount_minor=v["amount_minor"],
                quantity=v.get("quantity"),
                occurred_on=v.get("occurred_on"),
                cash_account=(
                    _resolve(FinancialAccount, v["cash_account_id"]) if v.get("cash_account_id") else None
                ),
                memo=v.get("memo", ""),
            )
        except services.InvestmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(
            {"id": txn.id, "amount_minor": txn.amount_minor, "occurred_on": txn.occurred_on},
            status=status.HTTP_201_CREATED,
        )


class IncomeScheduleView(TenantScopedAPIView, APIView):
    """What the portfolio pays, and how certain each figure is.

    One endpoint for all three instrument shapes, because the client's question
    is the same for all of them — "what does this pay me?" — and the answer's
    *certainty* is a field rather than a different URL.
    """

    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="investment_income")
    def get(self, request):
        days = request.query_params.get("days")
        if days:
            try:
                rows = selectors.upcoming_income(days=int(days))
            except ValueError:
                return Response({"detail": "days must be a number"}, status=400)
        else:
            rows = selectors.income_views()
        return Response([_income_out(v) for v in rows])


class SplitView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    serializer_class = SplitSerializer

    def post(self, request):
        s = SplitSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        account = _resolve(FinancialAccount, v["financial_account_id"])
        security = _resolve(Security, v["security_id"])
        if account is None or security is None:
            return Response({"detail": "Account or security not found."}, status=404)
        try:
            txn = services.apply_split(
                financial_account=account,
                security=security,
                ratio=v["ratio"],
                occurred_on=v.get("occurred_on"),
            )
        except services.InvestmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response({"id": txn.id, "quantity": str(txn.quantity)}, status=status.HTTP_201_CREATED)


class PriceView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Manual price entry.

    The seam a market-data or broker integration plugs into: a sync job records
    quotes through this same service, and nothing else in the module changes.
    """

    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    serializer_class = PriceSerializer

    def post(self, request):
        s = PriceSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        security = _resolve(Security, v["security_id"])
        if security is None:
            return Response({"detail": "Security not found."}, status=404)
        try:
            quote = services.record_price(
                security=security,
                price_minor=v["price_minor"],
                as_of=v.get("as_of"),
                source=v.get("source", "manual"),
            )
        except services.InvestmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(
            {"id": quote.id, "price_minor": quote.price_minor, "as_of": quote.as_of},
            status=status.HTTP_201_CREATED,
        )


class InvestmentTransactionsView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="investment_transactions")
    def get(self, request):
        qs = InvestmentTransaction.objects.select_related("holding__security")[:100]
        return Response(
            [
                {
                    "id": t.id,
                    "txn_type": t.txn_type,
                    "symbol": t.holding.security.symbol,
                    "quantity": str(t.quantity),
                    "amount_minor": t.amount_minor,
                    "fee_minor": t.fee_minor,
                    "realized_gain_minor": t.realized_gain_minor,
                    "currency": t.currency,
                    "occurred_on": t.occurred_on,
                    "memo": t.memo,
                }
                for t in qs
            ]
        )


class DividendSummaryView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, require_feature(PlanFeature.INVESTMENTS)]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="dividend_summary")
    def get(self, request):
        summary = selectors.dividend_income(months=int(request.query_params.get("months", 12)))
        if summary is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(
            {
                "currency": summary.currency,
                "total_minor": summary.total_minor,
                "by_security": summary.by_security,
            }
        )
