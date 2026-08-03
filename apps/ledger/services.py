"""Ledger service layer — the heart of the product.

`post_journal_entry` is the single choke point through which all money moves.
It enforces the double-entry invariant, single-currency rule, idempotency, and
updates materialized balances + the audit outbox — all in one DB transaction.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction

from apps.common.outbox import OutboxEvent

from .models import Account, AccountBalance, Direction, JournalEntry, LedgerLine



logger = logging.getLogger("ledgerflow.ledger")

class LedgerError(Exception): ...


class UnbalancedEntryError(LedgerError): ...


@dataclass(frozen=True, slots=True)
class LineInput:
    account_id: str
    direction: str  # Direction.DEBIT / CREDIT
    amount_minor: int  # positive


def create_account(*, name: str, kind: str, currency: str, is_system: bool = False) -> Account:
    """Creates a ledger account and its materialized balance row together.

    `is_system` marks accounts the product provisions on the user's behalf
    (opening-balance equity, FX gain/loss) so the UI can keep them out of
    pickers — they're real accounts with real entries, just not ones a user
    should post to by hand.
    """
    with transaction.atomic():
        account = Account.objects.create(name=name, kind=kind, currency=currency, is_system=is_system)
        AccountBalance.objects.create(
            account=account, tenant_id=account.tenant_id, balance_minor=0, currency=currency
        )
        OutboxEvent.objects.create(
            tenant_id=account.tenant_id,
            aggregate_type="ledger.Account",
            aggregate_id=account.id,
            event_type="ledger.account.created",
            payload={"name": name, "kind": kind, "currency": currency, "is_system": is_system},
        )
    return account


def _signed_delta(account: Account, direction: str, amount_minor: int) -> int:
    """Effect on the account's balance given its normal-balance side."""
    increases = (account.normal_debit and direction == Direction.DEBIT) or (
        not account.normal_debit and direction == Direction.CREDIT
    )
    return amount_minor if increases else -amount_minor


@transaction.atomic
def post_journal_entry(
    *,
    occurred_at: datetime,
    lines: list[LineInput],
    idempotency_key: str,
    memo: str = "",
    reverses: JournalEntry | None = None,
) -> JournalEntry:
    if len(lines) < 2:
        raise UnbalancedEntryError("A journal entry needs at least two lines.")

    # Idempotency: short-circuit on replay (unique constraint is the backstop).
    existing = JournalEntry.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing

    # Lock the accounts (and thus their balances) to serialize concurrent posts.
    account_ids = {ln.account_id for ln in lines}
    accounts = {str(a.id): a for a in Account.objects.select_for_update().filter(id__in=account_ids)}
    if len(accounts) != len(account_ids):
        raise LedgerError("One or more accounts not found in this workspace.")

    currencies = {accounts[ln.account_id].currency for ln in lines}
    if len(currencies) != 1:
        raise LedgerError("All lines of an entry must share one currency (use FX for cross-currency).")
    currency = currencies.pop()

    debits = sum(ln.amount_minor for ln in lines if ln.direction == Direction.DEBIT)
    credits = sum(ln.amount_minor for ln in lines if ln.direction == Direction.CREDIT)
    if debits != credits or debits == 0:
        raise UnbalancedEntryError(f"debits ({debits}) must equal credits ({credits}) and be non-zero.")

    try:
        # The insert needs its own savepoint. Without one, a unique-constraint
        # violation aborts the *enclosing* transaction, and the recovery query
        # below then fails with TransactionManagementError instead of returning
        # the winner — so the idempotency guarantee held only for the sequential
        # replay case and broke under the concurrent one it exists for.
        with transaction.atomic():
            entry = JournalEntry.objects.create(
                occurred_at=occurred_at,
                currency=currency,
                memo=memo,
                idempotency_key=idempotency_key,
                reverses=reverses,
            )
    except IntegrityError:  # lost an idempotency race — return the winner
        return JournalEntry.objects.get(idempotency_key=idempotency_key)

    LedgerLine.objects.bulk_create(
        [
            LedgerLine(
                entry=entry,
                tenant_id=entry.tenant_id,
                account=accounts[ln.account_id],
                direction=ln.direction,
                amount_minor=ln.amount_minor,
            )
            for ln in lines
        ]
    )

    # Update materialized balances in the same transaction.
    for ln in lines:
        acct = accounts[ln.account_id]
        delta = _signed_delta(acct, ln.direction, ln.amount_minor)
        AccountBalance.objects.filter(account=acct).update(balance_minor=models_f("balance_minor") + delta)

    OutboxEvent.objects.create(
        tenant_id=entry.tenant_id,
        aggregate_type="ledger.JournalEntry",
        aggregate_id=entry.id,
        event_type="ledger.journal_entry.posted",
        payload={
            "currency": currency,
            "memo": memo,
            "lines": [
                {"account_id": ln.account_id, "direction": ln.direction, "amount_minor": ln.amount_minor}
                for ln in lines
            ],
        },
    )

    # Every derived figure in the product — dashboards, health scores, reports —
    # is computed from the ledger and cached against a per-tenant version. This
    # is the single choke point through which all financial state changes, so
    # bumping the version here is what keeps every one of those caches honest.
    #
    # `on_commit` rather than inline: a rolled-back posting must not invalidate
    # anything, and an invalidation that fires before the data is visible would
    # let a concurrent read repopulate the cache with pre-write figures.
    _invalidate_derived_caches(entry.tenant_id)

    return entry


def _invalidate_derived_caches(tenant_id) -> None:
    """Schedule a cache-version bump for after this transaction commits.

    Failures are swallowed deliberately: a cache backend being unreachable must
    never roll back a posted journal entry. The TTL backstop bounds how long a
    stale figure can survive if this does fail.
    """
    from apps.common.cache import invalidate_tenant

    def _bump():
        try:
            invalidate_tenant(tenant_id)
        except Exception:  # pragma: no cover - cache backend failure
            logger.warning("cache invalidation failed for tenant %s", tenant_id, exc_info=True)

    transaction.on_commit(_bump)


@transaction.atomic
def reverse_journal_entry(*, entry: JournalEntry, idempotency_key: str, memo: str = "") -> JournalEntry:
    """Correct a mistake by posting the mirror image — never by mutating history."""
    original_lines = list(entry.lines.select_related("account"))
    flipped = [
        LineInput(
            account_id=str(ln.account_id),
            direction=Direction.CREDIT if ln.direction == Direction.DEBIT else Direction.DEBIT,
            amount_minor=ln.amount_minor,
        )
        for ln in original_lines
    ]
    return post_journal_entry(
        occurred_at=entry.occurred_at,
        lines=flipped,
        idempotency_key=idempotency_key,
        memo=memo or f"Reversal of {entry.id}",
        reverses=entry,
    )


# imported lazily to keep the module import graph clean in tooling
from django.db.models import F as models_f  # noqa: E402
