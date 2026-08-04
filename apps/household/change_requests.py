"""Asking a partner's permission, and what happens when they give it.

`APPROVAL_REQUIRED` was a policy with no mechanism: `visibility.needs_approval`
returned True and then nothing existed to route the change into, so the policy
behaved as read-only. This is the missing half.

The flow is deliberately three-sided, because that is what makes it worth
having over "ask them to do it themselves":

1. a member proposes a change to an account they do not control,
2. the owner sees exactly what was proposed, in the same terms they would type,
3. approving *applies* it — otherwise the owner has to make the change by hand
   and the request was only ever a message.

**A change request can never move money.** Not a transfer, not a balance, not a
transaction. The allow-list below is metadata and sharing only, and it is an
allow-list rather than a deny-list for the usual reason: a deny-list is wrong
the moment somebody adds a field. If a future field ought to be requestable,
adding it here is a deliberate act with a test attached.

**Approval is the owner's alone.** Not an admin's, not the workspace owner's —
the same rule the sharing endpoints already enforce, for the same reason. An
approval mechanism that a senior role can approve on your behalf is not an
approval mechanism.

**Nothing is deleted.** A declined request stays, with who declined it and
when. The value of the whole apparatus is the record, and a record that can be
tidied away is worth less than no record at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .models import AccountSharing, ChangeRequest, ChangeRequestStatus, SharingPolicy
from .visibility import current_membership

#: Everything a request may ask to change, and where it lands.
#:
#: `account` fields are on `FinancialAccount`; `sharing` fields are on
#: `AccountSharing`. Balances, currency, account type and the ledger link are
#: all absent on purpose — those either move money or would silently
#: re-interpret history, and neither belongs behind a partner's approval.
REQUESTABLE = {
    "name": ("account", str),
    "notes": ("account", str),
    "color": ("account", str),
    "icon": ("account", str),
    "is_hidden": ("account", bool),
    "include_in_net_worth": ("account", bool),
    "include_in_budgets": ("account", bool),
    "policy": ("sharing", str),
    "is_joint": ("sharing", bool),
}


class ChangeRequestError(Exception):
    """A request that cannot honestly be made, approved or declined."""


@dataclass(frozen=True)
class Applied:
    request: ChangeRequest
    #: Field -> (before, after), for the response and the audit trail.
    changes: dict


def validate_payload(payload: dict) -> dict:
    """Coerce and check a proposed change against the allow-list.

    Unknown keys are rejected rather than dropped. Elsewhere in this codebase
    (`ask.py`, the advisor) unknown keys are silently discarded, because there
    the author is a language model and dropping is the safe default. Here the
    author is a person who typed something and is waiting to hear back — and
    quietly ignoring half of what they asked for, then telling their partner
    the request was approved, is a worse failure than an error message.
    """
    if not payload:
        raise ChangeRequestError("A change request has to actually propose a change.")
    unknown = set(payload) - set(REQUESTABLE)
    if unknown:
        raise ChangeRequestError(
            f"These cannot be changed by request: {sorted(unknown)}. "
            "Requests cover an account's name and how it is shared — never its "
            "balance, currency or type."
        )

    resolved = {}
    for key, value in payload.items():
        _target, kind = REQUESTABLE[key]
        if kind is bool:
            if not isinstance(value, bool):
                raise ChangeRequestError(f"{key} must be true or false.")
        elif not isinstance(value, str):
            raise ChangeRequestError(f"{key} must be text.")
        if key == "policy" and value not in SharingPolicy.values:
            raise ChangeRequestError(f"unknown sharing policy: {value!r}")
        resolved[key] = value
    return resolved


def _describe(payload: dict) -> str:
    """A one-line summary in the terms the owner will recognise."""
    parts = []
    for key, value in payload.items():
        label = key.replace("_", " ")
        if key == "policy":
            parts.append(f"sharing to “{SharingPolicy(value).label}”")
        elif isinstance(value, bool):
            parts.append(f"{label} {'on' if value else 'off'}")
        else:
            parts.append(f"{label} to “{value}”")
    return "Change " + ", ".join(parts)


@transaction.atomic
def submit(*, account_id, payload: dict, summary: str = "") -> ChangeRequest:
    """Propose a change to an account you do not control.

    Refuses when the caller *could* just make the change: a request that did not
    need to be one clutters the owner's queue and teaches them to approve
    without reading, which is the failure mode that makes approval flows
    worthless.
    """
    from .visibility import can_write_account, needs_approval

    sharing = AccountSharing.objects.filter(financial_account_id=account_id).first()
    if sharing is None:
        raise ChangeRequestError("That account has no sharing settings yet, so there is nobody to ask.")

    membership = current_membership()
    if membership is not None and sharing.owner_id == membership.id:
        raise ChangeRequestError("You own this account — change it directly rather than asking.")
    if can_write_account(account_id):
        raise ChangeRequestError("This account is shared, so you can make that change yourself.")
    if not needs_approval(account_id):
        raise ChangeRequestError(
            "This account is read-only to you and its owner has not opened it to "
            "requests. Ask them directly."
        )

    resolved = validate_payload(payload)
    actor_id = membership.user_id if membership else None
    if actor_id is None:
        raise ChangeRequestError("A change request has to come from a signed-in member.")

    return ChangeRequest.objects.create(
        account_sharing=sharing,
        requested_by_id=actor_id,
        summary=summary or _describe(resolved),
        payload=resolved,
    )


def _assert_owner(request: ChangeRequest) -> None:
    membership = current_membership()
    if membership is None:
        raise ChangeRequestError("Only the account's owner can resolve this request.")
    if request.account_sharing.owner_id != membership.id:
        raise ChangeRequestError(
            "Only the account's owner can approve or decline this, whatever your role " "in the workspace."
        )


@transaction.atomic
def approve(request: ChangeRequest) -> Applied:
    """Apply the proposed change, as the owner.

    Re-validates the payload before applying rather than trusting what was
    stored. A request can sit for weeks, and the allow-list may have narrowed
    in between; applying a field the product no longer considers requestable
    because it was permitted when the request was filed is precisely the kind
    of quiet privilege escalation an approval queue invites.
    """
    if request.status != ChangeRequestStatus.PENDING:
        raise ChangeRequestError(f"This request was already {request.status}.")
    _assert_owner(request)

    payload = validate_payload(request.payload or {})
    sharing = request.account_sharing
    account = sharing.financial_account
    changes: dict = {}

    for key, value in payload.items():
        target, _kind = REQUESTABLE[key]
        obj = account if target == "account" else sharing
        before = getattr(obj, key)
        if before == value:
            continue
        setattr(obj, key, value)
        changes[key] = {"before": before, "after": value}

    if any(REQUESTABLE[k][0] == "account" for k in changes):
        account.save()
    if any(REQUESTABLE[k][0] == "sharing" for k in changes):
        sharing.save()

    membership = current_membership()
    request.status = ChangeRequestStatus.APPROVED
    request.resolved_at = timezone.now()
    request.resolved_by_id = membership.user_id if membership else None
    request.save(update_fields=["status", "resolved_at", "resolved_by", "updated_at"])
    return Applied(request=request, changes=changes)


@transaction.atomic
def decline(request: ChangeRequest) -> ChangeRequest:
    """Refuse the change, as the owner. The request stays on the record."""
    if request.status != ChangeRequestStatus.PENDING:
        raise ChangeRequestError(f"This request was already {request.status}.")
    _assert_owner(request)

    membership = current_membership()
    request.status = ChangeRequestStatus.DECLINED
    request.resolved_at = timezone.now()
    request.resolved_by_id = membership.user_id if membership else None
    request.save(update_fields=["status", "resolved_at", "resolved_by", "updated_at"])
    return request


def visible_to_me():
    """Requests the caller has a legitimate interest in.

    The owner of the account, and the person who asked. Nobody else — a
    workspace's approval queue is not a noticeboard, and a third member seeing
    that one partner asked another to un-hide an account learns something that
    is not theirs.
    """
    membership = current_membership()
    if membership is None:
        return ChangeRequest.objects.none()
    from django.db.models import Q

    return ChangeRequest.objects.filter(
        Q(account_sharing__owner_id=membership.id) | Q(requested_by_id=membership.user_id)
    ).select_related("account_sharing")
