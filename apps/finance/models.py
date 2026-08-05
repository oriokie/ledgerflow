"""Finance context — the user-facing domain layer over the ledger.

Every mutable model here inherits SoftDeletableModel (tenant-scoped + soft
delete + audit stamps). The immutable accounting truth lives in `ledger`.
"""

from __future__ import annotations

from django.contrib.postgres.indexes import BrinIndex, GinIndex
from django.db import models

from apps.common.models import SoftDeletableModel, TimeStampedModel, UUIDModel
from apps.ledger.models import Account as LedgerAccount


class Institution(UUIDModel, TimeStampedModel):
    """Global reference data (banks/providers). Shared across tenants."""

    name = models.CharField(max_length=160)
    country = models.CharField(max_length=2, blank=True, default="")  # ISO-3166 alpha-2
    swift_bic = models.CharField(max_length=11, blank=True, default="")
    logo_url = models.URLField(blank=True, default="")
    aggregator = models.CharField(max_length=40, blank=True, default="")  # plaid/truelayer/...
    external_id = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["name"])]
        constraints = [
            models.UniqueConstraint(
                fields=["aggregator", "external_id"],
                name="uniq_institution_external",
                condition=~models.Q(external_id=""),
            )
        ]


class AccountType(models.TextChoices):
    CHECKING = "checking", "Checking"
    SAVINGS = "savings", "Savings"
    CREDIT_CARD = "credit_card", "Credit card"
    LOAN = "loan", "Loan"
    CASH = "cash", "Cash"
    INVESTMENT = "investment", "Investment"
    OTHER = "other", "Other"


class Wallet(SoftDeletableModel):
    """A named grouping of one or more FinancialAccounts — the multi-currency
    "wallet" concept (e.g. a Revolut-style pot holding USD + EUR + GBP
    accounts together, or simply "Travel Fund").

    Deliberately NOT a new ledger primitive: a wallet never posts anything
    itself. It's a presentation/grouping layer over accounts that already
    exist, each still single-currency and each still backed by its own
    ledger.Account. Wallet balance is computed by summing member accounts'
    materialized balances **per currency** — no blind cross-currency sum,
    same discipline as net_worth().
    """

    name = models.CharField(max_length=120)
    icon = models.CharField(max_length=40, blank=True, default="")
    color = models.CharField(max_length=9, blank=True, default="")
    is_default = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "name"],
                name="uniq_wallet_name",
                condition=models.Q(deleted_at__isnull=True),
            ),
        ]

    def __str__(self) -> str:
        return self.name


class FinancialAccount(SoftDeletableModel):
    """A real-world account the user holds, backed by one ledger Account."""

    name = models.CharField(max_length=120)
    account_type = models.CharField(max_length=16, choices=AccountType.choices)
    institution = models.ForeignKey(
        Institution, null=True, blank=True, on_delete=models.SET_NULL, related_name="accounts"
    )
    wallet = models.ForeignKey(
        Wallet, null=True, blank=True, on_delete=models.SET_NULL, related_name="accounts"
    )
    currency = models.CharField(max_length=3)
    mask = models.CharField(max_length=4, blank=True, default="")  # last 4 digits only
    # One-to-one link to the accounting primitive that tracks its balance.
    ledger_account = models.OneToOneField(
        LedgerAccount, on_delete=models.PROTECT, related_name="financial_account"
    )
    is_active = models.BooleanField(default=True)

    # --- presentation -------------------------------------------------------
    # Personalisation is not decoration in a finance product: users hold several
    # near-identical accounts ("Chase Checking", "Chase Savings") and colour +
    # icon are how they're told apart at a glance. Mirrors Category, which
    # already carries the same two fields.
    color = models.CharField(max_length=9, blank=True, default="")
    icon = models.CharField(max_length=40, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    # --- lifecycle ----------------------------------------------------------
    # Archiving is NOT deletion. A closed account keeps every transaction it
    # ever had — deleting it would tear a hole in historical reports and orphan
    # ledger lines that must remain immutable. Archived accounts stop appearing
    # in pickers and default lists but their history stays intact and auditable.
    archived_at = models.DateTimeField(null=True, blank=True)

    # Hidden accounts still count toward net worth and budgets; they're merely
    # collapsed out of the default UI. This is deliberately distinct from
    # archiving (lifecycle) and from exclusion (arithmetic).
    is_hidden = models.BooleanField(default=False)

    # --- inclusion ----------------------------------------------------------
    # Some accounts shouldn't count toward the user's own position: a business
    # account inside a personal workspace, an account held for a relative, or a
    # security deposit. Excluding is a *reporting* choice — the ledger still
    # records every entry, so nothing about accounting integrity changes.
    include_in_net_worth = models.BooleanField(default=True)
    include_in_budgets = models.BooleanField(default=True)

    # --- overdraft ----------------------------------------------------------
    # How far below zero this account is allowed to go, as a positive figure.
    # Zero — the default — means a posting that would leave the account
    # overdrawn is refused outright.
    #
    # A limit rather than a boolean because an arranged overdraft is a real
    # arrangement with a real ceiling, and "may go negative: yes/no" cannot
    # express it. Applies only to asset accounts; a credit card or loan is
    # *supposed* to carry a balance owed, and is never checked.
    overdraft_limit_minor = models.BigIntegerField(default=0)

    # Aggregation sync state
    external_id = models.CharField(max_length=128, blank=True, default="")
    last_synced_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)  # extensibility hatch

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(overdraft_limit_minor__gte=0),
                name="faccount_overdraft_limit_non_negative",
            ),
            models.UniqueConstraint(
                fields=["tenant_id", "name"],
                name="uniq_faccount_name",
                condition=models.Q(deleted_at__isnull=True),
            ),
            models.UniqueConstraint(
                fields=["external_id"], name="uniq_faccount_external", condition=~models.Q(external_id="")
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "account_type", "is_active"]),
            models.Index(fields=["tenant_id", "wallet"]),
            GinIndex(fields=["metadata"], name="faccount_metadata_gin"),
        ]


