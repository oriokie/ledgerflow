"""Receivables — money other people owe you.

Why this exists
---------------
The product modelled every liability in detail and had no model of the other
direction at all. A household could record that it owed a friend 5,000, but not
that a friend owed *it* 5,000 — so the money simply vanished from the picture
between lending it and getting it back. For the informal lending most
households actually do, that is not a rounding error: it is often the largest
single thing they are owed, and it is the one most likely to be forgotten.

Why a separate app rather than a direction flag on `debt`
---------------------------------------------------------
They look symmetric and are not. A debt has an APR, a minimum payment, a
statement day and a payoff strategy — an entire planning apparatus built around
the question "how do I get out of this fastest?". A receivable has none of
that. Its questions are different ones: who owes me, how long has it been, and
am I ever going to see it again. Forcing both through one model would mean half
the fields are meaningless in either direction, and a payoff planner that has
to keep asking which way round it is.

Accounting
----------
A receivable is an **asset**: money you are owed is money you have a claim to.
It is modelled as its own record rather than as a `FinancialAccount`, because
an informal loan to a friend is not an account you hold at an institution and
giving it one would put it in account pickers, transfer dialogs and
reconciliation screens where it has no business being.

That means a receivable's balance is **not** in the ledger, and it deliberately
does not move net worth on its own. Lending someone money already shows in the
ledger as cash leaving your account; counting the receivable as well would
double-count it. What this module adds is the *memory* of where that money went
and whether it came back.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import SoftDeletableModel


class ReceivableKind(models.TextChoices):
    """What sort of claim this is.

    Drives presentation and expectations, not arithmetic. A personal loan to a
    sibling and an unpaid invoice behave identically as balances; they differ
    entirely in how you'd chase them.
    """

    PERSONAL = "personal", "Money I lent someone"
    INVOICE = "invoice", "Unpaid invoice"
    REIMBURSEMENT = "reimbursement", "Owed a reimbursement"
    DEPOSIT = "deposit", "Deposit held by someone else"
    OTHER = "other", "Something else"


class ReceivableStatus(models.TextChoices):
    OUTSTANDING = "outstanding", "Outstanding"
    #: Every cent accounted for. Set by the service when repayments reach the
    #: full amount, never by hand — a status that can disagree with the sums
    #: beneath it is a status nobody can trust.
    SETTLED = "settled", "Settled"
    #: Given up on. Kept rather than deleted: writing something off is a fact
    #: worth remembering, both for the user and for anyone deciding whether to
    #: lend to that person again.
    WRITTEN_OFF = "written_off", "Written off"


class Receivable(SoftDeletableModel):
    """One claim on someone else's money."""

    #: Who owes it. Free text, deliberately: a friend is not an institution and
    #: is not a `Payee` either — payees are who you *pay*. Modelling a person
    #: you lent 2,000 to as a merchant would be the wrong shape entirely.
    counterparty = models.CharField(max_length=120)
    kind = models.CharField(max_length=20, choices=ReceivableKind.choices, default=ReceivableKind.PERSONAL)
    description = models.CharField(max_length=255, blank=True, default="")

    currency = models.CharField(max_length=3)
    #: What was originally owed, always positive. Never reduced by repayments —
    #: the outstanding figure is derived by subtracting them, so the original
    #: amount stays available and the history stays legible. The same
    #: separation `IncomeSource` keeps from `IncomeReceipt`.
    principal_minor = models.BigIntegerField()

    lent_on = models.DateField()
    #: When it was promised back. Null is honest and common — most informal
    #: loans have no date attached, and inventing one would manufacture an
    #: overdue warning nobody agreed to.
    due_on = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=12, choices=ReceivableStatus.choices, default=ReceivableStatus.OUTSTANDING
    )
    #: Where the money came from when it was lent. Advisory and optional: it
    #: links the claim back to the transaction that created it without
    #: requiring one, since plenty of lending happens in cash.
    source_account = models.ForeignKey(
        "finance.FinancialAccount",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="receivables",
    )
    notes = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(principal_minor__gt=0), name="receivable_principal_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(due_on__isnull=True) | models.Q(due_on__gte=models.F("lent_on")),
                name="receivable_due_after_lent",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "status"], name="receivable_status_idx"),
            models.Index(fields=["tenant_id", "due_on"], name="receivable_due_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.counterparty} owes {self.principal_minor} {self.currency}"


class Repayment(SoftDeletableModel):
    """Money actually received against a receivable.

    Separate rows rather than a running balance on the receivable, for the same
    reason the ledger is made of entries: a single mutable balance cannot say
    when anything was paid, and cannot be corrected without destroying the
    history that produced it. Part-payments are the norm with informal loans.
    """

    receivable = models.ForeignKey(Receivable, on_delete=models.CASCADE, related_name="repayments")
    received_on = models.DateField()
    amount_minor = models.BigIntegerField()
    #: Provenance link to the real ledger movement, when one is known.
    #: Advisory: a repayment is a fact whether or not it was matched.
    transaction = models.ForeignKey(
        "finance.Transaction",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="receivable_repayments",
    )
    memo = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(amount_minor__gt=0), name="repayment_amount_positive"),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "receivable", "-received_on"], name="repayment_hist_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.amount_minor} on {self.received_on}"
