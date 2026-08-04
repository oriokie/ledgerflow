"""Runtime-editable platform configuration.

The hard question this module answers is **which settings belong in a database
an admin can edit, and which must stay in the environment.**

The split used here
-------------------
*Operational settings* — which payment providers are offered, the invoice
issuer's name and tax ID, default tax rate, whether AI is available at all,
which model to use — go in the database. They are commercial decisions a
finance or ops person makes on a Tuesday, and requiring a deploy for each one
guarantees they get made badly or not at all.

*Secrets* — API keys, webhook signing secrets, private keys — stay in the
environment by default. Putting a live Stripe secret key behind a web form
changes the platform's security posture in ways that are easy to understate:

* A database dump becomes a live payment credential. Backups, read replicas and
  analytics exports all inherit that.
* Any XSS or CSRF hole in the admin console becomes credential theft rather
  than an ugly-but-bounded incident.
* Secrets stop being rotatable by the deployment pipeline, which is where
  rotation is actually automated.

But refusing outright is its own failure: a deployment that cannot rotate a key
without a release is a deployment that does not rotate keys. So a secret *may*
be stored here, encrypted with `FIELD_ENCRYPTION_KEY` (the same key that
protects TOTP secrets, and deliberately not `SECRET_KEY`), as an explicit
opt-in. The resolution order is:

    database override (if set)  ->  environment  ->  built-in default

and the API never returns a stored secret's value — only whether one is set and
where it came from. An operator can replace a key; nobody can read one back out
through the console.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import models

from apps.common.crypto import decrypt_str, encrypt_str
from apps.common.models import TimeStampedModel, UUIDModel

logger = logging.getLogger("ledgerflow.platform.settings")


class SettingKind(models.TextChoices):
    STRING = "string", "Text"
    BOOLEAN = "boolean", "Yes/No"
    INTEGER = "integer", "Number"
    JSON = "json", "Structured"
    SECRET = "secret", "Secret"


@dataclass(frozen=True)
class SettingSpec:
    """A setting the console is allowed to touch.

    An allowlist rather than free-form key/value storage. Without it, the
    settings table becomes a second, undocumented configuration system that
    nothing validates and no one can enumerate — and a typo'd key silently does
    nothing rather than failing.
    """

    key: str
    kind: str
    group: str
    label: str
    help: str
    #: The Django setting this shadows, when there is one. Used to show the
    #: operator what the environment currently provides.
    env_setting: str | None = None
    default: Any = None
    #: Secrets are write-only through the API.
    write_only: bool = False
    #: Permitted values, for settings that are a closed set rather than free
    #: text. Without this a typo'd style name would be stored happily and the
    #: only symptom would be an interface that silently stopped rendering
    #: illustrations — a failure with no error attached to it.
    choices: tuple[str, ...] = ()


#: Every setting the platform console may read or write.
SPECS: tuple[SettingSpec, ...] = (
    # ---------------------------------------------------------- invoicing
    SettingSpec(
        "appearance.illustration_style",
        SettingKind.STRING,
        "appearance",
        "Illustration style",
        "Which illustration set the product draws with. Applies everywhere "
        "illustrations appear, including the signed-out landing page. "
        "'motion' animates; it holds still for anyone who has asked their "
        "system to reduce motion, and inside the application it is static.",
        default="clay",
        choices=("clay", "doodle", "motion"),
    ),
    # ---------------------------------------------------------- invoicing
    SettingSpec(
        "invoice.issuer_name",
        SettingKind.STRING,
        "invoicing",
        "Issuer name",
        "The legal entity that issues invoices.",
        default="LedgerFlow",
    ),
    SettingSpec(
        "invoice.issuer_address",
        SettingKind.STRING,
        "invoicing",
        "Issuer address",
        "Printed on every invoice.",
        default="",
    ),
    SettingSpec(
        "invoice.issuer_email",
        SettingKind.STRING,
        "invoicing",
        "Billing contact",
        "Where invoice replies go.",
        default="billing@ledgerflow.app",
    ),
    SettingSpec(
        "invoice.issuer_tax_id",
        SettingKind.STRING,
        "invoicing",
        "Tax ID",
        "VAT/GST registration number, if you have one.",
        default="",
    ),
    SettingSpec(
        "invoice.default_tax_rate_bps",
        SettingKind.INTEGER,
        "invoicing",
        "Default tax rate (basis points)",
        "2000 = 20%. Applied to new invoices unless overridden.",
        default=0,
    ),
    SettingSpec(
        "invoice.tax_label",
        SettingKind.STRING,
        "invoicing",
        "Tax label",
        'What to call it on the document — "VAT", "GST", "Sales tax".',
        default="Tax",
    ),
    SettingSpec(
        "invoice.payment_terms_days",
        SettingKind.INTEGER,
        "invoicing",
        "Payment terms (days)",
        "Days from issue to due date.",
        default=14,
    ),
    # ------------------------------------------------------------ payments
    SettingSpec(
        "payments.stripe_enabled",
        SettingKind.BOOLEAN,
        "payments",
        "Offer Stripe",
        "Whether customers can pay by card.",
        default=True,
    ),
    SettingSpec(
        "payments.mpesa_enabled",
        SettingKind.BOOLEAN,
        "payments",
        "Offer M-PESA",
        "Whether customers can pay by M-PESA.",
        default=True,
    ),
    SettingSpec(
        "payments.stripe_secret_key",
        SettingKind.SECRET,
        "payments",
        "Stripe secret key",
        "Overrides STRIPE_SECRET_KEY. Prefer the environment; set here only if "
        "you need to rotate without a deploy.",
        env_setting="STRIPE_SECRET_KEY",
        write_only=True,
    ),
    SettingSpec(
        "payments.stripe_webhook_secret",
        SettingKind.SECRET,
        "payments",
        "Stripe webhook secret",
        "Overrides STRIPE_WEBHOOK_SECRET.",
        env_setting="STRIPE_WEBHOOK_SECRET",
        write_only=True,
    ),
    SettingSpec(
        "payments.mpesa_consumer_key",
        SettingKind.SECRET,
        "payments",
        "M-PESA consumer key",
        "Overrides MPESA_CONSUMER_KEY.",
        env_setting="MPESA_CONSUMER_KEY",
        write_only=True,
    ),
    SettingSpec(
        "payments.mpesa_consumer_secret",
        SettingKind.SECRET,
        "payments",
        "M-PESA consumer secret",
        "Overrides MPESA_CONSUMER_SECRET.",
        env_setting="MPESA_CONSUMER_SECRET",
        write_only=True,
    ),
    SettingSpec(
        "payments.mpesa_shortcode",
        SettingKind.STRING,
        "payments",
        "M-PESA shortcode",
        "Overrides MPESA_SHORTCODE.",
        env_setting="MPESA_SHORTCODE",
        default="",
    ),
    # ------------------------------------------------------------------ ai
    SettingSpec(
        "ai.enabled",
        SettingKind.BOOLEAN,
        "ai",
        "AI features available",
        "Master switch. Off means no workspace gets AI, whatever their plan.",
        env_setting="LLM_ENABLED",
        default=False,
    ),
    SettingSpec(
        "ai.provider",
        SettingKind.STRING,
        "ai",
        "Provider",
        "google, groq, openai, anthropic, ollama, …",
        env_setting="LLM_PROVIDER",
        default="",
    ),
    SettingSpec(
        "ai.model",
        SettingKind.STRING,
        "ai",
        "Model",
        "Model identifier for the chosen provider.",
        env_setting="LLM_MODEL",
        default="",
    ),
    SettingSpec(
        "ai.api_key",
        SettingKind.SECRET,
        "ai",
        "API key",
        "Overrides LLM_API_KEY.",
        env_setting="LLM_API_KEY",
        write_only=True,
    ),
    SettingSpec(
        "ai.share_financial_context",
        SettingKind.BOOLEAN,
        "ai",
        "Send financial context to the model",
        "Off by default. Sending a household's spending to a third party is a "
        "decision the operator makes deliberately, not a side effect of "
        "enabling AI. Local providers are unaffected — nothing leaves the host.",
        env_setting="LLM_SHARE_FINANCIAL_CONTEXT",
        default=False,
    ),
    # ----------------------------------------------------------- operations
    SettingSpec(
        "ops.queue_backlog_threshold",
        SettingKind.INTEGER,
        "operations",
        "Queue backlog alert threshold",
        "Depth above which the health dashboard reports workers as degraded.",
        env_setting="PLATFORM_QUEUE_BACKLOG_THRESHOLD",
        default=500,
    ),
    SettingSpec(
        "ops.impersonation_ttl_minutes",
        SettingKind.INTEGER,
        "operations",
        "Impersonation session length (minutes)",
        "How long a support session stays usable before expiring on its own.",
        env_setting="PLATFORM_IMPERSONATION_TTL_MINUTES",
        default=30,
    ),
)

SPEC_BY_KEY: dict[str, SettingSpec] = {spec.key: spec for spec in SPECS}


class PlatformSetting(UUIDModel, TimeStampedModel):
    """One stored override. Absent rows fall through to the environment."""

    key = models.CharField(max_length=80, unique=True)
    #: Non-secret values, stored as text and coerced by kind on read.
    value = models.TextField(blank=True, default="")
    #: Secrets, encrypted at rest with FIELD_ENCRYPTION_KEY.
    encrypted_value = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=16, choices=SettingKind.choices)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platform_settings_updated",
    )

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return self.key

    @property
    def is_secret(self) -> bool:
        return self.kind == SettingKind.SECRET

    def set_value(self, raw: Any) -> None:
        if self.is_secret:
            self.encrypted_value = encrypt_str(str(raw)) if raw else ""
            self.value = ""
        else:
            self.value = "" if raw is None else str(raw)
            self.encrypted_value = ""

    def get_value(self) -> Any:
        if self.is_secret:
            return decrypt_str(self.encrypted_value) if self.encrypted_value else ""
        return _coerce(self.value, self.kind)


def _coerce(raw: str, kind: str) -> Any:
    if kind == SettingKind.BOOLEAN:
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    if kind == SettingKind.INTEGER:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    if kind == SettingKind.JSON:
        import json

        try:
            return json.loads(raw or "{}")
        except ValueError:
            return {}
    return raw


def env_value(spec: SettingSpec) -> Any:
    """What the environment currently provides for this setting, if anything."""
    if not spec.env_setting:
        return None
    return getattr(settings, spec.env_setting, None)


def get(key: str) -> Any:
    """Resolve a setting: database override, then environment, then default.

    Reads are uncached deliberately. These are consulted at provider-call and
    invoice-render time — not per request in a hot loop — and a cached payment
    credential that lags a rotation by five minutes is a worse problem than one
    extra indexed lookup.
    """
    spec = SPEC_BY_KEY.get(key)
    if spec is None:
        raise KeyError(f"{key!r} is not a known platform setting.")

    row = PlatformSetting.objects.filter(key=key).first()
    if row is not None:
        stored = row.get_value()
        # An empty stored value means "no override", not "set to empty" —
        # otherwise clearing a field in the console would blank the environment
        # value rather than falling back to it.
        if stored not in (None, ""):
            return stored

    from_env = env_value(spec)
    if from_env not in (None, ""):
        return from_env
    return spec.default


def get_overrides(keys: list[str]) -> dict[str, Any]:
    """Stored overrides for several keys, in one query.

    Batched because the callers that need more than one — invoice rendering
    wants four — run on a hot path, and four separate lookups per rendered
    document is a cost with no benefit.

    Only *explicit* overrides are returned. A key absent from the result means
    "nothing stored", which is different from "stored as empty" and, crucially,
    different from "the built-in default". A caller with its own configured
    value must not have it displaced by this module's default.
    """
    rows = PlatformSetting.objects.filter(key__in=keys)
    found: dict[str, Any] = {}
    for row in rows:
        value = row.get_value()
        if value not in (None, ""):
            found[row.key] = value
    return found


def describe(spec: SettingSpec) -> dict:
    """Console-safe description of one setting.

    A secret's value is never returned — only whether one exists and which
    layer supplied it. An operator can replace a key; nobody reads one back out
    through the API.
    """
    row = PlatformSetting.objects.filter(key=spec.key).first()
    has_override = bool(row and (row.encrypted_value or row.value))
    from_env = env_value(spec)
    has_env = from_env not in (None, "")

    payload = {
        "key": spec.key,
        "kind": spec.kind,
        "choices": list(spec.choices),
        "group": spec.group,
        "label": spec.label,
        "help": spec.help,
        "env_setting": spec.env_setting,
        "source": "database" if has_override else ("environment" if has_env else "default"),
        "overridden": has_override,
        "env_configured": has_env,
        "updated_at": row.updated_at if row else None,
        "updated_by": row.updated_by.email if row and row.updated_by_id else None,
    }
    if spec.write_only:
        payload["value"] = None
        payload["is_set"] = has_override or has_env
    else:
        payload["value"] = get(spec.key)
    return payload


def describe_all() -> list[dict]:
    return [describe(spec) for spec in SPECS]


class InvalidSettingValue(ValueError):
    """A value outside a setting's closed set."""


