"""Ledger service layer — the heart of the product.

`post_journal_entry` is the single choke point through which all money moves.
It enforces the double-entry invariant, single-currency rule, idempotency, and
updates materialized balances + the audit outbox — all in one DB transaction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, connection, transaction

from apps.common.outbox import OutboxEvent
from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import get_current_tenant_id, use_tenant

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
    except IntegrityError:
        # Lost a race on idempotency_key, or on "one reversal per original".
        winner = JournalEntry.objects.filter(idempotency_key=idempotency_key).first()
        if winner is not None:
            return winner
        if reverses is not None:
            winner = JournalEntry.objects.filter(reverses=reverses).first()
            if winner is not None:
                return winner
        raise

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
    """Correct a mistake by posting the mirror image — never by mutating history.

    An entry may be reversed only once. A transfer (and a split) is several
    domain rows on one journal; voiding the second row must return the same
    reversal, not post another copy that would overshoot the accounts.
    """
    locked = JournalEntry.objects.select_for_update().get(pk=entry.pk)
    existing = JournalEntry.objects.filter(reverses_id=locked.id).first()
    if existing is not None:
        return existing
    original_lines = list(locked.lines.select_related("account"))
    flipped = [
        LineInput(
            account_id=str(ln.account_id),
            direction=Direction.CREDIT if ln.direction == Direction.DEBIT else Direction.DEBIT,
            amount_minor=ln.amount_minor,
        )
        for ln in original_lines
    ]
    return post_journal_entry(
        occurred_at=locked.occurred_at,
        lines=flipped,
        idempotency_key=idempotency_key,
        memo=memo or f"Reversal of {locked.id}",
        reverses=locked,
    )


def correct_duplicate_reversals() -> int:
    """Undo extra reversing journals left by voiding both legs of a transfer.

    Journal rows are append-only, so the extras are not deleted. The first
    reversal of each original is kept; every later reversal of that same
    original is itself reversed, which restores the balances the first
    reversal already produced. Safe to run more than once: a second pass
    finds the extras already reversed and posts nothing.
    """
    if get_current_tenant_id() is not None:
        return _correct_duplicate_reversals_for_current_tenant()

    repaired = 0
    for tenant_id in _tenant_ids_to_scan():
        with transaction.atomic():
            bind_db_tenant(tenant_id)
            with use_tenant(tenant_id):
                repaired += _correct_duplicate_reversals_for_current_tenant()
    return repaired


def _tenant_ids_to_scan():
    from apps.tenancy.models import Tenant

    ids = list(Tenant.objects.values_list("id", flat=True))
    if ids:
        return ids
    if connection.vendor != "postgresql":
        return list(
            JournalEntry.unscoped.filter(reverses_id__isnull=False)
            .values_list("tenant_id", flat=True)
            .distinct()
        )
    # FORCE RLS hides every journal row when migrate has no tenant GUC.
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE ledger_journalentry NO FORCE ROW LEVEL SECURITY")
        try:
            cursor.execute("""
                SELECT tenant_id
                FROM ledger_journalentry
                WHERE reverses_id IS NOT NULL
                GROUP BY tenant_id, reverses_id
                HAVING COUNT(*) > 1
                """)
            return list({row[0] for row in cursor.fetchall()})
        finally:
            cursor.execute("ALTER TABLE ledger_journalentry FORCE ROW LEVEL SECURITY")


def _correct_duplicate_reversals_for_current_tenant() -> int:
    first_by_original: dict = {}
    extras: list[JournalEntry] = []
    for entry in JournalEntry.objects.filter(reverses_id__isnull=False).order_by("created_at", "id"):
        if entry.reverses_id in first_by_original:
            extras.append(entry)
        else:
            first_by_original[entry.reverses_id] = entry
    if extras:
        logger.warning(
            "correcting %s duplicate reversal(s) for tenant %s",
            len(extras),
            get_current_tenant_id(),
        )
    for extra in extras:
        reverse_journal_entry(
            entry=extra,
            idempotency_key=f"fix-dup-reversal:{extra.id}",
            memo=f"Correct duplicate reversal of {extra.reverses_id}",
        )
    return len(extras)


# imported lazily to keep the module import graph clean in tooling
from django.db.models import F as models_f  # noqa: E402
