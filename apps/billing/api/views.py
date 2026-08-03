from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api_base import TenantScopedAPIView, WriteRequiresMemberMixin
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import services
from ..models import PaymentMethod, Plan
from .serializers import (
    AddPaymentMethodSerializer,
    CancelSerializer,
    PaymentMethodSerializer,
    PaymentSerializer,
    PlanSerializer,
    SubscribeSerializer,
    SubscriptionSerializer,
)


class PlanListView(APIView):
    """Public catalog — anyone can see what's on offer (e.g. a pricing page)."""

    permission_classes = [AllowAny]
    serializer_class = PlanSerializer

    def get(self, request):
        currency = request.query_params.get("currency", "USD")
        plans = services.list_plans(currency=currency)
        return Response(PlanSerializer(plans, many=True).data)


class SubscriptionView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = SubscriptionSerializer

    def get(self, request):
        sub = services.get_subscription(tenant_id=request.tenant_id)
        if sub is None:
            return Response({"subscription": None})
        return Response(SubscriptionSerializer(sub).data)

    def post(self, request):
        # Subscribing / changing plan requires an admin or owner (billing action).
        s = SubscribeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        plan = Plan.objects.filter(id=s.validated_data["plan_id"], is_active=True).first()
        if plan is None:
            return Response({"detail": "Plan not found."}, status=status.HTTP_404_NOT_FOUND)
        payment_method = None
        pm_id = s.validated_data.get("payment_method_id")
        if pm_id:
            payment_method = PaymentMethod.objects.filter(
                id=pm_id, tenant_id=request.tenant_id
            ).first()
            if payment_method is None:
                return Response({"detail": "Payment method not found."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            sub = services.subscribe(
                tenant_id=request.tenant_id, plan=plan, payment_method=payment_method
            )
        except services.BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(SubscriptionSerializer(sub).data, status=status.HTTP_201_CREATED)


class SubscriptionCancelView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.ADMIN
    serializer_class = CancelSerializer

    def post(self, request):
        s = CancelSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            sub = services.cancel_subscription(
                tenant_id=request.tenant_id, at_period_end=s.validated_data["at_period_end"]
            )
        except services.BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(SubscriptionSerializer(sub).data)


class SubscriptionRetryView(TenantScopedAPIView, APIView):
    """Recover a past_due/incomplete subscription by re-charging the card."""

    permission_classes = [IsTenantMember]
    required_role = Role.ADMIN
    serializer_class = None

    def post(self, request):
        try:
            sub = services.retry_payment(tenant_id=request.tenant_id)
        except services.BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(SubscriptionSerializer(sub).data)


class PaymentMethodView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = PaymentMethodSerializer

    def get(self, request):
        methods = services.list_payment_methods(tenant_id=request.tenant_id)
        return Response(PaymentMethodSerializer(methods, many=True).data)

    def post(self, request):
        s = AddPaymentMethodSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            method = services.add_payment_method(
                tenant_id=request.tenant_id,
                provider_key=v["provider"],
                token=v["token"],
                kind=v["kind"],
                make_default=v["make_default"],
            )
        except services.BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(PaymentMethodSerializer(method).data, status=status.HTTP_201_CREATED)


class PaymentMethodDetailView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.ADMIN
    serializer_class = None

    @extend_schema(operation_id="billing_payment_method_set_default")
    def patch(self, request, method_id):
        """Promote this method to the one renewals charge.

        The only supported change: everything else about a stored method comes
        from the provider, and letting a client edit a brand or last4 would
        make the display disagree with what actually gets charged.
        """
        try:
            method = services.set_default_payment_method(
                tenant_id=request.tenant_id, payment_method_id=method_id
            )
        except services.BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(PaymentMethodSerializer(method).data)

    def delete(self, request, method_id):
        services.remove_payment_method(tenant_id=request.tenant_id, payment_method_id=method_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PaymentHistoryView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = PaymentSerializer

    def get(self, request):
        payments = services.list_payments(tenant_id=request.tenant_id)
        return Response(PaymentSerializer(payments, many=True).data)


class WebhookView(APIView):
    """Inbound provider webhooks. Public + unauthenticated by necessity — the
    provider calls us. Security is the per-provider signature verification done
    inside parse_webhook, plus event-id de-duplication. NOT tenant-scoped: the
    event is located by provider_ref, and the service binds context as needed."""

    permission_classes = [AllowAny]
    serializer_class = None

    def post(self, request, provider_key):
        headers = {k.lower(): v for k, v in request.headers.items()}
        try:
            result = services.handle_webhook(
                provider_key=provider_key, body=request.body, headers=headers
            )
        except services.BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response({"status": result})
