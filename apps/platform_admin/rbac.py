"""Platform-level RBAC — deliberately *not* the same system as tenancy RBAC.

`apps.tenancy.rbac` answers "what may this person do inside their own
workspace". This module answers "what may this employee do to the whole
platform". They share no vocabulary and must not: a workspace OWNER has
unlimited authority over their own household's data and none whatsoever over
the platform, while a BILLING_ADMIN can refund any tenant's payment and read
none of their transactions. Collapsing the two into one hierarchy would make
that distinction inexpressible.

Design
------
* Capabilities are the unit of authorization. Nothing in the codebase asks
  "is this person a PLATFORM_ADMIN"; it asks "may they do `tenant.suspend`".
  Roles are simply named bundles of capabilities, which keeps the role list a
  product decision rather than a structural one.
* Roles are a *starting point*, not a ceiling. `PlatformStaff` carries
  `extra_capabilities` and `denied_capabilities`, so an operator can be given
  exactly one extra power (or have one revoked) without inventing a role.
  Denials win over grants — a revocation should never be defeated by also
  appearing in a grant list.
* Separation of duties is encoded in the capability split, not left to
  convention: `REFUND_REQUEST` and `REFUND_APPROVE` are distinct, and
  CUSTOMER_SUCCESS holds only the former. The person who promises a customer
  their money back is not the person who moves it.
"""

from __future__ import annotations

from enum import StrEnum


class PlatformRole(StrEnum):
    """Named capability bundles. Ordered loosely by breadth of authority, but
    the order carries no meaning — there is no "at least this role" check
    anywhere, only capability checks."""

    OWNER = "platform_owner"
    ADMIN = "platform_administrator"
    BILLING_ADMIN = "billing_administrator"
    FINANCE = "finance"
    CUSTOMER_SUCCESS = "customer_success"
    TECHNICAL_SUPPORT = "technical_support"
    AUDITOR = "read_only_auditor"

    @property
    def label(self) -> str:
        return {
            PlatformRole.OWNER: "Platform Owner",
            PlatformRole.ADMIN: "Platform Administrator",
            PlatformRole.BILLING_ADMIN: "Billing Administrator",
            PlatformRole.FINANCE: "Finance",
            PlatformRole.CUSTOMER_SUCCESS: "Customer Success",
            PlatformRole.TECHNICAL_SUPPORT: "Technical Support",
            PlatformRole.AUDITOR: "Read Only Auditor",
        }[self]


class PlatformCapability(StrEnum):
    """The complete vocabulary of platform authority.

    Grouped by module. Read and write are always separate; destructive or
    money-moving actions are always separate from their read counterpart.
    """

    # Dashboard & analytics
    DASHBOARD_VIEW = "platform.dashboard.view"
    ANALYTICS_READ = "platform.analytics.read"

    # Tenants
    TENANT_READ = "tenant.read"
    TENANT_WRITE = "tenant.write"
    TENANT_SUSPEND = "tenant.suspend"
    TENANT_DELETE = "tenant.delete"
    TENANT_EXPORT = "tenant.export"
    TENANT_IMPERSONATE = "tenant.impersonate"

    # Subscriptions
    SUBSCRIPTION_READ = "subscription.read"
    SUBSCRIPTION_WRITE = "subscription.write"
    #: Edit the commercial catalogue itself — prices, limits, and which
    #: features a plan includes. Distinct from SUBSCRIPTION_WRITE for the same
    #: reason SUBSCRIPTION_GRANT is: moving one customer between plans is
    #: support; changing what every customer on a plan gets is a commercial
    #: decision that deserves its own grant.
    PLAN_MANAGE = "plan.manage"
    #: Give away paid product (comps, gifts, trial extensions). Deliberately
    #: distinct from SUBSCRIPTION_WRITE: moving a customer between plans they
    #: are paying for is routine support; granting free revenue-bearing
    #: product is a commercial decision.
    SUBSCRIPTION_GRANT = "subscription.grant"

    # Billing: invoices, payments, credits
    BILLING_READ = "billing.read"
    INVOICE_WRITE = "invoice.write"
    PAYMENT_RECONCILE = "payment.reconcile"
    CREDIT_ISSUE = "credit.issue"

    # Refunds — split for separation of duties.
    REFUND_REQUEST = "refund.request"
    REFUND_APPROVE = "refund.approve"

    # Coupons & promotions
    COUPON_READ = "coupon.read"
    COUPON_WRITE = "coupon.write"

    # Dunning
    DUNNING_READ = "dunning.read"
    DUNNING_MANAGE = "dunning.manage"

    # Operations
    HEALTH_READ = "health.read"
    WEBHOOK_REPLAY = "webhook.replay"

    # Customer account recovery
    USER_RECOVER = "user.recover"
    #: Removing someone's second factor genuinely lowers a security control, so
    #: it is separate from ordinary unlocking and given to fewer people.
    USER_MFA_RESET = "user.mfa_reset"

    # Governance
    AUDIT_READ = "audit.read"
    STAFF_READ = "staff.read"
    STAFF_MANAGE = "staff.manage"

    # Platform notifications
    NOTIFICATION_READ = "platform.notification.read"
    NOTIFICATION_MANAGE = "platform.notification.manage"


