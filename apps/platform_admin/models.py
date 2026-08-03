"""Platform administration domain.

Nothing here is tenant-owned, so none of it inherits `TenantOwnedModel` and
none of it is RLS-protected — these rows describe the *operator* of the
platform, not any customer of it. Where a row refers to a tenant it does so
with a plain `tenant_id` UUID, and the reference is informational: the platform
console reads control-plane facts about a workspace (plan, status, seat count)
and never its financial rows.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.ids import uuid7
from apps.common.models import TimeStampedModel, UUIDModel

from .rbac import PlatformRole, capabilities_for


def _role_choices():
    return [(r.value, r.label) for r in PlatformRole]


class PlatformStaff(UUIDModel, TimeStampedModel):
    """Grants a user authority over the platform itself.

    Separate from `User.is_staff`/`is_superuser` on purpose. Django's flags are
    coarse (they gate the Django admin wholesale) and carry no capability
    detail, so they can't express "this person may approve refunds but may not
    impersonate". Keeping platform authority in its own table also means
    revoking it is one row, and that every grant carries who granted it and
    when — which `is_superuser = True` never does.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="platform_staff"
    )
    role = models.CharField(max_length=32, choices=_role_choices())
    #: Per-person capability overrides on top of the role bundle. Stored as
    #: plain lists of capability strings; validated by the service layer
    #: against the PlatformCapability enum so a typo fails loudly.
    extra_capabilities = models.JSONField(default=list, blank=True)
    denied_capabilities = models.JSONField(default=list, blank=True)

    is_active = models.BooleanField(default=True)
    #: Optional CIDR/IP allowlist. Empty list = no restriction. Enforced by
    #: `IsPlatformStaff`, so it covers every platform endpoint uniformly
    #: rather than being remembered per-view.
    allowed_ips = models.JSONField(default=list, blank=True)
    #: Platform staff handle other people's money; requiring a second factor is
    #: policy, not preference. Enforced at permission time.
    require_mfa = models.BooleanField(default=True)

    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platform_grants_made",
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["is_active", "role"])]
        verbose_name = "platform staff member"
        verbose_name_plural = "platform staff"

    def __str__(self) -> str:
        return f"{self.user_id} [{self.role}]"

    @property
    def capabilities(self) -> frozenset:
        return capabilities_for(
            self.role, extra=self.extra_capabilities, denied=self.denied_capabilities
        )

    def has(self, capability) -> bool:
        return capability in self.capabilities