def set_value(*, key: str, raw: Any, user=None) -> PlatformSetting:
    spec = SPEC_BY_KEY.get(key)
    if spec is None:
        raise KeyError(f"{key!r} is not a known platform setting.")

    if spec.choices and str(raw) not in spec.choices:
        raise InvalidSettingValue(f"{raw!r} is not one of {', '.join(spec.choices)}.")

    row, _ = PlatformSetting.objects.get_or_create(key=key, defaults={"kind": spec.kind})
    row.kind = spec.kind
    row.set_value(raw)
    row.updated_by = user
    row.save()
    return row


def clear(*, key: str, user=None) -> None:
    """Drop an override so the setting falls back to the environment."""
    PlatformSetting.objects.filter(key=key).delete()


# --------------------------------------------------------------------------
# Resolved views used by the rest of the product
# --------------------------------------------------------------------------
def ai_available() -> bool:
    """Whether AI is switched on at the platform level.

    This is the *first* of three independent gates, and the only one an
    operator controls:

    1. **Platform** (here) — is AI available at all, with which provider and
       key. A cost and data-processing decision; nobody else can make it.
    2. **Plan** (`Plan.ai_insights`) — has this workspace paid for it.
    3. **Workspace** (`Tenant.ai_enabled`) — has the owner opted out.

    A workspace member is deliberately absent from that list. Choosing where a
    household's financial data gets sent is a decision made *for* everyone in
    the household, so it belongs to the operator (who chose the vendor) and the
    owner (who can decline), not to whichever member opened the settings page.
    """
    try:
        return bool(get("ai.enabled"))
    except Exception:  # noqa: BLE001
        return bool(getattr(settings, "LLM_ENABLED", False))


def payment_provider_enabled(provider_key: str) -> bool:
    """Whether a provider is offered to customers right now."""
    mapping = {"stripe": "payments.stripe_enabled", "mpesa": "payments.mpesa_enabled"}
    key = mapping.get(provider_key)
    if key is None:
        return True
    try:
        return bool(get(key))
    except Exception:  # noqa: BLE001
        return True
