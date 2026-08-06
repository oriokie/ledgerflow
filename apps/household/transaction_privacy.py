"""What one partner sees of the other's individual transactions.

The sibling of `visibility.py`, one level down. That module decides which
*accounts* a member may see; this decides how much of a *line* they see inside
an account they can already see. The two compose, account first: a transaction
in a private account is invisible whatever its own setting says, because the
account already answered the question.

Four levels, and each conceals something different
--------------------------------------------------
``PRIVATE``        omitted from itemised listings entirely.
``CATEGORY_ONLY``  "Groceries — private amount". They know the kind of thing,
                   not the size. The common case for a gift.
``AMOUNT_ONLY``    "KSh 2,400 — private". They know the size, not the kind.
                   The common case for a hobby somebody would rather not
                   discuss but does not want to hide the cost of.
``FULL``           ordinary.

Two rules
---------
**Redaction happens in one place.** `redact()` is the only sanctioned way to
turn a transaction into something another member may read. A second
serialisation path that formats transactions itself is a leak waiting to be
written, which is why `apply()` takes the already-serialised payload rather
than asking each call site to remember which fields are sensitive.

**Totals still include what is hidden.** A household's spending is its
spending; a partner who cannot itemise a purchase should still see it in the
month's outgoings, or the figures they *are* shown are wrong and they will act
on them. This mirrors `all_account_ids()`: aggregate truth, itemised privacy.

The limitation this module cannot fix
-------------------------------------
Hiding a line inside an account whose balance is visible does not hide the
amount from anybody willing to subtract. `PRIVATE` reliably conceals *what*
something was; it conceals *how much* only when the partner cannot see the
account's balance. The product must not imply otherwise — a privacy control
that overpromises is worse than one that explains its edges.
"""

from __future__ import annotations

import uuid

from django.db.models import QuerySet

from .models import TransactionPrivacy, TransactionVisibility

#: Fields that reveal *what* a transaction was.
_WHAT_FIELDS = ("memo", "category_id", "payee_id", "counter_account_id")
#: Fields that reveal *how much*.
_AMOUNT_FIELDS = ("amount_minor",)


def _levels_by_transaction() -> dict[uuid.UUID, str]:
    """Deliberate privacy choices in this workspace, as {txn_id: level}.

    Small by construction — only transactions somebody explicitly marked have a
    row. See the model for why that matters.
    """
    return dict(TransactionPrivacy.objects.values_list("transaction_id", "level"))


def _mine() -> set[uuid.UUID]:
    """Transactions the acting member marked themselves.

    Your own privacy setting never hides anything from you. Without this, a
    member would mark a purchase private and then be unable to see it, which
    reads as data loss.
    """
    from .visibility import current_membership

    membership = current_membership()
    if membership is None:
        return set()
    return set(
        TransactionPrivacy.objects.filter(owner_id=membership.id).values_list("transaction_id", flat=True)
    )


def hidden_transaction_ids() -> set[uuid.UUID]:
    """Ids to leave out of itemised listings for the current actor.

    Empty in a single-member workspace, and empty for the marks you made
    yourself.
    """
    from .visibility import is_single_member_workspace

    if is_single_member_workspace():
        return set()

    mine = _mine()
    return {
        txn_id
        for txn_id, level in _levels_by_transaction().items()
        if level == TransactionVisibility.PRIVATE and txn_id not in mine
    }


def restrict_transactions(queryset: QuerySet) -> QuerySet:
    """Narrow a `Transaction` queryset to lines the actor may itemise.

    Only removes `PRIVATE` ones. Partially-redacted lines stay in the queryset
    and are blunted by `apply()` at serialisation — removing them would leave
    the same unexplained gap as hiding them, while telling the partner less.
    """
    hidden = hidden_transaction_ids()
    if not hidden:
        return queryset
    return queryset.exclude(id__in=hidden)


