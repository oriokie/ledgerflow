from __future__ import annotations

from rest_framework import serializers

from ..models import Payment, PaymentMethod, Plan, Subscription


class PlanSerializer(serializers.ModelSerializer):
    #: What the plan actually includes — tier defaults plus this row's
    #: overrides, labelled. This is what makes "the plan determines the
    #: features" true on every surface at once: the pricing page, the in-app
    #: upgrade screen and the console all read this field instead of keeping
    #: their own idea of what a tier contains.
    resolved_features = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = [
            "id",
            "tier",
            "name",
            "description",
            "price_minor",
            "currency",
            "interval",
            "max_members",
            "max_accounts",
            "ai_insights",
            "features",
            "resolved_features",
        ]

    def get_resolved_features(self, plan) -> list[dict]:
        from ..plan_catalogue import label_for, resolved_features

        return [{"key": key, "label": label_for(key)} for key in resolved_features(plan)]


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    is_current = serializers.BooleanField(read_only=True)

    class Meta:
        model = Subscription
        fields = [
            "id",
            "plan",
            "status",
            "is_current",
            "current_period_start",
            "current_period_end",
            "cancel_at_period_end",
            "canceled_at",
            "trial_end",
            "provider",
        ]


class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = [
            "id",
            "kind",
            "is_default",
            "brand",
            "last4",
            "exp_month",
            "exp_year",
            "phone_masked",
            "provider",
            "created_at",
        ]


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "id",
            "amount_minor",
            "currency",
            "status",
            "provider",
            "description",
            "failure_reason",
            "created_at",
        ]


class SubscribeSerializer(serializers.Serializer):
    plan_id = serializers.UUIDField()
    payment_method_id = serializers.UUIDField(required=False, allow_null=True)


class AddPaymentMethodSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=["stripe", "mpesa"])
    # Client-side token (Stripe.js payment-method id, or an M-PESA phone number).
    # Raw card data never reaches the server.
    token = serializers.CharField(max_length=255)
    kind = serializers.ChoiceField(choices=["card", "mpesa"])
    make_default = serializers.BooleanField(default=True)


class CancelSerializer(serializers.Serializer):
    at_period_end = serializers.BooleanField(default=True)
