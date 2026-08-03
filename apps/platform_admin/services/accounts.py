"""Account recovery: unlocking users and starting a password reset for them.

Support's most common request is "I can't get in". Until now the only answers
were "use the forgot-password link" — useless if the person has lost access to
the mailbox or the account is deactivated — or a shell on production, which is
the thing this console exists to avoid.

Deliberate limits
-----------------
**Staff never set a password.** Every operation here either clears an
obstruction or sends the user a link they must act on themselves. An operator
who can set a customer's password can log in as them without an impersonation
grant, silently, and every audit control in the platform is bypassed. The
inconvenience of not being able to read a password down the phone is the point.

**Reactivation is not the same as undoing a suspension.** A user deactivated
because their *workspace* was suspended for non-payment must stay out until the
billing state is resolved, or support becomes a way around dunning. This
service refuses when the only live workspace is suspended, and says why.

**MFA reset is separated from unlocking**, because it is the one operation that
genuinely lowers a security control. Removing someone's second factor on the
word of a caller is how account takeovers happen, so it requires its own
capability and its own reason, and it notifies the account.
"""

from __future__ import annotations

import logging

from django.db import transaction

from apps.users.models import User

from ..audit import record
from ..models import PlatformStaff

logger = logging.getLogger("ledgerflow.platform.accounts")

MODULE = "users"


class AccountRecoveryError(Exception):
    """Raised when a recovery action is refused."""


def _require_reason(reason: str, action: str) -> str:
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise AccountRecoveryError(
            f"{action} needs a specific reason (at least 10 characters) — it is "
            "recorded against the customer's account."
        )
    return reason


def find_user(*, email: str) -> User | None:
    return User.objects.filter(email__iexact=email.strip()).first()


def account_status(*, user: User) -> dict:
    """Everything support needs to answer "why can't they get in?" in one call.

    Assembled here rather than left to the console so the answer is the same
    whichever surface asks, and so the reasons are named rather than inferred
    from a scatter of booleans.
    """
    from apps.tenancy.models import Membership
    from apps.users.mfa_models import TOTPDevice
    from apps.users.security_events import LoginEvent

    memberships = list(
        Membership.objects.filter(user=user).select_related("tenant")
    )
    recent = list(
        LoginEvent.objects.filter(user=user).order_by("-created_at")[:5]
    )

    blockers = []
    if not user.is_active:
        blockers.append("The account is deactivated.")
    if not user.is_verified:
        blockers.append("The email address was never verified.")
    if memberships and all(not m.tenant.is_active for m in memberships):
        blockers.append("Every workspace they belong to is suspended.")
    if not memberships:
        blockers.append("They belong to no workspace.")

    return {
        "user_id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "mfa_enabled": TOTPDevice.objects.filter(user=user, confirmed_at__isnull=False).exists(),
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
        "blockers": blockers,
        "workspaces": [
            {
                "tenant_id": str(m.tenant_id),
                "name": m.tenant.name,
                "role": m.role,
                "workspace_active": m.tenant.is_active,
            }
            for m in memberships
        ],
        "recent_logins": [
            {"at": e.created_at, "method": e.method, "succeeded": e.succeeded, "ip": e.ip_address}
            for e in recent
        ],
    }


@transaction.atomic
def reactivate(*, user: User, actor: PlatformStaff, reason: str, request=None) -> User:
    """Re-enable a deactivated account."""
    reason = _require_reason(reason, "Reactivating an account")
    if user.is_active:
        return user

    from apps.tenancy.models import Membership

    memberships = Membership.objects.filter(user=user).select_related("tenant")
    if memberships.exists() and not memberships.filter(tenant__is_active=True).exists():
        # Otherwise support becomes a way around dunning.
        raise AccountRecoveryError(
            "Every workspace this person belongs to is suspended, so reactivating "
            "the login would not let them in. Resolve the workspace's billing "
            "state first."
        )

    user.is_active = True
    user.save(update_fields=["is_active"])
    record(
        action="user.reactivated",
        staff=actor,
        module=MODULE,
        target_type="users.User",
        target_id=user.id,
        changes={"is_active": [False, True]},
        reason=reason,
        context={"email": user.email},
        request=request,
    )
    return user