C = PlatformCapability

#: Everything. Used for OWNER and as the validation universe for custom grants.
ALL_CAPABILITIES: frozenset[PlatformCapability] = frozenset(PlatformCapability)

_READ_ONLY: frozenset[PlatformCapability] = frozenset(
    {
        C.DASHBOARD_VIEW,
        C.ANALYTICS_READ,
        C.TENANT_READ,
        C.SUBSCRIPTION_READ,
        C.BILLING_READ,
        C.COUPON_READ,
        C.DUNNING_READ,
        C.AUDIT_READ,
        C.STAFF_READ,
        C.HEALTH_READ,
        C.NOTIFICATION_READ,
    }
)

ROLE_CAPABILITIES: dict[PlatformRole, frozenset[PlatformCapability]] = {
    PlatformRole.OWNER: ALL_CAPABILITIES,
    # Everything operational, but not the ability to appoint other staff or
    # approve refunds — the owner keeps appointment, finance keeps the money.
    PlatformRole.ADMIN: ALL_CAPABILITIES
    - frozenset({C.STAFF_MANAGE, C.REFUND_APPROVE, C.TENANT_DELETE}),
    PlatformRole.BILLING_ADMIN: _READ_ONLY
    | frozenset(
        {
            C.SUBSCRIPTION_WRITE,
            C.SUBSCRIPTION_GRANT,
            C.PLAN_MANAGE,
            C.INVOICE_WRITE,
            C.PAYMENT_RECONCILE,
            C.CREDIT_ISSUE,
            C.REFUND_REQUEST,
            C.COUPON_WRITE,
            C.DUNNING_MANAGE,
        }
    ),
    # Finance approves and reconciles money but does not touch product state.
    PlatformRole.FINANCE: _READ_ONLY
    | frozenset({C.REFUND_REQUEST, C.REFUND_APPROVE, C.PAYMENT_RECONCILE, C.CREDIT_ISSUE, C.INVOICE_WRITE}),
    PlatformRole.CUSTOMER_SUCCESS: _READ_ONLY
    | frozenset(
        {
            C.TENANT_WRITE,
            C.TENANT_IMPERSONATE,
            C.SUBSCRIPTION_WRITE,
            C.REFUND_REQUEST,  # can promise; cannot pay
            C.USER_RECOVER,
            C.NOTIFICATION_MANAGE,
        }
    ),
    PlatformRole.TECHNICAL_SUPPORT: _READ_ONLY
    | frozenset(
        {
            C.TENANT_IMPERSONATE,
            C.TENANT_EXPORT,
            C.WEBHOOK_REPLAY,
            C.USER_RECOVER,
            C.USER_MFA_RESET,
            C.NOTIFICATION_MANAGE,
        }
    ),
    PlatformRole.AUDITOR: _READ_ONLY,
}


class UnknownCapabilityError(ValueError):
    """Raised when a grant/denial names a capability that doesn't exist.

    Silently ignoring an unknown string would let a typo in a custom grant
    (`"tenant.suspended"`) look like it succeeded while conferring nothing —
    the kind of failure that is only discovered during an incident.
    """


def parse_capability(value: str) -> PlatformCapability:
    try:
        return PlatformCapability(value)
    except ValueError as exc:
        raise UnknownCapabilityError(f"{value!r} is not a known platform capability.") from exc


def parse_capabilities(values) -> frozenset[PlatformCapability]:
    return frozenset(parse_capability(str(v)) for v in (values or []))


def capabilities_for(
    role: str,
    *,
    extra: object = None,
    denied: object = None,
) -> frozenset[PlatformCapability]:
    """Resolve the effective capability set for a role plus per-person overrides.

    Denials are applied last and unconditionally, so revoking a capability is
    always effective regardless of how it was granted.
    """
    try:
        base = ROLE_CAPABILITIES[PlatformRole(role)]
    except ValueError as exc:
        raise UnknownCapabilityError(f"{role!r} is not a known platform role.") from exc
    return (base | parse_capabilities(extra)) - parse_capabilities(denied)
