"""Tenancy context.

A "tenant" is any shared financial workspace — a `type` distinguishes a
single user's personal space, a couple/family household, or a broader
organization (e.g. a small business, or a household with a hired
accountant). All three share one model rather than parallel schemas: they
differ in policy (seat limits, default roles, billing) and presentation, not
in the isolation mechanism, and a single Tenant/Membership pair keeps the
already-substantial RLS + service-layer isolation machinery from having to
be duplicated per tenant "kind".
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel as TimestampedModel
from apps.common.models import UUIDModel


class TenantType(models.TextChoices):
    PERSONAL = "personal", "Personal"
    HOUSEHOLD = "household", "Household"
    ORGANIZATION = "organization", "Organization"


class Role(models.TextChoices):
    OWNER = "owner", "Owner"  # billing + can delete workspace
    ADMIN = "admin", "Admin"  # manage members + all financial data
    MEMBER = "member", "Member"  # read/write financial data
    VIEWER = "viewer", "Viewer"  # read-only (e.g. an accountant)


class Tenant(UUIDModel, TimestampedModel):
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=16, choices=TenantType.choices, default=TenantType.PERSONAL)
    # Config-over-hardcode: workspace defaults for localization live on the tenant.
    base_currency = models.CharField(max_length=3, default="USD")
    #: When an owner actually *chose* the base currency, as against inheriting
    #: the "USD" default above.
    #:
    #: The default has to be some currency, so `base_currency` alone cannot
    #: distinguish "the user picked dollars" from "nobody has been asked yet" —
    #: and that difference is the whole point of putting the choice in first-run
    #: setup. Null means unasked, and the setup checklist keeps asking.
    #:
    #: Nullable rather than a boolean with a default: an existing workspace has
    #: genuinely never been asked, and backfilling it to True would silently
    #: assert a choice its owner never made.
    base_currency_chosen_at = models.DateTimeField(null=True, blank=True)
    default_locale = models.CharField(max_length=10, default="en-US")
    default_timezone = models.CharField(max_length=64, default="UTC")
    billing_email = models.EmailField(blank=True, default="")
    #: ISO-3166 alpha-2. Blank means "not stated"; `resolved_country` falls
    #: back to the locale's region subtag so revenue-by-country reporting
    #: works for the workspaces that existed before this field did, without a
    #: backfill that would invent data for anyone who never told us.
    country = models.CharField(max_length=2, blank=True, default="")
    is_active = models.BooleanField(default=True)
    #: Per-workspace opt-out for AI-touched insights and narration, independent
    #: of whatever the deployment has configured. Provider, model and API key
    #: stay deployment-level (env vars) deliberately — a member choosing where
    #: the household's financial data gets sent would be deciding that for
    #: everyone else. Whether *this* workspace's data goes through a model at
    #: all is a different, narrower decision, and one an owner should be able
    #: to make without touching the deployment. Defaults to True so nothing
    #: changes for an existing workspace on a deployment that already has AI
    #: configured.
    ai_enabled = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["is_active"]), models.Index(fields=["type"])]

    def __str__(self) -> str:
        return self.name

    @property
    def resolved_country(self) -> str:
        """Stated country, else the region subtag of the locale, else blank."""
        if self.country:
            return self.country.upper()
        if "-" in (self.default_locale or ""):
            region = self.default_locale.rsplit("-", 1)[-1]
            if len(region) == 2 and region.isalpha():
                return region.upper()
        return ""


class Membership(UUIDModel, TimestampedModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "user"], name="uniq_tenant_user"),
        ]
        indexes = [models.Index(fields=["user", "tenant"])]

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.tenant_id} ({self.role})"


class InvitationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    REVOKED = "revoked", "Revoked"


def _generate_invitation_token() -> str:
    return secrets.token_urlsafe(32)


def _default_invitation_expiry():
    return timezone.now() + timedelta(days=getattr(settings, "INVITATION_TTL_DAYS", 7))


class Invitation(UUIDModel, TimestampedModel):
    """Not RLS-protected — same reasoning as `Membership`/`Tenant`: this is
    tenancy control-plane data, written and read around the edges of a tenant
    context (an invitee has no membership yet), not user financial data.
    Isolation is enforced at the service/permission layer instead.

    The raw token is returned to the caller exactly once (at creation) and
    never stored — only its hash is, following the same at-rest-secret
    discipline as passwords and MFA backup codes. A leaked DB dump is not
    enough to accept someone else's invitation.
    """

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    status = models.CharField(
        max_length=16, choices=InvitationStatus.choices, default=InvitationStatus.PENDING
    )
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="sent_invitations"
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_invitations",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(default=_default_invitation_expiry)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["email", "status"]),
        ]

    def __str__(self) -> str:
        return f"invite:{self.email}->{self.tenant_id} ({self.status})"

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    @property
    def is_pending(self) -> bool:
        return self.status == InvitationStatus.PENDING and not self.is_expired


class TenantAISettings(UUIDModel, TimestampedModel):
    """A workspace's own choice of model.

    `Tenant.ai_enabled` lets an owner decline AI. This lets them *substitute*
    it, which is the request that follows immediately: a household that would
    rather run a local model than send anything to a vendor, or one that has
    its own account with a provider and would sooner spend its own quota.

    Still the owner's decision, not a member's — the reasoning on
    `Tenant.ai_enabled` applies unchanged, because choosing the destination for
    a household's finances is a choice made for everyone in the household.
    Enforced in apps/tenancy/api, not here.

    Absent or blank means "no override": resolution falls through to the
    platform's configuration and then the environment's. The API key is
    encrypted with FIELD_ENCRYPTION_KEY, the same key protecting TOTP secrets,
    and is never read back through the API — a workspace can replace its key,
    nobody can retrieve one.
    """

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="ai_settings")
    #: Blank means no override. Matches PROVIDER_PRESETS keys in apps.intelligence.llm.
    provider = models.CharField(max_length=32, blank=True, default="")
    model = models.CharField(max_length=120, blank=True, default="")
    #: Only meaningful for self-hosted endpoints; presets supply the rest.
    base_url = models.URLField(blank=True, default="")
    encrypted_api_key = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "workspace AI settings"
        verbose_name_plural = "workspace AI settings"

    def __str__(self) -> str:
        return f"ai:{self.tenant_id}:{self.provider or 'inherit'}"

    def set_api_key(self, raw: str) -> None:
        from apps.common.crypto import encrypt_str

        self.encrypted_api_key = encrypt_str(raw) if raw else ""

    @property
    def api_key(self) -> str:
        if not self.encrypted_api_key:
            return ""
        from apps.common.crypto import decrypt_str

        try:
            return decrypt_str(self.encrypted_api_key)
        except Exception:  # noqa: BLE001
            # A key encrypted under a rotated FIELD_ENCRYPTION_KEY is
            # unreadable, not a reason to fail every AI call in the workspace.
            return ""
