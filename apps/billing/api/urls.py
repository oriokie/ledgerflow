from django.urls import path

from .views import (
    PaymentHistoryView,
    PaymentMethodDetailView,
    PaymentMethodView,
    PlanListView,
    SubscriptionCancelView,
    SubscriptionRetryView,
    SubscriptionView,
    WebhookView,
)

urlpatterns = [
    path("plans/", PlanListView.as_view(), name="billing-plans"),
    path("subscription/", SubscriptionView.as_view(), name="billing-subscription"),
    path("subscription/cancel/", SubscriptionCancelView.as_view(), name="billing-subscription-cancel"),
    path("subscription/retry/", SubscriptionRetryView.as_view(), name="billing-subscription-retry"),
    path("payment-methods/", PaymentMethodView.as_view(), name="billing-payment-methods"),
    path(
        "payment-methods/<uuid:method_id>/",
        PaymentMethodDetailView.as_view(),
        name="billing-payment-method-detail",
    ),
    path("payments/", PaymentHistoryView.as_view(), name="billing-payments"),
    path("webhooks/<str:provider_key>/", WebhookView.as_view(), name="billing-webhook"),
]