class CategoryKind(models.TextChoices):
    INCOME = "income", "Income"
    EXPENSE = "expense", "Expense"
    TRANSFER = "transfer", "Transfer"


class Category(SoftDeletableModel):
    """Hierarchical taxonomy. `path`/`depth` give O(1) subtree filtering
    (materialized path) without recursive CTEs on the hot read path."""

    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=80, blank=True, default="")  # stable machine reference for rules
    kind = models.CharField(max_length=10, choices=CategoryKind.choices)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    path = models.CharField(max_length=255, db_index=True, default="")  # e.g. "food.groceries"
    depth = models.PositiveSmallIntegerField(default=0)
    is_system = models.BooleanField(default=False)
    color = models.CharField(max_length=9, blank=True, default="")
    icon = models.CharField(max_length=40, blank=True, default="")
    # Contra ledger account so a spend posts a real double-entry line.
    ledger_account = models.OneToOneField(
        LedgerAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="category"
    )

    class Meta:
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "parent", "name"],
                name="uniq_category_name_parent",
                condition=models.Q(deleted_at__isnull=True),
            ),
            models.UniqueConstraint(
                fields=["tenant_id", "slug"],
                name="uniq_category_slug",
                condition=models.Q(deleted_at__isnull=True) & ~models.Q(slug=""),
            ),
        ]
        indexes = [models.Index(fields=["tenant_id", "kind"])]


class Payee(SoftDeletableModel):
    name = models.CharField(max_length=160)
    normalized_name = models.CharField(max_length=160, db_index=True)  # lowercased/stripped
    default_category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="payees"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "normalized_name"],
                name="uniq_payee_normalized",
                condition=models.Q(deleted_at__isnull=True),
            ),
        ]


class Tag(SoftDeletableModel):
    name = models.CharField(max_length=40)
    color = models.CharField(max_length=9, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "name"],
                name="uniq_tag_name",
                condition=models.Q(deleted_at__isnull=True),
            ),
        ]


class TransactionStatus(models.TextChoices):
    PENDING = "pending", "Pending"  # observed (bank feed) but not cleared
    POSTED = "posted", "Posted"  # written to the ledger
    RECONCILED = "reconciled", "Reconciled"
    VOID = "void", "Void"


class TransactionSource(models.TextChoices):
    MANUAL = "manual", "Manual"
    IMPORTED = "imported", "Imported"
    RULE = "rule", "Rule"
    RECURRING = "recurring", "Recurring"


