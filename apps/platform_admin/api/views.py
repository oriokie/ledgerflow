"""Platform workspace API.

Every view mixes `PlatformAdminAPIView` (transaction + `IsPlatformStaff`) and
declares the capability it needs. Views stay thin: they validate input, call a
service, and serialize the result. All business rules — including every audit
write — live in the service layer, so the same operation performed by a Celery
task or a management command is audited identically.

Pagination is offset-based here, unlike the tenant-facing API's cursor
pagination. That is a considered inversion: admin lists need "jump to page 40"
and a total count, both of which cursor pagination cannot give, and these
tables are thousands of rows rather than the millions the ledger reaches.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing import dunning as dunning_engine
from apps.billing import invoicing, refunds
from apps.billing.dunning_models import DunningCase, DunningPolicy
from apps.billing.invoice_pdf import invoice_filename, render_invoice_pdf
from apps.billing.invoicing_models import Invoice, Refund
from apps.billing.models import Payment, Plan, Subscription
from apps.billing.promotions_models import Coupon
from apps.billing.tasks import send_invoice_email_task
from apps.tenancy.models import Tenant
from apps.users.models import User

from .. import health, metrics, settings_store
from ..api_base import PlatformAdminAPIView
from ..audit import record
from ..models import (
    ImpersonationGrant,
    PlatformAuditLog,
    PlatformNotification,
    PlatformStaff,
    SavedView,
)
from ..notifications import acknowledge, acknowledge_all
from ..rbac import PlatformCapability as Cap
from ..selectors import tenants as tenant_selectors
from ..services import accounts as accounts_service
from ..services import impersonation as impersonation_service
from ..services import staff as staff_service
from ..services import tenants as tenant_service
from . import serializers as s


class AdminPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200


def _paginate(request, queryset, serializer_class, **serializer_kwargs):
    paginator = AdminPagination()
    page = paginator.paginate_queryset(queryset, request)
    data = serializer_class(page, many=True, **serializer_kwargs).data
    return paginator.get_paginated_response(data)


def _paginate_named(request, queryset, serializer_class):
    """Paginate, resolving each row's tenant name in one extra query.

    Billing rows carry `tenant_id` as a plain UUID column rather than a
    ForeignKey — they are isolated by RLS and deliberately do not join across
    the app boundary — so the name cannot come from `select_related`. Looking it
    up per row would be N+1; looking it up once per page is one query whatever
    the page size.
    """
    paginator = AdminPagination()
    page = paginator.paginate_queryset(queryset, request)
    names = dict(Tenant.objects.filter(id__in={row.tenant_id for row in page}).values_list("id", "name"))
    data = serializer_class(page, many=True, context={"tenant_names": names}).data
    return paginator.get_paginated_response(data)


# ============================================================== identity / me
class MeView(PlatformAdminAPIView, APIView):
    """Who the caller is and what they may do.

    The admin UI gates every control on this payload, so it is fetched once at
    boot. Returning the resolved capability list — rather than the role — means
    the client never has to reimplement the role→capability mapping and drift
    from the server's.
    """

    serializer_class = s.PlatformStaffSerializer

    def get(self, request):
        staff_service.touch_last_seen(staff=self.staff)
        return Response(s.PlatformStaffSerializer(self.staff).data)


class CapabilityCatalogView(PlatformAdminAPIView, APIView):
    required_capability = Cap.STAFF_READ
    serializer_class = None

    def get(self, request):
        return Response(
            {
                "capabilities": staff_service.capability_catalog(),
                "roles": [
                    {"value": r.value, "label": r.label}
                    for r in __import__("apps.platform_admin.rbac", fromlist=["PlatformRole"]).PlatformRole
                ],
            }
        )


# ==================================================================== dashboard
class DashboardView(PlatformAdminAPIView, APIView):
    required_capability = Cap.DASHBOARD_VIEW
    serializer_class = None

    def get(self, request):
        currency = request.query_params.get("currency", "USD")
        return Response(metrics.dashboard(currency=currency))


class AnalyticsView(PlatformAdminAPIView, APIView):
    """Deeper analytics than the dashboard card set.

    One endpoint with a `report` parameter rather than a dozen near-identical
    ones: they share filters and response envelope, and a dozen URLs would make
    adding a report a routing change instead of a dictionary entry.
    """

    required_capability = Cap.ANALYTICS_READ
    serializer_class = None

    REPORTS = {
        "revenue_series": lambda p: metrics.monthly_revenue_series(
            months=int(p.get("months", 12)), currency=p.get("currency", "USD")
        ),
        "cohorts": lambda p: metrics.cohort_retention(months=int(p.get("months", 6))),
        "forecast": lambda p: metrics.forecast_revenue(
            months_ahead=int(p.get("months", 6)), currency=p.get("currency", "USD")
        ),
        "churn": lambda p: metrics.churn(days=int(p.get("days", 30))),
        "ltv": lambda p: metrics.lifetime_value(currency=p.get("currency", "USD")),
        "trial_conversion": lambda p: metrics.trial_conversion(days=int(p.get("days", 90))),
        "payment_success": lambda p: metrics.payment_success_rate(days=int(p.get("days", 30))),
        "by_plan": lambda p: metrics.revenue_by("plan", currency=p.get("currency", "USD")),
        "by_country": lambda p: metrics.revenue_by("country", currency=p.get("currency", "USD")),
        "by_currency": lambda p: metrics.revenue_by("currency"),
        "by_provider": lambda p: metrics.revenue_by("provider", currency=p.get("currency", "USD")),
    }

    def get(self, request):
        report = request.query_params.get("report", "revenue_series")
        handler = self.REPORTS.get(report)
        if handler is None:
            return Response(
                {"detail": f"Unknown report. Available: {', '.join(sorted(self.REPORTS))}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            return Response({"report": report, "data": handler(request.query_params)})
        except (ValueError, TypeError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


# ====================================================================== tenants
class TenantListView(PlatformAdminAPIView, APIView):
    required_capability = Cap.TENANT_READ
    serializer_class = s.TenantRowSerializer

    def get(self, request):
        p = request.query_params
        queryset = tenant_selectors.search_tenants(
            query=p.get("q", ""),
            status=p.get("status", ""),
            plan_id=p.get("plan_id") or None,
            country=p.get("country", ""),
            subscription_status=p.get("subscription_status", ""),
            order_by=p.get("order_by", "-created_at"),
        )
        paginator = AdminPagination()
        page = paginator.paginate_queryset(queryset, request)
        rows = tenant_selectors.directory_page(page)
        return paginator.get_paginated_response(s.TenantRowSerializer(rows, many=True).data)


class TenantDetailView(PlatformAdminAPIView, APIView):
    capability_map = {"GET": Cap.TENANT_READ, "PATCH": Cap.TENANT_WRITE}
    serializer_class = None

    def get(self, request, tenant_id):
        tenant = Tenant.objects.filter(id=tenant_id).first()
        if tenant is None:
            return Response({"detail": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(tenant_selectors.tenant_detail(tenant))

    @extend_schema(request=s.UpdateTenantSerializer)
    def patch(self, request, tenant_id):
        tenant = Tenant.objects.filter(id=tenant_id).first()
        if tenant is None:
            return Response({"detail": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)
        payload = s.UpdateTenantSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        reason = data.pop("reason", "")
        try:
            tenant = tenant_service.update_tenant(
                tenant=tenant, actor=self.staff, reason=reason, request=request, **data
            )
        except tenant_service.TenantAdminError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(tenant_selectors.tenant_detail(tenant))


class _TenantActionView(PlatformAdminAPIView, APIView):
    """Shared plumbing for the POST-an-action-with-a-reason endpoints."""

    serializer_class = s.ReasonMixin

    def resolve_tenant(self, tenant_id):
        return Tenant.objects.filter(id=tenant_id).first()

    def run(self, request, tenant_id, fn, serializer=None, **extra):
        tenant = self.resolve_tenant(tenant_id)
        if tenant is None:
            return Response({"detail": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)
        payload = (serializer or s.ReasonMixin)(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            fn(tenant=tenant, actor=self.staff, request=request, **payload.validated_data, **extra)
        except tenant_service.TenantAdminError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(tenant_selectors.tenant_detail(self.resolve_tenant(tenant_id)))


class TenantSuspendView(_TenantActionView):
    required_capability = Cap.TENANT_SUSPEND

    def post(self, request, tenant_id):
        return self.run(request, tenant_id, tenant_service.suspend)


class TenantReactivateView(_TenantActionView):
    required_capability = Cap.TENANT_SUSPEND

    def post(self, request, tenant_id):
        return self.run(request, tenant_id, tenant_service.reactivate)


class TenantCloseView(_TenantActionView):
    required_capability = Cap.TENANT_DELETE

    def post(self, request, tenant_id):
        return self.run(request, tenant_id, tenant_service.close_tenant)


class TenantResetBillingView(_TenantActionView):
    required_capability = Cap.SUBSCRIPTION_WRITE

    def post(self, request, tenant_id):
        return self.run(request, tenant_id, tenant_service.reset_billing_state)


class TenantExtendTrialView(_TenantActionView):
    required_capability = Cap.SUBSCRIPTION_WRITE
    serializer_class = s.ExtendTrialSerializer

    def post(self, request, tenant_id):
        return self.run(request, tenant_id, tenant_service.extend_trial, s.ExtendTrialSerializer)


class TenantCancelSubscriptionView(_TenantActionView):
    required_capability = Cap.SUBSCRIPTION_WRITE
    serializer_class = s.CancelSubscriptionSerializer

    def post(self, request, tenant_id):
        return self.run(
            request, tenant_id, tenant_service.cancel_subscription, s.CancelSubscriptionSerializer
        )


class TenantResumeSubscriptionView(_TenantActionView):
    required_capability = Cap.SUBSCRIPTION_WRITE

    def post(self, request, tenant_id):
        return self.run(request, tenant_id, tenant_service.resume_subscription)


class TenantChangePlanView(_TenantActionView):
    required_capability = Cap.SUBSCRIPTION_WRITE
    serializer_class = s.ChangePlanSerializer

    def post(self, request, tenant_id):
        tenant = self.resolve_tenant(tenant_id)
        if tenant is None:
            return Response({"detail": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)
        payload = s.ChangePlanSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        plan = Plan.objects.filter(id=payload.validated_data["plan_id"], is_active=True).first()
        if plan is None:
            return Response({"detail": "Plan not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            tenant_service.change_plan(
                tenant=tenant,
                plan=plan,
                actor=self.staff,
                reason=payload.validated_data["reason"],
                request=request,
            )
        except tenant_service.TenantAdminError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(tenant_selectors.tenant_detail(self.resolve_tenant(tenant_id)))


class TenantComplimentaryView(_TenantActionView):
    required_capability = Cap.SUBSCRIPTION_GRANT
    serializer_class = s.ComplimentarySerializer

    def post(self, request, tenant_id):
        tenant = self.resolve_tenant(tenant_id)
        if tenant is None:
            return Response({"detail": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)
        payload = s.ComplimentarySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        plan = Plan.objects.filter(id=payload.validated_data["plan_id"], is_active=True).first()
        if plan is None:
            return Response({"detail": "Plan not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            tenant_service.grant_complimentary(
                tenant=tenant,
                plan=plan,
                actor=self.staff,
                reason=payload.validated_data["reason"],
                months=payload.validated_data["months"],
                request=request,
            )
        except tenant_service.TenantAdminError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(tenant_selectors.tenant_detail(self.resolve_tenant(tenant_id)))


class TenantCreditView(_TenantActionView):
    required_capability = Cap.CREDIT_ISSUE
    serializer_class = s.ApplyCreditSerializer

    def post(self, request, tenant_id):
        return self.run(request, tenant_id, tenant_service.apply_credit, s.ApplyCreditSerializer)


# =============================================================== impersonation
class ImpersonationStartView(PlatformAdminAPIView, APIView):
    required_capability = Cap.TENANT_IMPERSONATE
    serializer_class = s.StartImpersonationSerializer

    def post(self, request, tenant_id):
        payload = s.StartImpersonationSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            grant, raw_token = impersonation_service.start(
                staff=self.staff, tenant_id=tenant_id, request=request, **payload.validated_data
            )
        except impersonation_service.ImpersonationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(
            {
                **s.ImpersonationGrantSerializer(grant).data,
                # Returned exactly once; only its hash is stored.
                "token": raw_token,
            },
            status=status.HTTP_201_CREATED,
        )


class ImpersonationListView(PlatformAdminAPIView, APIView):
    required_capability = Cap.AUDIT_READ
    serializer_class = s.ImpersonationGrantSerializer

    def get(self, request):
        impersonation_service.expire_stale()
        queryset = ImpersonationGrant.objects.select_related("staff", "staff__user").order_by("-created_at")
        if request.query_params.get("active") == "true":
            queryset = impersonation_service.active_sessions()
        return _paginate(request, queryset, s.ImpersonationGrantSerializer)


class ImpersonationEndView(PlatformAdminAPIView, APIView):
    serializer_class = None

    def post(self, request, grant_id):
        grant = ImpersonationGrant.objects.filter(id=grant_id).select_related("staff").first()
        if grant is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        own = grant.staff_id == self.staff.id
        # Ending your own session is always allowed; ending someone else's is a
        # supervisory act and needs the audit capability.
        if not own and not self.staff.has(Cap.AUDIT_READ):
            return Response(
                {"detail": "You can only end your own impersonation sessions."},
                status=status.HTTP_403_FORBIDDEN,
            )
        reason = request.data.get("reason", "")
        if own:
            impersonation_service.end(grant=grant, actor=self.staff, reason=reason, request=request)
        else:
            impersonation_service.revoke(grant=grant, actor=self.staff, reason=reason, request=request)
        grant.refresh_from_db()
        return Response(s.ImpersonationGrantSerializer(grant).data)


# ===================================================================== billing
class InvoiceListView(PlatformAdminAPIView, APIView):
    required_capability = Cap.BILLING_READ
    serializer_class = s.InvoiceSerializer

    def get(self, request):
        queryset = Invoice.objects.prefetch_related("line_items").order_by("-issue_date", "-created_at")
        p = request.query_params
        if p.get("status"):
            queryset = queryset.filter(status=p["status"])
        if p.get("tenant_id"):
            queryset = queryset.filter(tenant_id=p["tenant_id"])
        if p.get("currency"):
            queryset = queryset.filter(currency=p["currency"].upper())
        if p.get("q"):
            queryset = queryset.filter(Q(number__icontains=p["q"]) | Q(billing_email__icontains=p["q"]))
        return _paginate_named(request, queryset, s.InvoiceSerializer)


class InvoiceDetailView(PlatformAdminAPIView, APIView):
    required_capability = Cap.BILLING_READ
    serializer_class = s.InvoiceSerializer

    def get(self, request, invoice_id):
        invoice = Invoice.objects.prefetch_related("line_items").filter(id=invoice_id).first()
        if invoice is None:
            return Response({"detail": "Invoice not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(s.InvoiceSerializer(invoice).data)


class InvoicePdfView(PlatformAdminAPIView, APIView):
    """Download an invoice as a PDF.

    Rendered on demand and never stored: the invoice row already holds the
    frozen arithmetic, so the document is reproducible from it, and a cached
    PDF that disagreed with its invoice would be worse than none.

    Returns a real file response rather than JSON, so the browser's own
    download handling applies.
    """

    required_capability = Cap.BILLING_READ
    serializer_class = None

    def get(self, request, invoice_id):
        invoice = Invoice.objects.prefetch_related("line_items").filter(id=invoice_id).first()
        if invoice is None:
            return Response({"detail": "Invoice not found."}, status=status.HTTP_404_NOT_FOUND)

        pdf = render_invoice_pdf(invoice)
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{invoice_filename(invoice)}"'
        # Reading a document is not an administrative action, so it is not
        # audited — auditing every download would bury the actions that matter
        # under noise from anyone glancing at a bill.
        return response


class InvoiceSendView(PlatformAdminAPIView, APIView):
    """Email an invoice to the customer, PDF attached.

    Queued rather than sent inline: a slow mail provider must not hold the
    request open, and delivery is retryable where the operator's intent is not.
    """

    required_capability = Cap.INVOICE_WRITE
    serializer_class = s.SendInvoiceSerializer

    def post(self, request, invoice_id):
        invoice = Invoice.objects.filter(id=invoice_id).first()
        if invoice is None:
            return Response({"detail": "Invoice not found."}, status=status.HTTP_404_NOT_FOUND)

        payload = s.SendInvoiceSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        to = payload.validated_data.get("to") or invoice.billing_email
        if not to:
            return Response(
                {"to": ["This invoice has no billing address; supply one."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        send_invoice_email_task.delay(invoice_id=str(invoice.id), to=to)

        record(
            action="invoice.sent",
            staff=self.staff,
            module="billing",
            target_type="billing.Invoice",
            target_id=invoice.id,
            tenant_id=invoice.tenant_id,
            reason=payload.validated_data.get("reason") or f"Emailed invoice {invoice.number}.",
            context={"to": to},
            request=request,
        )
        return Response({"queued": True, "to": to})


class InvoiceVoidView(PlatformAdminAPIView, APIView):
    required_capability = Cap.INVOICE_WRITE
    serializer_class = s.ReasonMixin

    def post(self, request, invoice_id):
        invoice = Invoice.objects.filter(id=invoice_id).first()
        if invoice is None:
            return Response({"detail": "Invoice not found."}, status=status.HTTP_404_NOT_FOUND)
        payload = s.ReasonMixin(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            invoicing.void_invoice(invoice=invoice, reason=payload.validated_data["reason"])
        except invoicing.InvoicingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        record(
            action="invoice.voided",
            staff=self.staff,
            module="billing",
            target_type="billing.Invoice",
            target_id=invoice.id,
            tenant_id=invoice.tenant_id,
            reason=payload.validated_data["reason"],
            request=request,
        )
        invoice.refresh_from_db()
        return Response(s.InvoiceSerializer(invoice).data)


class PaymentListView(PlatformAdminAPIView, APIView):
    required_capability = Cap.BILLING_READ
    serializer_class = s.PaymentRowSerializer

    def get(self, request):
        queryset = Payment.objects.order_by("-created_at")
        p = request.query_params
        if p.get("status"):
            queryset = queryset.filter(status=p["status"])
        if p.get("tenant_id"):
            queryset = queryset.filter(tenant_id=p["tenant_id"])
        if p.get("provider"):
            queryset = queryset.filter(provider=p["provider"])
        return _paginate(request, queryset, s.PaymentRowSerializer)


class PaymentReconcileView(PlatformAdminAPIView, APIView):
    required_capability = Cap.PAYMENT_RECONCILE
    serializer_class = s.ReconcilePaymentSerializer

    def post(self, request):
        payload = s.ReconcilePaymentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        v = payload.validated_data

        payment = Payment.objects.filter(id=v["payment_id"]).first()
        invoice = Invoice.objects.filter(id=v["invoice_id"]).first()
        if payment is None or invoice is None:
            return Response({"detail": "Payment or invoice not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            invoicing.reconcile_payment(payment=payment, invoice=invoice)
        except invoicing.InvoicingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        record(
            action="payment.reconciled",
            staff=self.staff,
            module="billing",
            target_type="billing.Invoice",
            target_id=invoice.id,
            tenant_id=invoice.tenant_id,
            changes={"amount_paid_minor": [None, payment.amount_minor]},
            reason=v["reason"],
            context={"payment_id": str(payment.id)},
            request=request,
        )
        invoice.refresh_from_db()
        return Response(s.InvoiceSerializer(invoice).data)


# ===================================================================== refunds
class RefundListView(PlatformAdminAPIView, APIView):
    capability_map = {"GET": Cap.BILLING_READ, "POST": Cap.REFUND_REQUEST}
    serializer_class = s.RefundSerializer

    def get(self, request):
        queryset = Refund.objects.select_related("requested_by", "approved_by").order_by("-created_at")
        if request.query_params.get("status"):
            queryset = queryset.filter(status=request.query_params["status"])
        if request.query_params.get("tenant_id"):
            queryset = queryset.filter(tenant_id=request.query_params["tenant_id"])
        return _paginate(request, queryset, s.RefundSerializer)

    @extend_schema(request=s.RequestRefundSerializer)
    def post(self, request):
        payload = s.RequestRefundSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        v = payload.validated_data

        payment = Payment.objects.filter(id=v["payment_id"]).first()
        if payment is None:
            return Response({"detail": "Payment not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            refund = refunds.request_refund(
                payment=payment,
                amount_minor=v.get("amount_minor"),
                reason=v["reason"],
                requested_by=request.user,
            )
        except refunds.RefundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        record(
            action="refund.requested",
            staff=self.staff,
            module="billing",
            target_type="billing.Refund",
            target_id=refund.id,
            tenant_id=refund.tenant_id,
            changes={"amount_minor": [None, refund.amount_minor]},
            reason=v["reason"],
            request=request,
        )
        return Response(s.RefundSerializer(refund).data, status=status.HTTP_201_CREATED)


class RefundDecisionView(PlatformAdminAPIView, APIView):
    """Approve or reject. Both need `refund.approve` — the point of the split
    is that requesting and deciding are different people, so rejecting is a
    decision too."""

    required_capability = Cap.REFUND_APPROVE
    serializer_class = s.DecideRefundSerializer

    def post(self, request, refund_id, decision):
        refund = Refund.objects.filter(id=refund_id).first()
        if refund is None:
            return Response({"detail": "Refund not found."}, status=status.HTTP_404_NOT_FOUND)
        payload = s.DecideRefundSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        note = payload.validated_data["note"]

        try:
            if decision == "approve":
                refunds.approve_refund(refund=refund, approved_by=request.user, note=note)
            else:
                refunds.reject_refund(refund=refund, approved_by=request.user, note=note)
        except refunds.RefundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        refund.refresh_from_db()
        record(
            action=f"refund.{decision}d",
            staff=self.staff,
            module="billing",
            target_type="billing.Refund",
            target_id=refund.id,
            tenant_id=refund.tenant_id,
            changes={"status": ["requested", refund.status]},
            reason=note or f"Refund {decision}d.",
            request=request,
        )
        return Response(s.RefundSerializer(refund).data)


# ===================================================================== coupons
class CouponListView(PlatformAdminAPIView, APIView):
    capability_map = {"GET": Cap.COUPON_READ, "POST": Cap.COUPON_WRITE}
    serializer_class = s.CouponSerializer

    def get(self, request):
        queryset = Coupon.objects.order_by("-created_at")
        if request.query_params.get("active") == "true":
            queryset = queryset.filter(is_active=True)
        return _paginate(request, queryset, s.CouponSerializer)

    @extend_schema(request=s.WriteCouponSerializer)
    def post(self, request):
        payload = s.WriteCouponSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        v = dict(payload.validated_data)
        plan_ids = v.pop("plan_ids", [])

        if Coupon.objects.filter(code=v["code"].strip().upper()).exists():
            return Response(
                {"code": ["A coupon with that code already exists."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        coupon = Coupon.objects.create(created_by=request.user, **v)
        if plan_ids:
            coupon.applies_to_plans.set(Plan.objects.filter(id__in=plan_ids))

        record(
            action="coupon.created",
            staff=self.staff,
            module="billing",
            target_type="billing.Coupon",
            target_id=coupon.id,
            changes={"code": [None, coupon.code], "kind": [None, coupon.kind]},
            reason=f"Created promotion {coupon.code}.",
            request=request,
        )
        return Response(s.CouponSerializer(coupon).data, status=status.HTTP_201_CREATED)


class CouponDetailView(PlatformAdminAPIView, APIView):
    capability_map = {"GET": Cap.COUPON_READ, "PATCH": Cap.COUPON_WRITE, "DELETE": Cap.COUPON_WRITE}
    serializer_class = s.CouponSerializer

    def get(self, request, coupon_id):
        coupon = Coupon.objects.filter(id=coupon_id).first()
        if coupon is None:
            return Response({"detail": "Coupon not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(s.CouponSerializer(coupon).data)

    def patch(self, request, coupon_id):
        coupon = Coupon.objects.filter(id=coupon_id).first()
        if coupon is None:
            return Response({"detail": "Coupon not found."}, status=status.HTTP_404_NOT_FOUND)

        # Only campaign controls are editable. Changing `kind` or `value` after
        # redemptions exist would retroactively alter what customers were
        # promised, and the redemption rows record the old terms.
        before = {"is_active": coupon.is_active, "expires_at": str(coupon.expires_at)}
        for field in ("is_active", "expires_at", "max_redemptions", "description", "name"):
            if field in request.data:
                setattr(coupon, field, request.data[field])
        coupon.save()

        record(
            action="coupon.updated",
            staff=self.staff,
            module="billing",
            target_type="billing.Coupon",
            target_id=coupon.id,
            changes={"before": [before, None]},
            reason=request.data.get("reason", "Campaign updated."),
            request=request,
        )
        return Response(s.CouponSerializer(coupon).data)

    def delete(self, request, coupon_id):
        """Deactivate rather than delete — redemption rows reference it, and a
        campaign's history is the point of running campaigns."""
        coupon = Coupon.objects.filter(id=coupon_id).first()
        if coupon is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        coupon.is_active = False
        coupon.save(update_fields=["is_active", "updated_at"])
        record(
            action="coupon.deactivated",
            staff=self.staff,
            module="billing",
            target_type="billing.Coupon",
            target_id=coupon.id,
            reason=request.data.get("reason", "Campaign ended."),
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ===================================================================== dunning
class DunningCaseListView(PlatformAdminAPIView, APIView):
    required_capability = Cap.DUNNING_READ
    serializer_class = s.DunningCaseSerializer

    def get(self, request):
        queryset = DunningCase.objects.prefetch_related("attempts").order_by("-opened_at")
        if request.query_params.get("status"):
            queryset = queryset.filter(status=request.query_params["status"])
        return _paginate_named(request, queryset, s.DunningCaseSerializer)


class DunningCaseActionView(PlatformAdminAPIView, APIView):
    required_capability = Cap.DUNNING_MANAGE
    serializer_class = s.ReasonMixin

    def post(self, request, case_id, action):
        case = DunningCase.objects.filter(id=case_id).select_related("subscription").first()
        if case is None:
            return Response({"detail": "Case not found."}, status=status.HTTP_404_NOT_FOUND)
        payload = s.ReasonMixin(data=request.data)
        payload.is_valid(raise_exception=True)
        reason = payload.validated_data["reason"]

        if action == "recover":
            dunning_engine.mark_recovered(case=case, note=reason)
        elif action == "cancel":
            from apps.billing.dunning_models import DunningCaseStatus

            dunning_engine.close_case(case=case, status=DunningCaseStatus.CANCELLED, note=reason)
        else:
            return Response({"detail": "Unknown action."}, status=status.HTTP_400_BAD_REQUEST)

        record(
            action=f"dunning.{action}",
            staff=self.staff,
            module="billing",
            target_type="billing.DunningCase",
            target_id=case.id,
            tenant_id=case.tenant_id,
            reason=reason,
            request=request,
        )
        case.refresh_from_db()
        return Response(s.DunningCaseSerializer(case).data)


class DunningPolicyView(PlatformAdminAPIView, APIView):
    capability_map = {"GET": Cap.DUNNING_READ, "POST": Cap.DUNNING_MANAGE}
    serializer_class = s.DunningPolicySerializer

    def get(self, request):
        return Response(s.DunningPolicySerializer(DunningPolicy.objects.order_by("name"), many=True).data)

    def post(self, request):
        payload = s.DunningPolicySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        v = dict(payload.validated_data)

        if v.get("is_default"):
            # The partial unique index would reject a second default; clear the
            # incumbent first so the operator's intent is honoured.
            DunningPolicy.objects.filter(is_default=True).update(is_default=False)

        policy = DunningPolicy(**v)
        try:
            dunning_engine.validate_policy(policy)
        except dunning_engine.DunningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        policy.save()

        record(
            action="dunning.policy_created",
            staff=self.staff,
            module="billing",
            target_type="billing.DunningPolicy",
            target_id=policy.id,
            reason=f"Created dunning policy {policy.name}.",
            request=request,
        )
        return Response(s.DunningPolicySerializer(policy).data, status=status.HTTP_201_CREATED)


# ======================================================================= staff
class StaffListView(PlatformAdminAPIView, APIView):
    capability_map = {"GET": Cap.STAFF_READ, "POST": Cap.STAFF_MANAGE}
    serializer_class = s.PlatformStaffSerializer

    def get(self, request):
        queryset = PlatformStaff.objects.select_related("user").order_by("-created_at")
        return _paginate(request, queryset, s.PlatformStaffSerializer)

    @extend_schema(request=s.AppointStaffSerializer)
    def post(self, request):
        payload = s.AppointStaffSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        v = dict(payload.validated_data)

        user = User.objects.filter(email__iexact=v.pop("email")).first()
        if user is None:
            return Response(
                {"email": ["No user with that email address."]}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            member = staff_service.appoint(user=user, actor=self.staff, request=request, **v)
        except staff_service.StaffError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(s.PlatformStaffSerializer(member).data, status=status.HTTP_201_CREATED)


class StaffDetailView(PlatformAdminAPIView, APIView):
    capability_map = {"GET": Cap.STAFF_READ, "PATCH": Cap.STAFF_MANAGE, "DELETE": Cap.STAFF_MANAGE}
    serializer_class = s.PlatformStaffSerializer

    def _get(self, staff_id):
        return PlatformStaff.objects.select_related("user").filter(id=staff_id).first()

    def get(self, request, staff_id):
        member = self._get(staff_id)
        if member is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(s.PlatformStaffSerializer(member).data)

    @extend_schema(request=s.UpdateStaffSerializer)
    def patch(self, request, staff_id):
        member = self._get(staff_id)
        if member is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        payload = s.UpdateStaffSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            member = staff_service.update(
                staff=member, actor=self.staff, request=request, **payload.validated_data
            )
        except staff_service.StaffError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(s.PlatformStaffSerializer(member).data)

    def delete(self, request, staff_id):
        member = self._get(staff_id)
        if member is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        try:
            staff_service.revoke(
                staff=member,
                actor=self.staff,
                reason=request.data.get("reason", "Access revoked."),
                request=request,
            )
        except staff_service.StaffError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ======================================================================= audit
class AuditLogView(PlatformAdminAPIView, APIView):
    required_capability = Cap.AUDIT_READ
    serializer_class = s.AuditLogSerializer

    def get(self, request):
        queryset = PlatformAuditLog.objects.order_by("-created_at")
        p = request.query_params
        if p.get("actor_id"):
            queryset = queryset.filter(actor_id=p["actor_id"])
        if p.get("tenant_id"):
            queryset = queryset.filter(tenant_id=p["tenant_id"])
        if p.get("module"):
            queryset = queryset.filter(module=p["module"])
        if p.get("action"):
            queryset = queryset.filter(action=p["action"])
        if p.get("q"):
            queryset = queryset.filter(
                Q(actor_email__icontains=p["q"]) | Q(action__icontains=p["q"]) | Q(reason__icontains=p["q"])
            )
        if p.get("since"):
            queryset = queryset.filter(created_at__gte=p["since"])
        return _paginate(request, queryset, s.AuditLogSerializer)


# ====================================================================== health
class HealthView(PlatformAdminAPIView, APIView):
    required_capability = Cap.HEALTH_READ
    serializer_class = None

    def get(self, request):
        return Response(health.snapshot())


# =============================================================== notifications
class NotificationListView(PlatformAdminAPIView, APIView):
    required_capability = Cap.NOTIFICATION_READ
    serializer_class = s.PlatformNotificationSerializer

    def get(self, request):
        queryset = PlatformNotification.objects.order_by("-created_at")
        if request.query_params.get("open") == "true":
            queryset = queryset.filter(acknowledged_at__isnull=True)
        if request.query_params.get("severity"):
            queryset = queryset.filter(severity=request.query_params["severity"])
        return _paginate(request, queryset, s.PlatformNotificationSerializer)


class NotificationAckView(PlatformAdminAPIView, APIView):
    required_capability = Cap.NOTIFICATION_MANAGE
    serializer_class = None

    def post(self, request, notification_id=None):
        if notification_id is None:
            count = acknowledge_all(user=request.user, category=request.data.get("category", ""))
            return Response({"acknowledged": count})
        notification = PlatformNotification.objects.filter(id=notification_id).first()
        if notification is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        acknowledge(notification=notification, user=request.user)
        notification.refresh_from_db()
        return Response(s.PlatformNotificationSerializer(notification).data)


# ======================================================== account recovery
class UserLookupView(PlatformAdminAPIView, APIView):
    """Find a customer account and say plainly why they cannot get in."""

    required_capability = Cap.TENANT_READ
    serializer_class = None

    def get(self, request):
        email = request.query_params.get("email", "").strip()
        if not email:
            return Response(
                {"email": ["Provide an email address to search for."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = accounts_service.find_user(email=email)
        if user is None:
            return Response({"detail": "No account with that email."}, status=status.HTTP_404_NOT_FOUND)
        return Response(accounts_service.account_status(user=user))


class UserRecoveryActionView(PlatformAdminAPIView, APIView):
    """Unlock, reactivate, verify, or start a password reset.

    MFA reset is routed here too but gated on its own capability: it is the one
    action that lowers a security control rather than clearing an obstruction.
    """

    capability_map = {"POST": Cap.USER_RECOVER}
    serializer_class = s.ReasonMixin

    ACTIONS = {"reactivate", "deactivate", "send-password-reset", "reset-mfa", "verify-email"}

    def post(self, request, user_id, action):
        if action not in self.ACTIONS:
            return Response(
                {"detail": f"Unknown action. Available: {', '.join(sorted(self.ACTIONS))}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if action == "reset-mfa" and not self.staff.has(Cap.USER_MFA_RESET):
            return Response(
                {"detail": "Resetting two-factor authentication needs a separate permission."},
                status=status.HTTP_403_FORBIDDEN,
            )

        user = User.objects.filter(id=user_id).first()
        if user is None:
            return Response({"detail": "Account not found."}, status=status.HTTP_404_NOT_FOUND)

        payload = s.ReasonMixin(data=request.data)
        payload.is_valid(raise_exception=True)
        reason = payload.validated_data["reason"]

        handlers = {
            "reactivate": accounts_service.reactivate,
            "deactivate": accounts_service.deactivate,
            "send-password-reset": accounts_service.send_password_reset,
            "reset-mfa": accounts_service.reset_mfa,
            "verify-email": accounts_service.verify_email,
        }
        try:
            handlers[action](user=user, actor=self.staff, reason=reason, request=request)
        except accounts_service.AccountRecoveryError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        user.refresh_from_db()
        return Response(accounts_service.account_status(user=user))


class PlanCatalogueView(PlatformAdminAPIView, APIView):
    """What each tier includes — the data behind a pricing page."""

    required_capability = Cap.SUBSCRIPTION_READ
    serializer_class = None

    def get(self, request):
        from apps.billing.plan_catalogue import FEATURE_LABELS, UNIVERSAL, catalogue

        # Labels and the universal set ride along so the console's feature
        # editor and the pricing surfaces all print the same names from the
        # same map — the whole point of holding labels server-side.
        return Response({"tiers": catalogue(), "labels": FEATURE_LABELS, "universal": sorted(UNIVERSAL)})


# ==================================================================== settings
class PublicAppearanceView(APIView):
    """The handful of platform settings the signed-out product needs.

    Deliberately its own endpoint rather than an exemption on the settings API.
    That one is capability-gated and returns every key the console can touch —
    including which secrets are configured — and the landing page needs exactly
    one string. An allowlist of one is easier to keep safe than a filter over
    everything.
    """

    permission_classes = [AllowAny]
    serializer_class = None

    @extend_schema(operation_id="platform_public_appearance")
    def get(self, request):
        return Response({"illustration_style": settings_store.get("appearance.illustration_style")})


class PlatformSettingsView(PlatformAdminAPIView, APIView):
    """Read and write runtime platform configuration.

    Secrets are write-only: the response says whether a key is set and which
    layer supplied it, never its value. An operator can rotate a credential;
    nobody can read one back out through the console — which is what keeps a
    compromised admin session from becoming a credential dump.
    """

    capability_map = {"GET": Cap.HEALTH_READ, "POST": Cap.STAFF_MANAGE}
    serializer_class = s.WriteSettingSerializer

    def get(self, request):
        return Response({"settings": settings_store.describe_all()})

    @extend_schema(request=s.WriteSettingSerializer)
    def post(self, request):
        payload = s.WriteSettingSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        key = payload.validated_data["key"]
        value = payload.validated_data["value"]

        spec = settings_store.SPEC_BY_KEY.get(key)
        if spec is None:
            return Response(
                {"key": [f"{key} is not a known platform setting."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if value in (None, ""):
            settings_store.clear(key=key, user=request.user)
            action, after = "setting.cleared", None
        else:
            try:
                settings_store.set_value(key=key, raw=value, user=request.user)
            except settings_store.InvalidSettingValue as exc:
                # A closed-set setting stored with a bad value would not error
                # anywhere — the only symptom is an interface that quietly
                # stops working. Refuse it at the boundary instead.
                return Response({"value": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
            action, after = "setting.updated", ("<set>" if spec.write_only else value)

        record(
            action=action,
            staff=self.staff,
            module="settings",
            target_type="platform_admin.PlatformSetting",
            # The audit row records *that* a secret changed and by whom, never
            # its value — an audit log holding live credentials is a liability,
            # not a control.
            changes={key: [None, after]},
            reason=payload.validated_data["reason"] or f"Updated {key}.",
            request=request,
        )
        return Response(settings_store.describe(spec))


class PlatformTestEmailView(PlatformAdminAPIView, APIView):
    """Send a one-line message to the operator so a broken relay is visible."""

    capability_map = {"POST": Cap.STAFF_MANAGE}
    serializer_class = None

    def post(self, request):
        from django.core.mail import send_mail

        from apps.platform_admin.email_backend import resolve_from_email

        to = request.user.email
        try:
            send_mail(
                subject="LedgerFlow test email",
                message="Outbound email is working. This is a test from platform settings.",
                from_email=resolve_from_email(),
                recipient_list=[to],
                fail_silently=False,
            )
        except Exception as exc:  # noqa: BLE001 — surface the SMTP error
            record(
                action="setting.test_email_failed",
                staff=self.staff,
                module="settings",
                target_type="platform_admin.PlatformSetting",
                changes={"email": [None, str(exc)[:200]]},
                reason="Test email failed.",
                request=request,
            )
            return Response({"ok": False, "detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        record(
            action="setting.test_email",
            staff=self.staff,
            module="settings",
            target_type="platform_admin.PlatformSetting",
            changes={"to": [None, to]},
            reason="Sent a test email.",
            request=request,
        )
        return Response({"ok": True, "to": to})


class PlatformTestAIView(PlatformAdminAPIView, APIView):
    """Ping the configured model without sending any household data."""

    capability_map = {"POST": Cap.STAFF_MANAGE}
    serializer_class = None

    def post(self, request):
        from apps.intelligence.llm import complete, get_llm_config

        config = get_llm_config()
        if not config.enabled:
            return Response({"ok": False, "detail": "AI is turned off."}, status=status.HTTP_400_BAD_REQUEST)
        if not config.model:
            return Response({"ok": False, "detail": "No model is configured."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            reply = complete(
                system="You are a connectivity check. Reply with the single word pong.",
                user="ping",
                config=config,
            )
        except Exception as exc:  # noqa: BLE001 — surface provider errors
            return Response({"ok": False, "detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"ok": True, "model": config.model, "reply": (reply or "")[:240]})


# ================================================================= saved views
class SavedViewListView(PlatformAdminAPIView, APIView):
    serializer_class = s.SavedViewSerializer

    def get(self, request):
        queryset = SavedView.objects.filter(Q(staff=self.staff) | Q(is_shared=True)).order_by(
            "surface", "name"
        )
        if request.query_params.get("surface"):
            queryset = queryset.filter(surface=request.query_params["surface"])
        return Response(s.SavedViewSerializer(queryset, many=True).data)

    def post(self, request):
        payload = s.SavedViewSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        view, _ = SavedView.objects.update_or_create(
            staff=self.staff,
            surface=payload.validated_data["surface"],
            name=payload.validated_data["name"],
            defaults={
                "filters": payload.validated_data.get("filters", {}),
                "is_shared": payload.validated_data.get("is_shared", False),
            },
        )
        return Response(s.SavedViewSerializer(view).data, status=status.HTTP_201_CREATED)


class SavedViewDetailView(PlatformAdminAPIView, APIView):
    serializer_class = None

    def delete(self, request, view_id):
        SavedView.objects.filter(id=view_id, staff=self.staff).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ======================================================================= plans
def _plan_out(plan, subscriber_counts: dict | None = None) -> dict:
    from apps.billing.plan_catalogue import label_for, resolved_features

    return {
        "id": str(plan.id),
        "tier": plan.tier,
        "name": plan.name,
        "description": plan.description,
        "price_minor": plan.price_minor,
        "currency": plan.currency,
        "interval": plan.interval,
        "max_members": plan.max_members,
        "max_accounts": plan.max_accounts,
        "ai_insights": plan.ai_insights,
        "is_active": plan.is_active,
        "sort_order": plan.sort_order,
        #: The override list as stored — what an editor round-trips.
        "features": sorted(str(f) for f in (plan.features or [])),
        #: What the plan actually includes, labelled — tier defaults ∪ override.
        "resolved_features": [{"key": key, "label": label_for(key)} for key in resolved_features(plan)],
        "subscriber_count": (subscriber_counts or {}).get(plan.id, 0),
    }


class PlanListView(PlatformAdminAPIView, APIView):
    """The plan catalog — plan pickers and the console's Plans page.

    `?all=true` includes retired plans, which the console needs (a plan with
    live subscribers can be inactive-for-new-signups) and the pickers do not.
    """

    required_capability = Cap.SUBSCRIPTION_READ
    serializer_class = None

    def get(self, request):
        queryset = Plan.objects.all().order_by("sort_order", "price_minor")
        if request.query_params.get("all") not in ("true", "1"):
            queryset = queryset.filter(is_active=True)

        # Live subscribers per plan in one query — the number that turns
        # "edit this row" from routine into "this changes 40 households".
        counts = dict(
            Subscription.objects.filter(status__in=["active", "trialing", "past_due"])
            .values_list("plan_id")
            .annotate(n=models.Count("id"))
            .values_list("plan_id", "n")
        )
        return Response([_plan_out(p, counts) for p in queryset])


class PlanDetailView(PlatformAdminAPIView, APIView):
    """Edit one catalogue plan, with a reason, into the audit log."""

    required_capability = Cap.PLAN_MANAGE
    serializer_class = s.PlanUpdateSerializer

    def patch(self, request, plan_id):
        plan = Plan.objects.filter(id=plan_id).first()
        if plan is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        payload = s.PlanUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        reason = data.pop("reason")

        # Field-level before/after into the audit row: "what changed" is the
        # first question about any commercial edit, and a diff nobody recorded
        # at write time cannot be reconstructed later.
        changes = {}
        for field, value in data.items():
            before = getattr(plan, field)
            if before != value:
                changes[field] = [before, value]
                setattr(plan, field, value)

        if not changes:
            return Response(_plan_out(plan))

        plan.save(update_fields=[*changes.keys(), "updated_at"])
        record(
            action="plan.updated",
            staff=self.staff,
            module="billing",
            target_type="plan",
            target_id=plan.id,
            changes=changes,
            reason=reason,
            request=request,
        )
        counts = dict(
            Subscription.objects.filter(plan=plan, status__in=["active", "trialing", "past_due"])
            .values_list("plan_id")
            .annotate(n=models.Count("id"))
            .values_list("plan_id", "n")
        )
        return Response(_plan_out(plan, counts))


class SubscriptionListView(PlatformAdminAPIView, APIView):
    required_capability = Cap.SUBSCRIPTION_READ
    serializer_class = None

    def get(self, request):
        queryset = Subscription.objects.select_related("plan").order_by("-created_at")
        if request.query_params.get("status"):
            queryset = queryset.filter(status=request.query_params["status"])
        paginator = AdminPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(
            [tenant_selectors._subscription_dict(sub) | {"tenant_id": str(sub.tenant_id)} for sub in page]
        )


class ExpiringTrialsView(PlatformAdminAPIView, APIView):
    required_capability = Cap.SUBSCRIPTION_READ
    serializer_class = None

    def get(self, request):
        days = int(request.query_params.get("days", 7))
        rows = tenant_selectors.expiring_trials(within_days=days)
        names = dict(Tenant.objects.filter(id__in=[r.tenant_id for r in rows]).values_list("id", "name"))
        return Response(
            [
                {
                    "tenant_id": str(r.tenant_id),
                    "tenant_name": names.get(r.tenant_id, ""),
                    "plan_name": r.plan.name,
                    "trial_end": r.trial_end,
                    "days_left": (r.trial_end - timezone.now()).days if r.trial_end else None,
                }
                for r in rows
            ]
        )
