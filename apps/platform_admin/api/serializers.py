"""Serializers for the platform workspace.

Two conventions worth stating:

* **Write serializers validate; read serializers project.** Most read paths
  here return already-shaped dicts from the selector layer, so they use plain
  `Serializer` subclasses for schema generation rather than `ModelSerializer`.
  That keeps the API contract independent of model field names, which matters
  because these payloads are consumed by an admin UI that should not have to
  change when a column is renamed.

* **Every destructive action carries a `reason`.** It is required at the
  serializer boundary, not just in the service, so the failure arrives as a
  400 with a field error the UI can attach to the textarea rather than a 422
  with a sentence.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.billing.invoicing_models import CreditKind, InvoiceStatus
from apps.billing.promotions_models import CouponDuration, CouponKind
from apps.platform_admin.rbac import PlatformCapability, PlatformRole


class ReasonMixin(serializers.Serializer):
    """Shared `reason` field for audited actions."""

    reason = serializers.CharField(min_length=5, max_length=1000, trim_whitespace=True)


# ------------------------------------------------------------------- identity
class PlatformStaffSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    name = serializers.CharField(source="user.full_name", read_only=True)
    role = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    require_mfa = serializers.BooleanField(read_only=True)
    allowed_ips = serializers.ListField(child=serializers.CharField(), read_only=True)
    extra_capabilities = serializers.ListField(child=serializers.CharField(), read_only=True)
    denied_capabilities = serializers.ListField(child=serializers.CharField(), read_only=True)
    capabilities = serializers.SerializerMethodField()
    last_seen_at = serializers.DateTimeField(read_only=True)
    note = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    def get_capabilities(self, obj) -> list[str]:
        return sorted(str(c) for c in obj.capabilities)


class AppointStaffSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=[r.value for r in PlatformRole])
    extra_capabilities = serializers.ListField(
        child=serializers.ChoiceField(choices=[c.value for c in PlatformCapability]),
        required=False,
        default=list,
    )
    denied_capabilities = serializers.ListField(
        child=serializers.ChoiceField(choices=[c.value for c in PlatformCapability]),
        required=False,
        default=list,
    )
    allowed_ips = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    require_mfa = serializers.BooleanField(default=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class UpdateStaffSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=[r.value for r in PlatformRole], required=False)
    extra_capabilities = serializers.ListField(
        child=serializers.ChoiceField(choices=[c.value for c in PlatformCapability]), required=False
    )
    denied_capabilities = serializers.ListField(
        child=serializers.ChoiceField(choices=[c.value for c in PlatformCapability]), required=False
    )
    allowed_ips = serializers.ListField(child=serializers.CharField(), required=False)
    require_mfa = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


# -------------------------------------------------------------------- tenants
class TenantRowSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    type = serializers.CharField()
    is_active = serializers.BooleanField()
    country = serializers.CharField(allow_blank=True)
    timezone = serializers.CharField()
    currency = serializers.CharField()
    locale = serializers.CharField()
    billing_email = serializers.CharField(allow_blank=True)
    owner_email = serializers.CharField(allow_blank=True)
    owner_name = serializers.CharField(allow_blank=True)
    member_count = serializers.IntegerField()
    plan_name = serializers.CharField(allow_blank=True)
    plan_id = serializers.CharField(allow_null=True)
    subscription_status = serializers.CharField(allow_blank=True)
    trial_ends_at = serializers.DateTimeField(allow_null=True)
    current_period_end = serializers.DateTimeField(allow_null=True)
    mrr_minor = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    last_activity = serializers.DateTimeField(allow_null=True)
    last_payment_at = serializers.DateTimeField(allow_null=True)
    storage_bytes = serializers.IntegerField()
    transaction_count = serializers.IntegerField()


class UpdateTenantSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, max_length=120)
    billing_email = serializers.EmailField(required=False, allow_blank=True)
    country = serializers.CharField(required=False, allow_blank=True, max_length=2)
    default_timezone = serializers.CharField(required=False, max_length=64)
    default_locale = serializers.CharField(required=False, max_length=10)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class ChangePlanSerializer(ReasonMixin):
    plan_id = serializers.UUIDField()


class ComplimentarySerializer(ReasonMixin):
    plan_id = serializers.UUIDField()
    months = serializers.IntegerField(min_value=1, max_value=36, default=1)


class ExtendTrialSerializer(ReasonMixin):
    days = serializers.IntegerField(min_value=1, max_value=365)


class CancelSubscriptionSerializer(ReasonMixin):
    immediate = serializers.BooleanField(default=False)


class ApplyCreditSerializer(ReasonMixin):
    amount_minor = serializers.IntegerField(min_value=1)
    currency = serializers.CharField(max_length=3)
    kind = serializers.ChoiceField(choices=CreditKind.values, default=CreditKind.GOODWILL)


# -------------------------------------------------------------- impersonation
class StartImpersonationSerializer(serializers.Serializer):
    # Longer minimum than other reasons: this one grants access to a family's
    # financial records, and "support" is not an explanation.
    reason = serializers.CharField(min_length=10, max_length=1000)
    read_only = serializers.BooleanField(default=True)
    subject_user_id = serializers.UUIDField(required=False, allow_null=True)
    ttl_minutes = serializers.IntegerField(required=False, min_value=5, max_value=480)


class ImpersonationGrantSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    tenant_id = serializers.UUIDField(read_only=True)
    staff_email = serializers.CharField(source="staff.user.email", read_only=True)
    reason = serializers.CharField(read_only=True)
    read_only = serializers.BooleanField(read_only=True)
    status = serializers.CharField(read_only=True)
    expires_at = serializers.DateTimeField(read_only=True)
    ended_at = serializers.DateTimeField(read_only=True)
    request_count = serializers.IntegerField(read_only=True)
    ip_address = serializers.CharField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)


# -------------------------------------------------------------------- billing
class InvoiceSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    number = serializers.CharField(read_only=True)
    tenant_id = serializers.UUIDField(read_only=True)
    # An invoice list that names no customer is a list of amounts. The operator
    # reading it has to open every row to find out whose it is, which is the
    # one thing they came to the screen already knowing they needed.
    #
    # Resolved through `tenant_names` in the serializer context rather than a
    # relation: `tenant_id` is a bare UUID column, not a ForeignKey, because
    # billing rows are isolated by RLS and must not join across the app
    # boundary. `_with_tenant_names` in views.py builds the map in one query.
    tenant_name = serializers.SerializerMethodField()

    def get_tenant_name(self, obj) -> str:
        return self.context.get("tenant_names", {}).get(obj.tenant_id, "")

    status = serializers.CharField(read_only=True)
    currency = serializers.CharField(read_only=True)
    issue_date = serializers.DateField(read_only=True)
    due_date = serializers.DateField(read_only=True)
    paid_at = serializers.DateTimeField(read_only=True)
    subtotal_minor = serializers.IntegerField(read_only=True)
    discount_minor = serializers.IntegerField(read_only=True)
    credit_minor = serializers.IntegerField(read_only=True)
    tax_minor = serializers.IntegerField(read_only=True)
    tax_label = serializers.CharField(read_only=True)
    total_minor = serializers.IntegerField(read_only=True)
    amount_paid_minor = serializers.IntegerField(read_only=True)
    amount_due_minor = serializers.IntegerField(read_only=True)
    billing_name = serializers.CharField(read_only=True)
    billing_email = serializers.CharField(read_only=True)
    billing_country = serializers.CharField(read_only=True)
    line_items = serializers.SerializerMethodField()

    def get_line_items(self, obj) -> list[dict]:
        return [
            {
                "description": li.description,
                "quantity": li.quantity,
                "unit_amount_minor": li.unit_amount_minor,
                "amount_minor": li.amount_minor,
                "period_start": li.period_start,
                "period_end": li.period_end,
            }
            for li in obj.line_items.all()
        ]


class SendInvoiceSerializer(serializers.Serializer):
    """Optional override address — support occasionally needs to send a copy to
    an accountant or a corrected address without editing the invoice, which is
    frozen once issued."""

    to = serializers.EmailField(required=False, allow_blank=True, default="")
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)


class InvoiceFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=InvoiceStatus.values, required=False)
    tenant_id = serializers.UUIDField(required=False)
    currency = serializers.CharField(required=False, max_length=3)


class RefundSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    tenant_id = serializers.UUIDField(read_only=True)
    payment_id = serializers.UUIDField(read_only=True)
    amount_minor = serializers.IntegerField(read_only=True)
    currency = serializers.CharField(read_only=True)
    reason = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    requested_by_email = serializers.SerializerMethodField()
    approved_by_email = serializers.SerializerMethodField()
    approved_at = serializers.DateTimeField(read_only=True)
    completed_at = serializers.DateTimeField(read_only=True)
    decision_note = serializers.CharField(read_only=True)
    provider = serializers.CharField(read_only=True)
    provider_ref = serializers.CharField(read_only=True)
    failure_reason = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    def get_requested_by_email(self, obj) -> str:
        return obj.requested_by.email if obj.requested_by_id else ""

    def get_approved_by_email(self, obj) -> str:
        return obj.approved_by.email if obj.approved_by_id else ""


class RequestRefundSerializer(serializers.Serializer):
    payment_id = serializers.UUIDField()
    amount_minor = serializers.IntegerField(required=False, min_value=1, allow_null=True)
    reason = serializers.CharField(min_length=5, max_length=1000)


class DecideRefundSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)


class CouponSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    code = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    kind = serializers.CharField(read_only=True)
    value = serializers.IntegerField(read_only=True)
    currency = serializers.CharField(read_only=True)
    duration = serializers.CharField(read_only=True)
    duration_in_months = serializers.IntegerField(read_only=True, allow_null=True)
    allowed_countries = serializers.ListField(child=serializers.CharField(), read_only=True)
    starts_at = serializers.DateTimeField(read_only=True)
    expires_at = serializers.DateTimeField(read_only=True)
    max_redemptions = serializers.IntegerField(read_only=True, allow_null=True)
    max_redemptions_per_tenant = serializers.IntegerField(read_only=True)
    redemption_count = serializers.IntegerField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    is_live = serializers.BooleanField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class WriteCouponSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=40)
    name = serializers.CharField(max_length=120)
    description = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    kind = serializers.ChoiceField(choices=CouponKind.values)
    value = serializers.IntegerField(min_value=1)
    currency = serializers.CharField(required=False, allow_blank=True, default="", max_length=3)
    duration = serializers.ChoiceField(choices=CouponDuration.values, default=CouponDuration.ONCE)
    duration_in_months = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    plan_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    allowed_countries = serializers.ListField(
        child=serializers.CharField(max_length=2), required=False, default=list
    )
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    max_redemptions = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    max_redemptions_per_tenant = serializers.IntegerField(default=1, min_value=1)
    is_active = serializers.BooleanField(default=True)

    def validate(self, attrs):
        # A percentage above 100% would produce a negative invoice total, and
        # a fixed discount with no currency cannot be safely compared to one.
        if attrs["kind"] == CouponKind.PERCENT and attrs["value"] > 10_000:
            raise serializers.ValidationError(
                {"value": "A percentage discount cannot exceed 100% (10000 bps)."}
            )
        if attrs["kind"] == CouponKind.FIXED and not attrs.get("currency"):
            raise serializers.ValidationError({"currency": "A fixed-amount discount needs a currency."})
        if attrs["duration"] == CouponDuration.REPEATING and not attrs.get("duration_in_months"):
            raise serializers.ValidationError(
                {"duration_in_months": "A repeating discount needs a duration in months."}
            )
        starts, expires = attrs.get("starts_at"), attrs.get("expires_at")
        if starts and expires and expires <= starts:
            raise serializers.ValidationError({"expires_at": "The end must come after the start."})
        return attrs


class PaymentRowSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    tenant_id = serializers.UUIDField(read_only=True)
    amount_minor = serializers.IntegerField(read_only=True)
    currency = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    provider = serializers.CharField(read_only=True)
    provider_ref = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    failure_reason = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class ReconcilePaymentSerializer(ReasonMixin):
    payment_id = serializers.UUIDField()
    invoice_id = serializers.UUIDField()


# -------------------------------------------------------------------- dunning
class PlanUpdateSerializer(serializers.Serializer):
    """Edits to a catalogue plan.

    `tier`, `interval` and `currency` are absent by design: together they are
    the plan's identity (the unique constraint), and every subscriber's
    entitlements resolve through `tier`. A different price point in a different
    currency is a *new plan row*, not an edit — editing identity in place
    would silently reinterpret what existing customers are paying for.
    """

    name = serializers.CharField(max_length=80, required=False)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True)
    price_minor = serializers.IntegerField(min_value=0, required=False)
    max_members = serializers.IntegerField(min_value=1, required=False)
    max_accounts = serializers.IntegerField(min_value=1, required=False)
    ai_insights = serializers.BooleanField(required=False)
    features = serializers.ListField(child=serializers.CharField(), required=False)
    is_active = serializers.BooleanField(required=False)
    sort_order = serializers.IntegerField(min_value=0, required=False)
    reason = serializers.CharField(min_length=5, max_length=500)

    def validate_features(self, value):
        from apps.billing.plan_catalogue import UNIVERSAL, PlanFeature

        known = {str(f) for f in PlanFeature}
        unknown = [v for v in value if v not in known]
        if unknown:
            # Universal features are named separately: they are always on, so
            # putting one in an override is a category error, not a typo.
            universal = [v for v in unknown if v in UNIVERSAL]
            if universal:
                raise serializers.ValidationError(
                    f"{', '.join(universal)}: universal features are included in every "
                    "plan and cannot be listed as overrides."
                )
            raise serializers.ValidationError(f"Unknown features: {', '.join(unknown)}.")
        return sorted(set(value))


class DunningCaseSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    tenant_id = serializers.UUIDField(read_only=True)
    tenant_name = serializers.SerializerMethodField()
    subscription_id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    amount_minor = serializers.IntegerField(read_only=True)
    currency = serializers.CharField(read_only=True)
    opened_at = serializers.DateTimeField(read_only=True)
    grace_ends_at = serializers.DateTimeField(read_only=True)
    suspend_at = serializers.DateTimeField(read_only=True)
    resolved_at = serializers.DateTimeField(read_only=True)
    attempts_made = serializers.IntegerField(read_only=True)
    last_failure_reason = serializers.CharField(read_only=True)
    next_attempt_at = serializers.SerializerMethodField()

    def get_tenant_name(self, obj) -> str:
        return self.context.get("tenant_names", {}).get(obj.tenant_id, "")

    def get_next_attempt_at(self, obj):
        nxt = obj.attempts.filter(outcome="scheduled").order_by("scheduled_for").first()
        return nxt.scheduled_for if nxt else None


class DunningPolicySerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True, default="")
    retry_offsets_days = serializers.ListField(child=serializers.IntegerField(min_value=0))
    reminder_offsets_days = serializers.ListField(
        child=serializers.IntegerField(min_value=0), required=False, default=list
    )
    grace_period_days = serializers.IntegerField(min_value=0)
    suspend_after_days = serializers.IntegerField(min_value=0)
    abandon_after_days = serializers.IntegerField(min_value=0)
    send_email = serializers.BooleanField(default=True)
    send_sms = serializers.BooleanField(default=False)
    is_default = serializers.BooleanField(default=False)
    is_active = serializers.BooleanField(default=True)


# ---------------------------------------------------------------------- audit
class AuditLogSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    actor_id = serializers.UUIDField(read_only=True, allow_null=True)
    actor_email = serializers.CharField(read_only=True)
    actor_role = serializers.CharField(read_only=True)
    action = serializers.CharField(read_only=True)
    module = serializers.CharField(read_only=True)
    target_type = serializers.CharField(read_only=True)
    target_id = serializers.UUIDField(read_only=True, allow_null=True)
    tenant_id = serializers.UUIDField(read_only=True, allow_null=True)
    changes = serializers.JSONField(read_only=True)
    reason = serializers.CharField(read_only=True)
    ip_address = serializers.CharField(read_only=True, allow_null=True)
    user_agent = serializers.CharField(read_only=True)
    request_id = serializers.CharField(read_only=True)
    context = serializers.JSONField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


# -------------------------------------------------------------- notifications
class PlatformNotificationSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    category = serializers.CharField(read_only=True)
    severity = serializers.CharField(read_only=True)
    title = serializers.CharField(read_only=True)
    body = serializers.CharField(read_only=True)
    tenant_id = serializers.UUIDField(read_only=True, allow_null=True)
    data = serializers.JSONField(read_only=True)
    acknowledged_at = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class WriteSettingSerializer(serializers.Serializer):
    """One setting change.

    `value` is untyped here on purpose — the store coerces by the setting's
    declared kind, which is the single place that knows what a given key means.
    Duplicating that as per-field serializers would let the two disagree.
    """

    key = serializers.CharField(max_length=80)
    value = serializers.JSONField(allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)


class SavedViewSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    surface = serializers.CharField(max_length=40)
    name = serializers.CharField(max_length=80)
    filters = serializers.JSONField(required=False, default=dict)
    is_shared = serializers.BooleanField(default=False)
    created_at = serializers.DateTimeField(read_only=True)
