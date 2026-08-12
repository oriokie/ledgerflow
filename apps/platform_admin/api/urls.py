"""Platform workspace routes.

Mounted at `/api/v1/platform/` — a sibling of the tenant API rather than a
child of it. The separation is the point: nothing under this prefix accepts an
`X-Tenant-ID` header or resolves a membership, so a misrouted tenant request
cannot land here and a platform route cannot accidentally inherit tenant
scoping.
"""

from django.urls import path

from .views import (
    AnalyticsView,
    AuditLogView,
    CapabilityCatalogView,
    CouponDetailView,
    CouponListView,
    DashboardView,
    DunningCaseActionView,
    DunningCaseListView,
    DunningPolicyView,
    ExpiringTrialsView,
    HealthView,
    ImpersonationEndView,
    ImpersonationListView,
    ImpersonationStartView,
    InvoiceDetailView,
    InvoiceListView,
    InvoicePdfView,
    InvoiceSendView,
    InvoiceVoidView,
    MeView,
    NotificationAckView,
    NotificationListView,
    PaymentListView,
    PaymentReconcileView,
    PlanCatalogueView,
    PlanDetailView,
    PlanListView,
    PlatformSettingsView,
    PlatformTestAIView,
    PlatformTestEmailView,
    PublicAppearanceView,
    RefundDecisionView,
    RefundListView,
    SavedViewDetailView,
    SavedViewListView,
    StaffDetailView,
    StaffListView,
    SubscriptionListView,
    TenantCancelSubscriptionView,
    TenantChangePlanView,
    TenantCloseView,
    TenantComplimentaryView,
    TenantCreditView,
    TenantDetailView,
    TenantExtendTrialView,
    TenantListView,
    TenantReactivateView,
    TenantResetBillingView,
    TenantResumeSubscriptionView,
    TenantSuspendView,
    UserLookupView,
    UserRecoveryActionView,
)