class PlatformAuditLog(models.Model):
    """Append-only record of every administrative action.

    Distinct from `apps.common.audit.AuditLog`, which is tenant-scoped and
    records what a *customer* did inside their own workspace. This table
    records what an *employee* did to a customer, which has different
    retention, different readers (compliance, not the account owner) and a
    nullable tenant (plenty of platform actions — appointing staff, editing a
    coupon — belong to no tenant at all).

    Actor identity is denormalized to `actor_email` alongside the FK-less
    `actor_id`: an audit trail that becomes anonymous when an employee's user
    row is deleted has failed at the one job it has.

    Immutability is enforced by a database trigger (see migration 0002), not by
    application convention — the same mechanism that protects the ledger.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    actor_id = models.UUIDField(null=True, blank=True, editable=False)  # null = system/automation
    actor_email = models.CharField(max_length=254, blank=True, default="", editable=False)
    actor_role = models.CharField(max_length=32, blank=True, default="", editable=False)

    #: Dotted action name, e.g. "tenant.suspended", "refund.approved".
    action = models.CharField(max_length=64)
    #: Coarse grouping for filtering the audit UI ("tenants", "billing", ...).
    module = models.CharField(max_length=32, blank=True, default="")
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.UUIDField(null=True, blank=True)
    #: Which customer this touched, when applicable.
    tenant_id = models.UUIDField(null=True, blank=True, db_index=True)

    #: {"field": [before, after], ...} — the same shape as the tenant audit log
    #: so one viewer component renders both.
    changes = models.JSONField(default=dict, blank=True)
    #: Free-text justification. Required by the service layer for any
    #: destructive or money-moving action; an audit row that says *what* but
    #: never *why* is only half a record.
    reason = models.TextField(blank=True, default="")

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True, default="")
    request_id = models.CharField(max_length=64, blank=True, default="")
    #: Anything else worth keeping (impersonation session id, provider refs).
    context = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="pa_audit_recent_idx"),
            models.Index(fields=["actor_id", "-created_at"], name="pa_audit_actor_idx"),
            models.Index(fields=["tenant_id", "-created_at"], name="pa_audit_tenant_idx"),
            models.Index(fields=["module", "-created_at"], name="pa_audit_module_idx"),
            models.Index(fields=["action", "-created_at"], name="pa_audit_action_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.action} by {self.actor_email or 'system'}"


class ImpersonationStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    ENDED = "ended", "Ended"
    EXPIRED = "expired", "Expired"
    REVOKED = "revoked", "Revoked"


def _default_impersonation_expiry():
    minutes = getattr(settings, "PLATFORM_IMPERSONATION_TTL_MINUTES", 30)
    return timezone.now() + timedelta(minutes=minutes)


def _generate_grant_secret() -> str:
    return secrets.token_urlsafe(32)


class ImpersonationGrant(UUIDModel, TimeStampedModel):
    """A time-boxed, audited licence for one staff member to act inside one
    tenant.

    Impersonation is the single mechanism by which platform staff can reach
    customer financial data, so it is modelled as an explicit, revocable grant
    rather than a flag on a token. The consequences of that choice:

    * It expires on its own (`expires_at`), so an abandoned session closes
      itself rather than lingering until logout.
    * It can be revoked centrally while in flight — a token, once issued,
      cannot be recalled, but every impersonated request re-checks this row.
    * It is read-only by default. Acting *as* a customer with write authority
      is occasionally necessary and always a bigger decision, so `read_only`
      must be deliberately turned off and is recorded when it is.
    * The reason is mandatory at the model's usage site (see services), and the
      grant is useless without it.
    """

    staff = models.ForeignKey(PlatformStaff, on_delete=models.CASCADE, related_name="impersonations")
    tenant_id = models.UUIDField(db_index=True)
    #: The membership/user whose seat is being borrowed, when the operator
    #: needs to see the workspace as a specific person sees it.
    subject_user_id = models.UUIDField(null=True, blank=True)

    reason = models.TextField()
    read_only = models.BooleanField(default=True)
    status = models.CharField(
        max_length=16, choices=ImpersonationStatus.choices, default=ImpersonationStatus.ACTIVE
    )

    #: Only the hash is stored, following the same discipline as invitations
    #: and password-reset tokens: a database dump must not yield a usable
    #: impersonation credential.
    token_hash = models.CharField(max_length=64, unique=True, editable=False)

    expires_at = models.DateTimeField(default=_default_impersonation_expiry)
    ended_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="impersonations_revoked",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    #: Rolling count of requests made under this grant, for the audit view.
    request_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["staff", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"impersonation:{self.staff_id}->{self.tenant_id} ({self.status})"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_usable(self) -> bool:
        return self.status == ImpersonationStatus.ACTIVE and not self.is_expired


class PlatformAlertSeverity(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    CRITICAL = "critical", "Critical"


class PlatformNotification(UUIDModel, TimeStampedModel):
    """Operational notice for platform staff (failed payment, queue backlog,
    expiring trial, storage threshold).

    Deliberately a separate table from `apps.notifications.Notification`, which
    is tenant-scoped and RLS-protected: a platform alert has no tenant to be
    scoped to, and making the customer-facing table nullable-tenant would
    punch a hole in exactly the isolation guarantee it exists to provide.

    `dedupe_key` gives the same idempotency the customer notification model
    has — a sweep that runs every five minutes must not produce a wall of
    identical "queue is backed up" rows.
    """

    category = models.CharField(max_length=40)  # e.g. "payment.failed", "queue.backlog"
    severity = models.CharField(
        max_length=10, choices=PlatformAlertSeverity.choices, default=PlatformAlertSeverity.INFO
    )
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=600, blank=True, default="")
    tenant_id = models.UUIDField(null=True, blank=True, db_index=True)
    subject_type = models.CharField(max_length=40, blank=True, default="")
    subject_id = models.UUIDField(null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)

    dedupe_key = models.CharField(max_length=200, blank=True, default="")
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platform_notifications_acked",
    )
    delivered_channels = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["dedupe_key"],
                name="uniq_platform_notification_dedupe",
                condition=~models.Q(dedupe_key=""),
            )
        ]
        indexes = [
            models.Index(fields=["-created_at"], name="pa_notif_recent_idx"),
            models.Index(
                fields=["severity", "-created_at"],
                name="pa_notif_open_idx",
                condition=models.Q(acknowledged_at__isnull=True),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.category}: {self.title}"


class SavedView(UUIDModel, TimeStampedModel):
    """A named set of filters on a platform list (tenants, payments, audit).

    Operators return to the same handful of questions — "trials expiring this
    week", "past-due enterprise accounts" — and retyping filters is friction
    that pushes people back to writing SQL against production. Stored as an
    opaque JSON blob so adding a filter to a list never requires a migration
    here; the owning list is identified by `surface`.
    """

    staff = models.ForeignKey(PlatformStaff, on_delete=models.CASCADE, related_name="saved_views")
    surface = models.CharField(max_length=40)  # "tenants", "payments", "audit", ...
    name = models.CharField(max_length=80)
    filters = models.JSONField(default=dict, blank=True)
    #: Shared views appear for every staff member; personal ones don't.
    is_shared = models.BooleanField(default=False)

    class Meta:
        ordering = ["surface", "name"]
        constraints = [
            models.UniqueConstraint(fields=["staff", "surface", "name"], name="uniq_saved_view_name"),
        ]
        indexes = [models.Index(fields=["surface", "is_shared"])]

    def __str__(self) -> str:
        return f"{self.surface}:{self.name}"


class TenantUsageSnapshot(UUIDModel, TimeStampedModel):
    """Point-in-time usage telemetry for one workspace.

    This exists because of the RLS boundary, not in spite of it. Attachment
    rows and transaction counts live in tenant-scoped, RLS-protected tables
    that the platform console cannot read — and should not be able to read.
    A background task binds each tenant's context in turn, aggregates *counts
    and byte totals only*, and writes the result here, where the console can
    see it. No customer financial content ever crosses the boundary; only
    magnitudes do.

    This is not a violation of the product's "no persisted projections" rule.
    That rule governs financial state, which must always be read from the
    ledger. A usage snapshot is an observation with a timestamp — it is
    *supposed* to be historical, and recomputing last month's storage figure
    from today's data would destroy the trend it exists to show.
    """

    tenant_id = models.UUIDField(db_index=True)
    captured_at = models.DateTimeField(db_index=True)

    member_count = models.PositiveIntegerField(default=0)
    account_count = models.PositiveIntegerField(default=0)
    transaction_count = models.PositiveIntegerField(default=0)
    attachment_count = models.PositiveIntegerField(default=0)
    storage_bytes = models.BigIntegerField(default=0)
    #: Requests attributed to this workspace since the previous snapshot.
    api_calls = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-captured_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "captured_at"], name="uniq_usage_snapshot_per_capture"
            )
        ]
        indexes = [models.Index(fields=["tenant_id", "-captured_at"], name="pa_usage_latest_idx")]

    def __str__(self) -> str:
        return f"usage:{self.tenant_id}@{self.captured_at:%Y-%m-%d}"


# Concrete model defined in a sibling module, registered here so migrations see
# it. Same pattern as apps/users/models.py.
from .settings_store import PlatformSetting, SettingKind  # noqa: E402,F401
