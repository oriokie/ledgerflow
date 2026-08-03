"""Statement reconciliation — confirming the ledger against the bank.

`TransactionStatus.RECONCILED` has existed since the first migration and was
read by two selectors, but nothing ever wrote it: the state was unreachable.
This module is the missing transition.

Why it matters more than its size suggests: reconciliation is the ritual by
which a ledger earns belief. Until a user can tick off what actually cleared
and see the difference reach zero, the balance on screen is a number they have
no way to confirm — so they check their bank's app instead, and at that point
the bank's app is the product.

Design
------
* **Marking is reversible.** `RECONCILED` and `POSTED` differ only in whether a
  human has confirmed the row against a statement. Unmarking is a normal
  correction, not an exception, because people mis-tick.
* **Voided rows are never reconcilable.** A void has no counterpart on any
  statement; allowing it would let the difference be forced to zero with a row
  that represents nothing.
* **The difference is computed, never stored.** `reconciliation_summary` sums
  ledger rows on demand. Storing a "last reconciled balance" would create a
  second source of truth for the one number the feature exists to establish.
* **Nothing is auto-reconciled.** The product's rule is that automation
  proposes and a person disposes; reconciliation *is* the disposing. A bank
  feed can mark rows `PENDING` and suggest matches, but the confirmation is the
  user's — that is the entire value of the step.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.db.models import Sum

from apps.common import audit

from .models import FinancialAccount, Transaction, TransactionStatus

logger = logging.getLogger("ledgerflow.finance.reconciliation")

#: Rows that represent real money and can therefore be confirmed.
RECONCILABLE = (TransactionStatus.POSTED, TransactionStatus.RECONCILED)


class ReconciliationError(Exception):
    """Raised when a reconciliation operation is invalid in the current state."""


@dataclass(frozen=True)
class ReconciliationSummary:
    """Where an account stands against a statement.

    `difference_minor` is the number the user is trying to drive to zero, so it
    is stated explicitly rather than left for the client to subtract — a
    reconciliation screen that makes the reader do arithmetic has missed the
    point.
    """

    account_id: str
    currency: str
    reconciled_minor: int
    uncleared_minor: int
    ledger_balance_minor: int
    statement_balance_minor: int | None
    difference_minor: int | None
    reconciled_count: int
    uncleared_count: int
    last_reconciled_at: object | None

    @property
    def is_balanced(self) -> bool:
        return self.difference_minor == 0


def _signed_total(queryset) -> int:
    """Net movement of a set of transactions, in minor units.

    `amount_minor` is already signed, so this is a plain sum — outflows are
    negative in the column itself rather than being encoded as a magnitude plus
    a direction.
    """
    return queryset.aggregate(total=Sum("amount_minor"))["total"] or 0


def reconciliation_summary(
    *,
    account: FinancialAccount,
    statement_balance_minor: int | None = None,
    as_of: date | None = None,
) -> ReconciliationSummary:
    """Reconciled vs uncleared for one account, and the gap to a statement."""
    rows = Transaction.objects.filter(financial_account=account, status__in=RECONCILABLE)
    if as_of is not None:
        rows = rows.filter(occurred_at__date__lte=as_of)

    reconciled = rows.filter(status=TransactionStatus.RECONCILED)
    uncleared = rows.filter(status=TransactionStatus.POSTED)

    reconciled_minor = _signed_total(reconciled)
    uncleared_minor = _signed_total(uncleared)

    last = (
        reconciled.order_by("-reconciled_at").values_list("reconciled_at", flat=True).first()
    )

    difference = None
    if statement_balance_minor is not None:
        # The statement should equal everything confirmed so far. What is left
        # over is exactly what has not yet cleared — or a genuine discrepancy,
        # which is the thing worth finding.
        difference = statement_balance_minor - reconciled_minor

    return ReconciliationSummary(
        account_id=str(account.id),
        currency=account.currency,
        reconciled_minor=reconciled_minor,
        uncleared_minor=uncleared_minor,
        ledger_balance_minor=reconciled_minor + uncleared_minor,
        statement_balance_minor=statement_balance_minor,
        difference_minor=difference,
        reconciled_count=reconciled.count(),
        uncleared_count=uncleared.count(),
        last_reconciled_at=last,
    )


@transaction.atomic
def set_reconciled(
    *, transactions: list[Transaction], reconciled: bool, actor_id=audit.UNSET
) -> int:
    """Mark rows confirmed against a statement, or undo that. Returns the count.

    Takes a list so a reconciliation screen can commit a whole session's ticks
    in one request — the natural unit of the task is "everything I just
    checked", not one row at a time.
    """
    from django.utils import timezone

    if not transactions:
        return 0

    ids = []
    for txn in transactions:
        if txn.status == TransactionStatus.VOID:
            raise ReconciliationError(
                "A voided transaction has no counterpart on a statement and "
                "cannot be reconciled."
            )
        if txn.status not in RECONCILABLE:
            raise ReconciliationError(
                f"A {txn.get_status_display().lower()} transaction cannot be reconciled."
            )
        ids.append(txn.pk)

    now = timezone.now()
    updated = Transaction.objects.filter(pk__in=ids).update(
        status=TransactionStatus.RECONCILED if reconciled else TransactionStatus.POSTED,
        reconciled_at=now if reconciled else None,
        updated_at=now,
    )

    audit.record(
        action="transactions.reconciled" if reconciled else "transactions.unreconciled",
        target_type="finance.Transaction",
        target_id=ids[0] if len(ids) == 1 else None,
        changes={"count": [None, updated]},
        actor_id=actor_id,
    )
    logger.info("reconciled=%s for %s transaction(s)", reconciled, updated)
    return updated


def uncleared_transactions(*, account: FinancialAccount, as_of: date | None = None):
    """Rows still awaiting confirmation, oldest first.

    Oldest-first because reconciliation works forward from the last statement,
    and the oldest uncleared item is the one most likely to be a genuine
    problem rather than simply in flight.
    """
    rows = Transaction.objects.filter(financial_account=account, status=TransactionStatus.POSTED)
    if as_of is not None:
        rows = rows.filter(occurred_at__date__lte=as_of)
    return rows.select_related("category").order_by("occurred_at", "id")
