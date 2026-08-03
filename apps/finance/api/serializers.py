from __future__ import annotations

from rest_framework import serializers

from ..models import (
    AccountType,
    CategoryKind,
    Frequency,
    RecurringType,
)


# ------------------------------------------------------------------ accounts
class FinancialAccountCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    account_type = serializers.ChoiceField(choices=AccountType.choices)
    currency = serializers.CharField(max_length=3, min_length=3)
    mask = serializers.CharField(max_length=4, required=False, allow_blank=True, default="")
    color = serializers.CharField(max_length=9, required=False, allow_blank=True, default="")
    icon = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    include_in_net_worth = serializers.BooleanField(required=False, default=True)
    include_in_budgets = serializers.BooleanField(required=False, default=True)
    # Always a positive magnitude in the account's natural direction: what you
    # hold for an asset, what you owe for a liability. The service derives the
    # debit/credit direction from the account type so callers never reason
    # about signs.
    opening_balance_minor = serializers.IntegerField(required=False, min_value=0, default=0)
    # Backdating matters: users start tracking mid-month and need the opening
    # entry to sit before their earliest imported transaction, or every running
    # balance in the statement is wrong.
    opening_balance_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class FinancialAccountUpdateSerializer(serializers.Serializer):
    """Presentation and reporting settings only.

    `currency` and `account_type` are absent by design — both are baked into
    every ledger line already posted, so changing them would silently invalidate
    history rather than correct it.
    """

    name = serializers.CharField(max_length=120, required=False)
    mask = serializers.CharField(max_length=4, required=False, allow_blank=True)
    color = serializers.CharField(max_length=9, required=False, allow_blank=True)
    icon = serializers.CharField(max_length=40, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    is_hidden = serializers.BooleanField(required=False)
    include_in_net_worth = serializers.BooleanField(required=False)
    include_in_budgets = serializers.BooleanField(required=False)


class FinancialAccountSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField()
    account_type = serializers.CharField()
    currency = serializers.CharField()
    balance_minor = serializers.IntegerField()
    mask = serializers.CharField(required=False, allow_blank=True)
    color = serializers.CharField(required=False, allow_blank=True)
    icon = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    is_hidden = serializers.BooleanField(required=False)
    is_archived = serializers.BooleanField(required=False)
    include_in_net_worth = serializers.BooleanField(required=False)
    include_in_budgets = serializers.BooleanField(required=False)


# ------------------------------------------------------------------ categories
class CategoryCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    kind = serializers.ChoiceField(choices=CategoryKind.choices)
    currency = serializers.CharField(max_length=3, min_length=3)
    parent_id = serializers.UUIDField(required=False, allow_null=True)
    color = serializers.CharField(max_length=9, required=False, allow_blank=True, default="")
    icon = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")


class CategoryUpdateSerializer(serializers.Serializer):
    # kind and currency are intentionally omitted — immutable after creation.
    name = serializers.CharField(max_length=80, required=False)
    color = serializers.CharField(max_length=9, required=False, allow_blank=True)
    icon = serializers.CharField(max_length=40, required=False, allow_blank=True)


class CategorySerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField()
    kind = serializers.CharField()
    path = serializers.CharField()
    depth = serializers.IntegerField()
    parent_id = serializers.UUIDField(allow_null=True)


# ------------------------------------------------------------------ transactions
class TransactionCreateSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["expense", "income"])
    financial_account_id = serializers.UUIDField()
    category_id = serializers.UUIDField()
    amount_minor = serializers.IntegerField(min_value=1)
    occurred_at = serializers.DateTimeField()
    memo = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    payee_id = serializers.UUIDField(required=False, allow_null=True)
    idempotency_key = serializers.CharField(max_length=128, required=False, allow_blank=True)


class TransferCreateSerializer(serializers.Serializer):
    from_account_id = serializers.UUIDField()
    to_account_id = serializers.UUIDField()
    amount_minor = serializers.IntegerField(min_value=1)
    occurred_at = serializers.DateTimeField()
    memo = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=128, required=False, allow_blank=True)


class TransactionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    financial_account_id = serializers.UUIDField()
    amount_minor = serializers.IntegerField()
    currency = serializers.CharField()
    occurred_at = serializers.DateTimeField()
    status = serializers.CharField()
    source = serializers.CharField()
    category_id = serializers.UUIDField(allow_null=True)
    counter_account_id = serializers.UUIDField(allow_null=True)
    transfer_group = serializers.UUIDField(allow_null=True)
    memo = serializers.CharField()


class TransactionUpdateSerializer(serializers.Serializer):
    """`category_id`/`payee_id` distinguish "omitted" (leave alone) from
    `null` (clear) via `required=False` + `allow_null=True` — DRF's
    `partial_data` semantics: a key absent from the payload never appears in
    `validated_data`, so the view can tell the two cases apart."""

    category_id = serializers.UUIDField(required=False, allow_null=True)
    payee_id = serializers.UUIDField(required=False, allow_null=True)
    memo = serializers.CharField(max_length=255, required=False, allow_blank=True)


# ------------------------------------------------------------------ wallets
class WalletCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    icon = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    color = serializers.CharField(max_length=9, required=False, allow_blank=True, default="")
    is_default = serializers.BooleanField(default=False)


class WalletSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField()
    icon = serializers.CharField()
    color = serializers.CharField()
    is_default = serializers.BooleanField()
    balances = serializers.ListField(child=serializers.DictField(), read_only=True)


class WalletAssignAccountSerializer(serializers.Serializer):
    financial_account_id = serializers.UUIDField()
    wallet_id = serializers.UUIDField(required=False, allow_null=True)  # null = remove from wallet


# ------------------------------------------------------------------ payees
class PayeeCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    default_category_id = serializers.UUIDField(required=False, allow_null=True)


class PayeeSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField()
    normalized_name = serializers.CharField()
    default_category_id = serializers.UUIDField(allow_null=True)


# ------------------------------------------------------------------ tags
class TagCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=40)
    color = serializers.CharField(max_length=9, required=False, allow_blank=True, default="")


class TagSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField()
    color = serializers.CharField()


class SetTransactionTagsSerializer(serializers.Serializer):
    tag_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=True)


# ------------------------------------------------------------------ attachments
class AttachmentRequestSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=100)
    byte_size = serializers.IntegerField(min_value=1)


class TransactionBulkSerializer(serializers.Serializer):
    """Batch action over a bounded set of transaction ids. `category_id` is only
    meaningful for the categorize action (null clears the category)."""

    action = serializers.ChoiceField(choices=["categorize", "void"])
    ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=500
    )
    category_id = serializers.UUIDField(required=False, allow_null=True)


class AttachmentConfirmSerializer(serializers.Serializer):
    checksum = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")


class AttachmentSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    transaction_id = serializers.UUIDField(allow_null=True)
    content_type = serializers.CharField()
    byte_size = serializers.IntegerField()
    status = serializers.CharField()
    checksum = serializers.CharField()
    download_url = serializers.SerializerMethodField()

    def get_download_url(self, obj) -> str | None:
        """API path to fetch the stored file — present only once uploaded."""
        from django.urls import NoReverseMatch, reverse

        from ..models import AttachmentStatus

        if obj.status != AttachmentStatus.UPLOADED:
            return None
        try:
            return reverse("finance-attachment-download", args=[obj.id])
        except NoReverseMatch:
            return None


# ------------------------------------------------------------------ recurring
class RecurringCreateSerializer(serializers.Serializer):
    txn_type = serializers.ChoiceField(choices=RecurringType.choices)
    financial_account_id = serializers.UUIDField()
    counter_account_id = serializers.UUIDField(required=False, allow_null=True)
    category_id = serializers.UUIDField(required=False, allow_null=True)
    amount_minor = serializers.IntegerField(min_value=1)
    currency = serializers.CharField(max_length=3, min_length=3)
    frequency = serializers.ChoiceField(choices=Frequency.choices)
    interval = serializers.IntegerField(min_value=1, default=1)
    starts_on = serializers.DateField()
    ends_on = serializers.DateField(required=False, allow_null=True)
    max_occurrences = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    memo = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class RecurringSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    txn_type = serializers.CharField()
    amount_minor = serializers.IntegerField()
    currency = serializers.CharField()
    frequency = serializers.CharField()
    interval = serializers.IntegerField()
    next_run_on = serializers.DateField()
    occurrences_created = serializers.IntegerField()
    is_active = serializers.BooleanField()
    memo = serializers.CharField()
    category_id = serializers.UUIDField(allow_null=True)
    financial_account_id = serializers.UUIDField(allow_null=True)
    payee_id = serializers.UUIDField(allow_null=True)


class RecurringUpdateSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()


# ------------------------------------------------------------------ calculations
class StatementQuerySerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()


class DateRangeQuerySerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()


# ------------------------------------------------------------------ bills & splits
class BillCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    amount_minor = serializers.IntegerField(min_value=1)
    currency = serializers.CharField(max_length=3)
    due_on = serializers.DateField()
    payee_id = serializers.UUIDField(required=False, allow_null=True)
    category_id = serializers.UUIDField(required=False, allow_null=True)
    recurrence_frequency = serializers.CharField(required=False, allow_blank=True, default="")
    recurrence_interval = serializers.IntegerField(required=False, min_value=1, default=1)
    autopay_account_id = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class BillPaySerializer(serializers.Serializer):
    from_account_id = serializers.UUIDField(required=False, allow_null=True)
    amount_minor = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    occurred_at = serializers.DateTimeField(required=False, allow_null=True)
    record_expense = serializers.BooleanField(required=False, default=True)


class SplitPartSerializer(serializers.Serializer):
    category_id = serializers.UUIDField()
    amount_minor = serializers.IntegerField(min_value=1)
    memo = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class TransactionSplitSerializer(serializers.Serializer):
    parts = SplitPartSerializer(many=True)


class CashflowCalendarQuerySerializer(serializers.Serializer):
    """Query params for the cash flow calendar.

    `days` is capped in the selector too; the ceiling here gives a 400 with a
    clear message instead of silently returning a different window than asked
    for.
    """

    start = serializers.DateField(required=False)
    days = serializers.IntegerField(required=False, min_value=1, max_value=365)
    currency = serializers.CharField(max_length=3, min_length=3, required=False)


class ReconcileSerializer(serializers.Serializer):
    """A batch of ticks from one reconciliation session."""

    transaction_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=500
    )
    #: False un-reconciles. Mis-ticking is ordinary, so undoing is a normal
    #: operation rather than an administrative exception.
    reconciled = serializers.BooleanField(default=True)
