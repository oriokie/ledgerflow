"""Amount-triggered approvals: "ask me before we spend that much".

The distinction this module is built around
-------------------------------------------
LedgerFlow records money that has already moved. A statement import is history;
so is a transaction somebody types in after the fact. It also lets a partner ask
*before* spending. Those are different events and the product must never
present one as the other:

``REQUESTED``   the money has not moved. Approving it permits a purchase;
                declining it prevents one. The approval is a decision.
``FLAGGED``     the money has moved. Approving it means "I have seen this and
                I am content"; declining it means "we need to talk". The
                approval is a review.

Collapsing these into one "approval" would let the interface say a purchase was
*blocked* when in truth it was *noticed afterwards* — a claim the product cannot
support, which would be discovered at the worst possible moment. Every function
below carries the distinction through to the wording it generates.

What expiry means
-----------------
A pending request that nobody answers becomes ``EXPIRED``, which is neither
approved nor declined, and that is deliberate. Auto-approving on silence defeats
the entire mechanism. Auto-declining lets one partner block the other's spending
by saying nothing, which is worse — it turns an absence into a veto. Silence
means silence, and the household can see that is what happened.

What this does not do
---------------------
It does not stand between a user and their own ledger. `require_approval_for()`
answers a question; it is the *caller's* job to act on the answer. Nothing here
posts, reverses or holds a transaction, because a household governance rule that
could silently prevent somebody accessing their own money is a bigger hazard
than the overspending it guards against.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import audit
from .models import (
    AccountSharing,
    ApprovalComment,
    ApprovalKind,
    ApprovalRule,
    ApprovalScope,
    ApprovalStatus,
    AuditAction,
    SpendApproval,
)


class ApprovalError(ValueError):
    """An action the approval engine will not take."""


# ------------------------------------------------------------------ matching
def matching_rule(*, amount_minor: int, account_id: uuid.UUID | None) -> ApprovalRule | None:
    """The rule that governs this spend, if any.

    The *highest* threshold at or below the amount wins, so a household can set
    "tell me over 20,000" and "give us longer over 100,000" without the two
    fighting over a 150,000 purchase.

    Amounts are compared as magnitudes. A caller passing a signed ledger amount
    should not have to remember which sign spending has.
    """
    amount = abs(int(amount_minor))
    candidates = ApprovalRule.objects.filter(is_active=True, min_amount_minor__lte=amount)

    scopes = [ApprovalScope.SHARED]
    if account_id is not None:
        sharing = AccountSharing.objects.filter(financial_account_id=account_id).first()
        # A rule never reaches a private account: making somebody approve
        # spending on an account they cannot see would be surveillance wearing
        # a governance hat.
        if sharing is not None and sharing.is_joint:
            scopes.append(ApprovalScope.JOINT)

    from django.db.models import Q

    predicate = Q(scope__in=scopes)
    if account_id is not None:
        predicate |= Q(scope=ApprovalScope.ACCOUNT, financial_account_id=account_id)

    return candidates.filter(predicate).order_by("-min_amount_minor").first()


@dataclass(frozen=True)
class ApprovalVerdict:
    required: bool
    rule: ApprovalRule | None = None
    reason: str = ""


def require_approval_for(*, amount_minor: int, account_id: uuid.UUID | None) -> ApprovalVerdict:
    """Would this spend need the other partner's agreement?

    A question, not an enforcement. See the module docstring: nothing here
    stands between somebody and their own money.
    """
    from .visibility import is_single_member_workspace

    # A workspace of one has nobody to ask. Without this, enabling a rule in a
    # personal workspace would make the product interrogate its only user.
    if is_single_member_workspace():
        return ApprovalVerdict(required=False, reason="There is nobody else in this workspace.")

    rule = matching_rule(amount_minor=amount_minor, account_id=account_id)
    if rule is None:
        return ApprovalVerdict(required=False)
    return ApprovalVerdict(
        required=True,
        rule=rule,
        reason=f"Over the agreed {rule.currency} {rule.min_amount_minor / 100:,.0f} threshold.",
    )


# ------------------------------------------------------------------- opening
@transaction.atomic
def request_approval(
    *,
    amount_minor: int,
    currency: str,
    description: str,
    account_id: uuid.UUID | None = None,
    rule: ApprovalRule | None = None,
) -> SpendApproval:
    """Ask before spending. The money has not moved."""
    return _open(
        kind=ApprovalKind.REQUESTED,
        amount_minor=amount_minor,
        currency=currency,
        description=description,
        account_id=account_id,
        rule=rule,
    )


@transaction.atomic
def flag_transaction(*, txn, rule: ApprovalRule | None = None) -> SpendApproval | None:
    """Flag a posting that already happened and trips a threshold.

    Returns None when no rule applies, so callers can invoke it unconditionally
    after posting. Idempotent per transaction: re-running an import must not
    ask a partner to review the same purchase twice.
    """
    existing = SpendApproval.objects.filter(transaction_id=txn.id).first()
    if existing is not None:
        return existing

    verdict = require_approval_for(amount_minor=txn.amount_minor, account_id=txn.financial_account_id)
    if not verdict.required:
        return None

    return _open(
        kind=ApprovalKind.FLAGGED,
        amount_minor=abs(txn.amount_minor),
        currency=getattr(txn.financial_account, "currency", "") or "",
        description=txn.memo or "A large transaction",
        account_id=txn.financial_account_id,
        rule=rule or verdict.rule,
        txn=txn,
    )


def _open(
    *,
    kind: str,
    amount_minor: int,
    currency: str,
    description: str,
    account_id,
    rule,
    txn=None,
) -> SpendApproval:
    from apps.common.tenant_context import get_current_actor_id

    if amount_minor <= 0:
        raise ApprovalError("An approval needs a positive amount.")

    actor_id = get_current_actor_id()
    label = audit._resolve_actor(actor_id)[1]
    hours = rule.expires_after_hours if rule else 48

    approval = SpendApproval.objects.create(
        kind=kind,
        rule=rule,
        requested_by_id=actor_id,
        requested_by_label=label,
        financial_account_id=account_id,
        transaction=txn,
        amount_minor=abs(int(amount_minor)),
        currency=(currency or "").upper()[:3],
        description=description[:255],
        expires_at=timezone.now() + timedelta(hours=hours) if hours else None,
    )

    verb = "asked about" if kind == ApprovalKind.REQUESTED else "flagged"
    audit.record(
        action=AuditAction.CREATED,
        subject_type="spend_approval",
        subject_id=approval.id,
        summary=f"{label} {verb} {approval.currency} {amount_minor / 100:,.2f} — {approval.description}.",
        detail={"kind": kind, "amount_minor": approval.amount_minor},
    )
    _notify_partners(approval)
    return approval


# ------------------------------------------------------------------ resolving
def _assert_open(approval: SpendApproval) -> None:
    if approval.status != ApprovalStatus.PENDING:
        raise ApprovalError(f"This was already {approval.get_status_display().lower()}.")
    if approval.expires_at and approval.expires_at <= timezone.now():
        raise ApprovalError("This request has expired. Ask again if it still matters.")


def _assert_not_self(approval: SpendApproval, actor_id) -> None:
    """Nobody approves their own request.

    The whole point is a second pair of eyes; a mechanism that lets the
    requester supply them is decoration. Reviewing your *own* flagged spending
    is allowed, because a flag is a notification and marking it seen is not a
    decision about anybody else's money.
    """
    if approval.kind == ApprovalKind.REQUESTED and str(approval.requested_by_id) == str(actor_id):
        raise ApprovalError("Approving your own request would defeat the point of asking.")


@transaction.atomic
def approve(*, approval: SpendApproval, note: str = "") -> SpendApproval:
    from apps.common.tenant_context import get_current_actor_id

    actor_id = get_current_actor_id()
    _assert_open(approval)
    _assert_not_self(approval, actor_id)
    return _resolve(approval, ApprovalStatus.APPROVED, actor_id, note)


@transaction.atomic
def decline(*, approval: SpendApproval, note: str = "") -> SpendApproval:
    from apps.common.tenant_context import get_current_actor_id

    actor_id = get_current_actor_id()
    _assert_open(approval)
    _assert_not_self(approval, actor_id)
    return _resolve(approval, ApprovalStatus.DECLINED, actor_id, note)


@transaction.atomic
def suggest(*, approval: SpendApproval, amount_minor: int, note: str = "") -> SpendApproval:
    """Answer with a different figure instead of yes or no.

    The request stays open. "Could you make it 30,000?" is a step in a
    negotiation, not a verdict, and resolving it here would end a conversation
    that has not finished.
    """
    from apps.common.tenant_context import get_current_actor_id

    actor_id = get_current_actor_id()
    _assert_open(approval)
    if amount_minor <= 0:
        raise ApprovalError("A suggested amount has to be positive.")

    approval.suggested_amount_minor = int(amount_minor)
    approval.save(update_fields=["suggested_amount_minor", "updated_at"])

    label = audit._resolve_actor(actor_id)[1]
    comment(
        approval=approval,
        body=note or f"Suggested {approval.currency} {amount_minor / 100:,.2f} instead.",
    )
    audit.record(
        action=AuditAction.UPDATED,
        subject_type="spend_approval",
        subject_id=approval.id,
        summary=(
            f"{label} suggested {approval.currency} {amount_minor / 100:,.2f} "
            f"instead of {approval.amount_minor / 100:,.2f}."
        ),
        detail={"suggested_amount_minor": int(amount_minor)},
    )
    _notify_partners(approval, suggestion=True)
    return approval


@transaction.atomic
def withdraw(*, approval: SpendApproval) -> SpendApproval:
    """The requester changing their mind. Only they may."""
    from apps.common.tenant_context import get_current_actor_id

    actor_id = get_current_actor_id()
    _assert_open(approval)
    if str(approval.requested_by_id) != str(actor_id):
        raise ApprovalError("Only the person who asked can withdraw the request.")
    return _resolve(approval, ApprovalStatus.WITHDRAWN, actor_id, "")


def _resolve(approval, status, actor_id, note) -> SpendApproval:
    label = audit._resolve_actor(actor_id)[1]
    approval.status = status
    approval.resolved_at = timezone.now()
    approval.resolved_by_id = actor_id if _user_exists(actor_id) else None
    approval.resolved_by_label = label
    approval.save(update_fields=["status", "resolved_at", "resolved_by", "resolved_by_label", "updated_at"])

    if note:
        comment(approval=approval, body=note)

    action = {
        ApprovalStatus.APPROVED: AuditAction.APPROVED,
        ApprovalStatus.DECLINED: AuditAction.DECLINED,
    }.get(status, AuditAction.UPDATED)

    # The wording differs by kind on purpose — see the module docstring.
    if approval.kind == ApprovalKind.REQUESTED:
        verbs = {
            ApprovalStatus.APPROVED: "approved",
            ApprovalStatus.DECLINED: "declined",
            ApprovalStatus.WITHDRAWN: "withdrew",
        }
    else:
        verbs = {
            ApprovalStatus.APPROVED: "reviewed and accepted",
            ApprovalStatus.DECLINED: "queried",
            ApprovalStatus.WITHDRAWN: "withdrew",
        }
    verb = verbs.get(status, str(status))

    audit.record(
        action=action,
        subject_type="spend_approval",
        subject_id=approval.id,
        summary=(
            f"{label} {verb} {approval.currency} "
            f"{approval.amount_minor / 100:,.2f} — {approval.description}."
        ),
        detail={"status": str(status), "kind": approval.kind},
    )
    return approval


def _user_exists(actor_id) -> bool:
    if not actor_id:
        return False
    from apps.tenancy.models import Membership

    return Membership.objects.filter(user_id=actor_id).exists()


# ------------------------------------------------------------------- comments
@transaction.atomic
def comment(*, approval: SpendApproval, body: str) -> ApprovalComment:
    from apps.common.tenant_context import get_current_actor_id

    text = (body or "").strip()
    if not text:
        raise ApprovalError("An empty comment says nothing.")

    actor_id = get_current_actor_id()
    label = audit._resolve_actor(actor_id)[1]
    return ApprovalComment.objects.create(
        approval=approval,
        author_id=actor_id if _user_exists(actor_id) else None,
        author_label=label,
        body=text,
    )


# -------------------------------------------------------------------- expiry
def expire_pending(*, now=None) -> int:
    """Move unanswered requests past their deadline to EXPIRED.

    Run from a periodic task. Returns how many it moved. Each expiry is
    audited, because "nobody answered" is a thing that happened and a blank in
    the timeline would leave the requester wondering whether they had been
    ignored or the product had lost the request.
    """
    now = now or timezone.now()
    stale = list(
        SpendApproval.objects.filter(
            status=ApprovalStatus.PENDING, expires_at__isnull=False, expires_at__lte=now
        )
    )
    for approval in stale:
        approval.status = ApprovalStatus.EXPIRED
        approval.resolved_at = now
        approval.save(update_fields=["status", "resolved_at", "updated_at"])
        audit.record(
            action=AuditAction.UPDATED,
            subject_type="spend_approval",
            subject_id=approval.id,
            summary=(
                f"Nobody answered {approval.requested_by_label}'s request for "
                f"{approval.currency} {approval.amount_minor / 100:,.2f} in time."
            ),
            detail={"status": str(ApprovalStatus.EXPIRED)},
        )
    return len(stale)


# -------------------------------------------------------------- notification
def _notify_partners(approval: SpendApproval, *, suggestion: bool = False) -> None:
    """Tell the other members. Never the person who acted.

    Failures are swallowed for the same reason the audit log's are: a household
    should not be unable to ask about a purchase because the push service is
    down.
    """
    try:
        from apps.notifications.models import NotificationSeverity, NotificationType
        from apps.notifications.services import raise_notification
        from apps.tenancy.models import Membership

        from .visibility import require_current_tenant_id

        actor_id = approval.requested_by_id
        others = Membership.objects.filter(tenant_id=require_current_tenant_id()).exclude(user_id=actor_id)
        if suggestion:
            title = "A change was suggested"
            body = f"On {approval.description}."
        elif approval.kind == ApprovalKind.REQUESTED:
            title = f"{approval.requested_by_label} is asking about a purchase"
            body = f"{approval.currency} {approval.amount_minor / 100:,.2f} — {approval.description}"
        else:
            title = "A large transaction needs a look"
            body = f"{approval.currency} {approval.amount_minor / 100:,.2f} — {approval.description}"

        for membership in others:
            raise_notification(
                type=NotificationType.LARGE_TRANSACTION,
                title=title,
                body=body,
                user=membership.user,
                severity=NotificationSeverity.WARNING,
                subject_type="spend_approval",
                subject_id=approval.id,
                dedupe_key=f"approval:{approval.id}:{'suggest' if suggestion else 'open'}",
            )
    except Exception:  # noqa: BLE001 — notifying must not break approving
        pass


# --------------------------------------------------------------------- reads
def pending() -> list[SpendApproval]:
    return list(SpendApproval.objects.filter(status=ApprovalStatus.PENDING))


def history(*, limit: int = 100) -> list[SpendApproval]:
    return list(SpendApproval.objects.all()[:limit])
