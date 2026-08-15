"""Ledger context — the immutable, append-only, double-entry core.

Base class is TenantOwnedModel (NOT SoftDeletableModel): ledger records are
never deleted. A DB trigger (see migration) blocks UPDATE/DELETE on these tables.
Corrections are reversing entries.
"""

from __future__ import annotations

from django.contrib.postgres.indexes import BrinIndex
from django.db import models

from apps.common.models import TenantOwnedModel


class AccountKind(models.TextChoices):
    ASSET = "asset", "Asset"
    LIABILITY = "liability", "Liability"
    EQUITY = "equity", "Equity"
    INCOME = "income", "Income"
    EXPENSE = "expense", "Expense"


NORMAL_DEBIT = {AccountKind.ASSET, AccountKind.EXPENSE}


class Direction(models.TextChoices):
    DEBIT = "debit", "Debit"
    CREDIT = "credit", "Credit"


class Account(TenantOwnedModel):
    """Accounting primitive. FinancialAccounts and Categories point at these."""

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=AccountKind.choices)
    currency = models.CharField(max_length=3)
    is_system = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "name", "kind"], name="uniq_account_name_kind"),
            models.CheckConstraint(
                condition=models.Q(currency__regex=r"^[A-Z]{3}$"), name="account_currency_iso"
            ),
        ]
        indexes = [models.Index(fields=["tenant_id", "kind"])]

    @property
    def normal_debit(self) -> bool:
        return self.kind in NORMAL_DEBIT


class JournalEntry(TenantOwnedModel):
    occurred_at = models.DateTimeField()
    currency = models.CharField(max_length=3)
    memo = models.CharField(max_length=255, blank=True, default="")
    idempotency_key = models.CharField(max_length=128)
    reverses = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_by"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "idempotency_key"], name="uniq_entry_idempotency"),
            # One reversing entry per original. Voiding both legs of a transfer
            # (or every part of a split) must not post a second mirror.
            models.UniqueConstraint(
                fields=["reverses"],
                condition=models.Q(reverses__isnull=False),
                name="uniq_entry_reverses",
            ),
        ]
        # BRIN: tiny index ideal for append-only, time-ordered rows at scale.
        indexes = [BrinIndex(fields=["occurred_at"], name="journalentry_occurred_brin")]


class LedgerLine(TenantOwnedModel):
    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="lines")
    direction = models.CharField(max_length=6, choices=Direction.choices)
    amount_minor = models.BigIntegerField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(amount_minor__gt=0), name="line_amount_positive"),
        ]
        indexes = [models.Index(fields=["tenant_id", "account", "id"])]


class AccountBalance(TenantOwnedModel):
    account = models.OneToOneField(Account, on_delete=models.CASCADE, related_name="balance")
    balance_minor = models.BigIntegerField(default=0)
    currency = models.CharField(max_length=3)
