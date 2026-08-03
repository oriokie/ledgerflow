"""Ledger read side. Every selector is written to avoid N+1s explicitly."""

from __future__ import annotations

from django.db.models import Prefetch

from apps.common.money import Money

from .models import Account, JournalEntry, LedgerLine


def list_accounts(*, include_system: bool = True):
    qs = Account.objects.all()
    if not include_system:
        qs = qs.filter(is_system=False)
    # one extra query for all balances via the reverse OneToOne, not one-per-row
    return qs.select_related("balance").order_by("kind", "name")


def account_balance(account: Account) -> Money:
    # `balance` is materialized; no aggregation over lines at read time.
    return Money(account.balance.balance_minor, account.balance.currency)


def recompute_balance_minor(account: Account) -> int:
    """Source-of-truth recomputation from immutable lines (for reconciliation)."""
    from .services import _signed_delta  # local import avoids cycle

    total = 0
    for line in LedgerLine.objects.filter(account=account).only("direction", "amount_minor"):
        total += _signed_delta(account, line.direction, line.amount_minor)
    return total


def list_entries(*, limit: int = 50, offset: int = 0):
    # Prefetch lines + their accounts so serializing N entries stays at ~3 queries.
    lines_qs = LedgerLine.objects.select_related("account").order_by("id")
    return JournalEntry.objects.prefetch_related(Prefetch("lines", queryset=lines_qs)).order_by(
        "-occurred_at", "-id"
    )[offset : offset + limit]