@transaction.atomic
def deactivate(*, user: User, actor: PlatformStaff, reason: str, request=None) -> User:
    """Disable a login — for abuse, or at the person's own request."""
    reason = _require_reason(reason, "Deactivating an account")
    if not user.is_active:
        return user

    from apps.platform_admin.separation import is_platform_staff

    if is_platform_staff(user):
        raise AccountRecoveryError(
            "This is a platform staff account. Revoke their platform access "
            "instead, which also ends any impersonation sessions they hold."
        )

    user.is_active = False
    user.save(update_fields=["is_active"])
    record(
        action="user.deactivated",
        staff=actor,
        module=MODULE,
        target_type="users.User",
        target_id=user.id,
        changes={"is_active": [True, False]},
        reason=reason,
        context={"email": user.email},
        request=request,
    )
    return user


@transaction.atomic
def send_password_reset(*, user: User, actor: PlatformStaff, reason: str, request=None) -> bool:
    """Trigger the ordinary reset email on the customer's behalf.

    Note what this does *not* do: it does not set a password, and it does not
    return the token to the operator. Support starts the flow; the customer
    completes it from their own mailbox. That keeps the one credential that
    grants access in exactly one pair of hands.
    """
    reason = _require_reason(reason, "Sending a password reset")

    from apps.users.services.password_reset import request_password_reset

    token = request_password_reset(email=user.email)
    record(
        action="user.password_reset_sent",
        staff=actor,
        module=MODULE,
        target_type="users.User",
        target_id=user.id,
        reason=reason,
        # Deliberately records that a reset was sent, never the token.
        context={"email": user.email},
        request=request,
    )
    logger.info("password reset sent for %s by %s", user.email, actor.user_id)
    return token is not None


@transaction.atomic
def reset_mfa(*, user: User, actor: PlatformStaff, reason: str, request=None) -> int:
    """Remove enrolled second factors so the user can re-enrol.

    The genuinely dangerous one, and the reason it is a separate operation with
    a separate capability: removing MFA on the word of a caller is the classic
    account-takeover path. The account is notified, so the real owner learns
    about it even if the request did not come from them.
    """
    reason = _require_reason(reason, "Resetting two-factor authentication")

    from apps.users.mfa_models import MFABackupCode, TOTPDevice
    from apps.users.webauthn_models import WebAuthnCredential

    counts = {
        "totp": TOTPDevice.objects.filter(user=user).count(),
        "passkeys": WebAuthnCredential.objects.filter(user=user).count(),
        "backup_codes": MFABackupCode.objects.filter(user=user).count(),
    }
    removed = sum(counts.values())
    if not removed:
        raise AccountRecoveryError("This account has no second factor enrolled.")

    TOTPDevice.objects.filter(user=user).delete()
    WebAuthnCredential.objects.filter(user=user).delete()
    MFABackupCode.objects.filter(user=user).delete()

    record(
        action="user.mfa_reset",
        staff=actor,
        module=MODULE,
        target_type="users.User",
        target_id=user.id,
        changes={k: [v, 0] for k, v in counts.items() if v},
        reason=reason,
        context={"email": user.email},
        request=request,
    )

    # Tell the account holder. If this request did not come from them, this
    # message is how they find out — which is the whole point.
    try:
        from django.core.mail import send_mail

        send_mail(
            subject="Two-factor authentication was removed from your LedgerFlow account",
            message=(
                "Support removed the second factor from your account so you can set it "
                "up again.\n\nIf you did not ask for this, contact us immediately — "
                "someone else may be trying to reach your account.\n"
            ),
            from_email=None,
            recipient_list=[user.email],
            fail_silently=True,
        )
    except Exception:  # noqa: BLE001 — notification must not roll back the reset
        logger.warning("could not notify %s about the MFA reset", user.email)

    return removed


@transaction.atomic
def verify_email(*, user: User, actor: PlatformStaff, reason: str, request=None) -> User:
    """Mark an address verified when delivery is the obstacle.

    A real case: corporate mail filters swallow the verification message and no
    amount of resending helps. Narrow enough to be safe — it confirms an address
    the person already gave us, and grants nothing beyond getting past the gate.
    """
    reason = _require_reason(reason, "Verifying an email address")
    if user.is_verified:
        return user

    user.is_verified = True
    user.save(update_fields=["is_verified"])
    record(
        action="user.email_verified",
        staff=actor,
        module=MODULE,
        target_type="users.User",
        target_id=user.id,
        changes={"is_verified": [False, True]},
        reason=reason,
        context={"email": user.email},
        request=request,
    )
    return user