urlpatterns = [
    # Identity
    path("me/", MeView.as_view(), name="platform-me"),
    path("capabilities/", CapabilityCatalogView.as_view(), name="platform-capabilities"),
    # Dashboard & analytics
    path("dashboard/", DashboardView.as_view(), name="platform-dashboard"),
    path("analytics/", AnalyticsView.as_view(), name="platform-analytics"),
    # Tenants
    path("tenants/", TenantListView.as_view(), name="platform-tenants"),
    path("tenants/<uuid:tenant_id>/", TenantDetailView.as_view(), name="platform-tenant-detail"),
    path("tenants/<uuid:tenant_id>/suspend/", TenantSuspendView.as_view(), name="platform-tenant-suspend"),
    path(
        "tenants/<uuid:tenant_id>/reactivate/",
        TenantReactivateView.as_view(),
        name="platform-tenant-reactivate",
    ),
    path("tenants/<uuid:tenant_id>/close/", TenantCloseView.as_view(), name="platform-tenant-close"),
    path(
        "tenants/<uuid:tenant_id>/reset-billing/",
        TenantResetBillingView.as_view(),
        name="platform-tenant-reset-billing",
    ),
    path(
        "tenants/<uuid:tenant_id>/extend-trial/",
        TenantExtendTrialView.as_view(),
        name="platform-tenant-extend-trial",
    ),
    path(
        "tenants/<uuid:tenant_id>/change-plan/",
        TenantChangePlanView.as_view(),
        name="platform-tenant-change-plan",
    ),
    path(
        "tenants/<uuid:tenant_id>/complimentary/",
        TenantComplimentaryView.as_view(),
        name="platform-tenant-complimentary",
    ),
    path(
        "tenants/<uuid:tenant_id>/cancel-subscription/",
        TenantCancelSubscriptionView.as_view(),
        name="platform-tenant-cancel-subscription",
    ),
    path(
        "tenants/<uuid:tenant_id>/resume-subscription/",
        TenantResumeSubscriptionView.as_view(),
        name="platform-tenant-resume-subscription",
    ),
    path("tenants/<uuid:tenant_id>/credit/", TenantCreditView.as_view(), name="platform-tenant-credit"),
    # Impersonation
    path(
        "tenants/<uuid:tenant_id>/impersonate/",
        ImpersonationStartView.as_view(),
        name="platform-impersonate-start",
    ),
    path("impersonations/", ImpersonationListView.as_view(), name="platform-impersonations"),
    path(
        "impersonations/<uuid:grant_id>/end/",
        ImpersonationEndView.as_view(),
        name="platform-impersonation-end",
    ),
    # Billing
    path("plans/", PlanListView.as_view(), name="platform-plans"),
    path("plans/<uuid:plan_id>/", PlanDetailView.as_view(), name="platform-plan-detail"),
    path("plans/catalogue/", PlanCatalogueView.as_view(), name="platform-plan-catalogue"),
    path("users/lookup/", UserLookupView.as_view(), name="platform-user-lookup"),
    path(
        "users/<uuid:user_id>/<str:action>/",
        UserRecoveryActionView.as_view(),
        name="platform-user-recovery",
    ),
    path("subscriptions/", SubscriptionListView.as_view(), name="platform-subscriptions"),
    path("subscriptions/expiring-trials/", ExpiringTrialsView.as_view(), name="platform-expiring-trials"),
    path("invoices/", InvoiceListView.as_view(), name="platform-invoices"),
    path("invoices/<uuid:invoice_id>/", InvoiceDetailView.as_view(), name="platform-invoice-detail"),
    path("invoices/<uuid:invoice_id>/pdf/", InvoicePdfView.as_view(), name="platform-invoice-pdf"),
    path("invoices/<uuid:invoice_id>/send/", InvoiceSendView.as_view(), name="platform-invoice-send"),
    path("invoices/<uuid:invoice_id>/void/", InvoiceVoidView.as_view(), name="platform-invoice-void"),
    path("payments/", PaymentListView.as_view(), name="platform-payments"),
    path("payments/reconcile/", PaymentReconcileView.as_view(), name="platform-payment-reconcile"),
    # Refunds
    path("refunds/", RefundListView.as_view(), name="platform-refunds"),
    path(
        "refunds/<uuid:refund_id>/<str:decision>/",
        RefundDecisionView.as_view(),
        name="platform-refund-decision",
    ),
    # Coupons
    path("coupons/", CouponListView.as_view(), name="platform-coupons"),
    path("coupons/<uuid:coupon_id>/", CouponDetailView.as_view(), name="platform-coupon-detail"),
    # Dunning
    path("dunning/cases/", DunningCaseListView.as_view(), name="platform-dunning-cases"),
    path(
        "dunning/cases/<uuid:case_id>/<str:action>/",
        DunningCaseActionView.as_view(),
        name="platform-dunning-case-action",
    ),
    path("dunning/policies/", DunningPolicyView.as_view(), name="platform-dunning-policies"),
    # Governance
    path("staff/", StaffListView.as_view(), name="platform-staff"),
    path("staff/<uuid:staff_id>/", StaffDetailView.as_view(), name="platform-staff-detail"),
    path("audit/", AuditLogView.as_view(), name="platform-audit"),
    # Operations
    path("health/", HealthView.as_view(), name="platform-health"),
    path("settings/", PlatformSettingsView.as_view(), name="platform-settings"),
    path("settings/test-email/", PlatformTestEmailView.as_view(), name="platform-settings-test-email"),
    path("settings/test-ai/", PlatformTestAIView.as_view(), name="platform-settings-test-ai"),
    # Public: the signed-out product needs the illustration style.
    path("appearance/", PublicAppearanceView.as_view(), name="platform-appearance"),
    path("notifications/", NotificationListView.as_view(), name="platform-notifications"),
    path(
        "notifications/ack/",
        NotificationAckView.as_view(),
        name="platform-notifications-ack-all",
    ),
    path(
        "notifications/<uuid:notification_id>/ack/",
        NotificationAckView.as_view(),
        name="platform-notification-ack",
    ),
    # Saved views
    path("saved-views/", SavedViewListView.as_view(), name="platform-saved-views"),
    path("saved-views/<uuid:view_id>/", SavedViewDetailView.as_view(), name="platform-saved-view-detail"),
]