class Transaction(SoftDeletableModel):
    """Domain aggregate the user edits. Posts to an immutable JournalEntry.

    Partitioned by RANGE(occurred_at) monthly on the Postgres target (see
    migration notes). `amount_minor` is signed (negative = money out) and
    denormalized from the entry for fast statements and category sums.
    """

    financial_account = models.ForeignKey(
        FinancialAccount, on_delete=models.PROTECT, related_name="transactions"
    )
    # FK (not OneToOne): one balanced JournalEntry underlies a transfer that
    # surfaces as TWO domain transactions (one per account). Income/expense
    # entries still back exactly one transaction.
    journal_entry = models.ForeignKey(
        "ledger.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="transactions"
    )
    amount_minor = models.BigIntegerField()  # signed
    currency = models.CharField(max_length=3)
    occurred_at = models.DateTimeField()
    posted_at = models.DateTimeField(null=True, blank=True)
    #: When a human confirmed this row against a statement. Null while the row
    #: is merely POSTED — the two together are what let a reconciliation screen
    #: say "last reconciled on X" without storing a second balance anywhere.
    reconciled_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=12, choices=TransactionStatus.choices, default=TransactionStatus.PENDING
    )
    source = models.CharField(
        max_length=12, choices=TransactionSource.choices, default=TransactionSource.MANUAL
    )
    payee = models.ForeignKey(
        Payee, null=True, blank=True, on_delete=models.SET_NULL, related_name="transactions"
    )
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="transactions"
    )
    counter_account = models.ForeignKey(  # set for transfers: points at the OTHER account
        FinancialAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="incoming_transfers"
    )
    # Pairs the two halves of a transfer. NULL for income/expense. Both halves
    # share this id, letting either be found from the other and letting
    # income/expense reports exclude transfers with a single index lookup.
    transfer_group = models.UUIDField(null=True, blank=True, db_index=True)
    # Pairs the parts of a split transaction (one purchase divided across
    # several categories). NULL for ordinary transactions. All parts share this
    # id and one backing JournalEntry, letting a statement collapse or expand
    # them and letting reports treat the parts as the single purchase they are.
    split_group = models.UUIDField(null=True, blank=True, db_index=True)
    memo = models.CharField(max_length=255, blank=True, default="")
    external_id = models.CharField(max_length=128, blank=True, default="")  # import idempotency
    # Set by automation's flag_review action (and manual review requests). A
    # real, queryable state — not a no-op — so a review queue can surface it.
    needs_review = models.BooleanField(default=False)
    review_reason = models.CharField(max_length=255, blank=True, default="")
    tags = models.ManyToManyField(Tag, through="TransactionTag", related_name="transactions")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            # idempotent imports: one row per (account, provider id)
            models.UniqueConstraint(
                fields=["financial_account", "external_id"],
                name="uniq_txn_external",
                condition=~models.Q(external_id=""),
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "financial_account", "-occurred_at"]),  # statements
            models.Index(fields=["tenant_id", "category", "-occurred_at"]),  # budgets
            # Global transaction list is cursor-paginated on (-occurred_at, -id);
            # this composite lets the paginator walk the index instead of a
            # top-N sort over the whole tenant (which grows with row count).
            models.Index(
                fields=["tenant_id", "-occurred_at", "-id"],
                name="txn_list_cursor_idx",
            ),
            # Reports/cash-flow/category-breakdown always exclude transfers;
            # a partial index keeps them off the transfer rows entirely.
            models.Index(
                fields=["tenant_id", "-occurred_at"],
                name="txn_non_transfer_idx",
                condition=models.Q(transfer_group__isnull=True),
            ),
            models.Index(
                fields=["tenant_id", "status"],
                name="txn_status_pending",
                condition=models.Q(status="pending"),
            ),  # partial
            models.Index(
                fields=["tenant_id", "-occurred_at"],
                name="txn_needs_review",
                condition=models.Q(needs_review=True),
            ),  # review queue (partial)
            BrinIndex(fields=["occurred_at"], name="txn_occurred_brin"),
            GinIndex(fields=["metadata"], name="txn_metadata_gin"),
        ]


class TransactionTag(SoftDeletableModel):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="tag_links")
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name="tag_links")

    class Meta:
        constraints = [
            # scoped to live rows only — without this, removing and
            # re-adding the same tag to a transaction would permanently
            # collide with its own soft-deleted history
            models.UniqueConstraint(
                fields=["transaction", "tag"],
                name="uniq_transaction_tag",
                condition=models.Q(deleted_at__isnull=True),
            ),
        ]


class AttachmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"  # row created, presigned upload issued, file not yet confirmed
    UPLOADED = "uploaded", "Uploaded"


class Attachment(SoftDeletableModel):
    """Receipts/documents. The blob lives in cloud object storage; we store the
    key + metadata only. Two-step lifecycle: the client never proxies the
    file through the app server — it requests a presigned PUT URL (creating
    a PENDING row), uploads directly to the bucket, then confirms."""

    transaction = models.ForeignKey(
        Transaction, null=True, blank=True, on_delete=models.CASCADE, related_name="attachments"
    )
    storage_key = models.CharField(max_length=512)  # s3://bucket/key
    content_type = models.CharField(max_length=100)
    byte_size = models.BigIntegerField()
    checksum = models.CharField(max_length=64, blank=True, default="")  # sha-256
    status = models.CharField(
        max_length=10, choices=AttachmentStatus.choices, default=AttachmentStatus.PENDING
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(byte_size__gt=0), name="attachment_size_positive"),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "transaction"]),
            models.Index(fields=["tenant_id", "status"]),
        ]