def redaction_levels() -> dict[uuid.UUID, str]:
    """{txn_id: level} for lines the actor may see but not in full.

    Excludes `PRIVATE` (already filtered out) and the actor's own marks.
    """
    from .visibility import is_single_member_workspace

    if is_single_member_workspace():
        return {}

    mine = _mine()
    partial = (TransactionVisibility.CATEGORY_ONLY, TransactionVisibility.AMOUNT_ONLY)
    return {
        txn_id: level
        for txn_id, level in _levels_by_transaction().items()
        if level in partial and txn_id not in mine
    }


def apply(payload: dict, level: str | None) -> dict:
    """Blunt an already-serialised transaction according to `level`.

    Takes the serialised dict rather than the model so that every field the API
    exposes is covered by one decision. A version of this that took the model
    and re-serialised would silently stop covering any field added later to the
    serializer and not to this function.

    The returned payload always says it was redacted. A blank field that does
    not explain itself reads as missing data and invites a partner to ask what
    happened to it, which is the opposite of what a privacy control is for.
    """
    if not level or level == TransactionVisibility.FULL:
        return payload

    out = dict(payload)
    if level == TransactionVisibility.CATEGORY_ONLY:
        for field in _AMOUNT_FIELDS:
            out[field] = None
        out["redacted"] = "amount"
        out["redaction_note"] = "The amount is private."
    elif level == TransactionVisibility.AMOUNT_ONLY:
        for field in _WHAT_FIELDS:
            out[field] = None
        out["redacted"] = "detail"
        out["redaction_note"] = "What this was for is private."
    else:  # PRIVATE reaching here means a caller skipped restrict_transactions
        for field in _WHAT_FIELDS + _AMOUNT_FIELDS:
            out[field] = None
        out["redacted"] = "all"
        out["redaction_note"] = "This transaction is private."
    return out


def apply_many(payloads: list[dict]) -> list[dict]:
    """Redact a page of serialised transactions in one pass.

    One query for the levels rather than one per row — a listing is the hot
    path this feature would otherwise slow down.
    """
    levels = redaction_levels()
    if not levels:
        return payloads
    return [apply(p, levels.get(_as_uuid(p.get("id")))) for p in payloads]


def _as_uuid(value):
    if isinstance(value, uuid.UUID) or value is None:
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


# ------------------------------------------------------------------- writing
class TransactionPrivacyError(ValueError):
    """A privacy change the household will not make."""


def set_level(*, transaction, level: str) -> TransactionPrivacy | None:
    """Mark a transaction's privacy. `FULL` clears any existing mark.

    Only the member who made a mark may change it. A privacy setting the other
    party can lift is not a privacy setting — and this is the one rule in the
    module that role seniority does not override.
    """
    from . import audit
    from .models import AuditAction
    from .visibility import current_membership

    if level not in set(TransactionVisibility):
        raise TransactionPrivacyError(f"{level!r} is not a privacy level.")

    membership = current_membership()
    existing = TransactionPrivacy.objects.filter(transaction_id=transaction.id).first()

    if (
        existing is not None
        and existing.owner_id
        and membership is not None
        and existing.owner_id != membership.id
    ):
        raise TransactionPrivacyError("Only the person who marked this private can change it.")

    if level == TransactionVisibility.FULL:
        if existing is not None:
            existing.delete()
            audit.record(
                action=AuditAction.SHARED,
                subject_type="transaction",
                subject_id=transaction.id,
                summary="Made a transaction visible to the household.",
            )
        return None

    if existing is not None:
        existing.level = level
        existing.save(update_fields=["level", "updated_at"])
        record = existing
    else:
        record = TransactionPrivacy.objects.create(
            transaction=transaction,
            owner=membership,
            level=level,
        )

    # The event is recorded but says nothing about the transaction. Its
    # existence is not the secret — a timeline with silent gaps is itself
    # informative — but the specifics are precisely what was just protected.
    audit.record(
        action=AuditAction.SHARED,
        subject_type="transaction",
        subject_id=transaction.id,
        summary="Changed the privacy of a transaction.",
        is_private=True,
    )
    return record