class Frequency(models.TextChoices):
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"
    YEARLY = "yearly", "Yearly"


class RecurringType(models.TextChoices):
    INCOME = "income", "Income"
    EXPENSE = "expense", "Expense"
    TRANSFER = "transfer", "Transfer"


class RecurringTransaction(SoftDeletableModel):
    """A schedule template. A Celery beat task materializes real Transactions
    from every due template daily. The template itself never touches the
    ledger; only the materialized transactions do — so a template can be
    edited or paused without rewriting history already posted from it.

    `amount_minor` is always positive here; the sign of the resulting
    transaction is derived from `txn_type`, exactly like the one-off
    record_income/record_expense services.
    """

    txn_type = models.CharField(max_length=10, choices=RecurringType.choices)
    financial_account = models.ForeignKey(
        FinancialAccount, on_delete=models.PROTECT, related_name="recurring_transactions"
    )
    counter_account = models.ForeignKey(  # required for transfers
        FinancialAccount,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="incoming_recurring_transactions",
    )
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="recurring_transactions"
    )
    payee = models.ForeignKey(
        Payee, null=True, blank=True, on_delete=models.SET_NULL, related_name="recurring_transactions"
    )
    amount_minor = models.BigIntegerField()  # positive
    currency = models.CharField(max_length=3)
    memo = models.CharField(max_length=255, blank=True, default="")

    # schedule
    frequency = models.CharField(max_length=10, choices=Frequency.choices)
    interval = models.PositiveSmallIntegerField(default=1)  # every N periods
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    max_occurrences = models.PositiveIntegerField(null=True, blank=True)

    # runtime state
    next_run_on = models.DateField(db_index=True)
    occurrences_created = models.PositiveIntegerField(default=0)
    last_run_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(amount_minor__gt=0), name="recurring_amount_positive"),
            models.CheckConstraint(condition=models.Q(interval__gte=1), name="recurring_interval_min"),
        ]
        indexes = [
            # the scheduler's hot query: active templates that are due
            models.Index(fields=["tenant_id", "is_active", "next_run_on"], name="recurring_due_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.txn_type} {self.amount_minor} {self.frequency} (next {self.next_run_on})"


class BillStatus(models.TextChoices):
    UPCOMING = "upcoming", "Upcoming"
    PAID = "paid", "Paid"
    OVERDUE = "overdue", "Overdue"
    CANCELLED = "cancelled", "Cancelled"


class Bill(SoftDeletableModel):
    """A known amount owed with a due date the user can mark paid.

    Distinct from RecurringTransaction: a recurring transaction *auto-posts*
    money that has already moved on a schedule; a Bill is money you *will* owe
    and haven't paid yet — it drives "due soon" views and reminders, and is
    marked paid (optionally linking the transaction that settled it) rather than
    posting on its own. A recurring bill can spawn the next occurrence on
    payment, but the money movement is always an explicit, user-confirmed
    transaction, never an automatic post.
    """

    name = models.CharField(max_length=120)
    payee = models.ForeignKey(Payee, null=True, blank=True, on_delete=models.SET_NULL, related_name="bills")
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="bills"
    )
    amount_minor = models.BigIntegerField()  # > 0, expected amount
    currency = models.CharField(max_length=3)
    due_on = models.DateField(db_index=True)
    status = models.CharField(max_length=10, choices=BillStatus.choices, default=BillStatus.UPCOMING)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_transaction = models.ForeignKey(
        Transaction,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="settled_bills",
    )
    # optional recurrence: if set, paying this bill schedules the next one
    recurrence_frequency = models.CharField(max_length=10, choices=Frequency.choices, blank=True, default="")
    recurrence_interval = models.PositiveSmallIntegerField(default=1)
    autopay_account = models.ForeignKey(
        FinancialAccount,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="autopay_bills",
    )
    notes = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(amount_minor__gt=0), name="bill_amount_positive"),
        ]
        indexes = [
            # "what's due soon" — upcoming bills by due date (partial)
            models.Index(
                fields=["tenant_id", "due_on"],
                name="bill_upcoming_idx",
                condition=models.Q(status="upcoming"),
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} {self.amount_minor} {self.currency} due {self.due_on}"
