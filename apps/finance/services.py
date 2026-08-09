"""Finance service layer — the domain engine over the double-entry ledger.

Every money movement a user makes (spend, earn, move between accounts) is a
single-entry mental model. This layer translates it into the balanced
double-entry truth in `ledger`, atomically, and keeps a user-friendly
`Transaction` aggregate alongside it.

The one rule that makes the whole thing hang together: **a FinancialAccount
and a Category each own a backing ledger.Account.** Spending money is then
uniformly "credit the account's ledger account, debit the category's ledger
account", regardless of whether the account is an asset (cash goes down) or a
liability (debt goes up) — the ledger's normal-balance rules make the signs
work out. Nothing here posts to the ledger except through
`ledger.services.post_journal_entry`, the single choke point.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.common import audit
from apps.ledger import services as ledger_services
from apps.ledger.models import (
    Account as LedgerAccount,
)
from apps.ledger.models import (
    AccountBalance,
    AccountKind,
    Direction,
    JournalEntry,
)
from apps.ledger.services import LineInput

from .models import (
    AccountType,
    Bill,
    Category,
    CategoryKind,
    FinancialAccount,
    RecurringTransaction,
    Transaction,
    TransactionSource,
    TransactionStatus,
)

# Which ledger primitive backs each real-world account type.
_ASSET_TYPES = {
    AccountType.CHECKING,
    AccountType.SAVINGS,
    AccountType.CASH,
    AccountType.INVESTMENT,
    AccountType.OTHER,
}
_LIABILITY_TYPES = {AccountType.CREDIT_CARD, AccountType.LOAN}


class FinanceError(Exception): ...


class CurrencyMismatchError(FinanceError): ...


class CategoryKindError(FinanceError): ...


class InsufficientFundsError(FinanceError):
    """A posting that would take an asset account past its overdraft limit.

    Its own class, not a bare `FinanceError`, because callers need to tell it
    apart: this is the one failure a user can fix by choosing a different
    account or a smaller amount, and the API turns it into a specific message
    naming the account and the shortfall.
    """

    def __init__(self, message: str, *, account_name: str, available_minor: int, shortfall_minor: int):
        super().__init__(message)
        self.account_name = account_name
        self.available_minor = available_minor
        self.shortfall_minor = shortfall_minor


def _assert_sufficient_funds(
    account: FinancialAccount, amount_minor: int, source: str = TransactionSource.MANUAL
) -> None:
    """Refuse a manual withdrawal that would overdraw `account`.

    **Any** manual posting that would take an asset account past its overdraft
    limit is refused, including one against an account already empty or already
    negative. An earlier version only policed accounts that currently held
    money, on the reasoning that a zero balance might just mean "no opening
    balance was ever recorded" — but that let the first overdraft through on
    exactly the accounts most likely to be mistracked, which is backwards. The
    escape hatch for those users is now an explicit workspace setting rather
    than a silent hole in the rule.

    Three exemptions remain, each because refusing would be the worse error:

    * **Liability accounts.** A credit card or loan going further into the red
      is the entire point of a credit card or loan. Blocking it would make the
      product unable to record the debts it exists to help pay off.

    * **Anything not typed in by hand.** An import, a bank sync or a
      reconciliation is recording what *already happened*; the money has moved
      whether or not the ledger likes it. Refusing there would leave the books
      disagreeing with the bank, which is far worse than a negative balance —
      and it would break a backfill of last year's statement against an account
      opened at today's figure.

    * **Recurring materialization.** A standing order that overdraws you is
      real life, and that is exactly when a user needs to see it. Silently
      halting the schedule would hide it.

    …plus the workspace's own `block_overdrafts`, which an owner can turn off.

    The check reads the materialized balance, which the ledger updates in the
    same transaction as the entry that moved it, so it cannot pass on a stale
    figure within a request. Two concurrent postings could still both pass;
    the resulting overdraft would be one transaction deep and immediately
    visible, which is the same guarantee a real bank gives.
    """
    if source != TransactionSource.MANUAL:
        return
    if account.account_type not in _ASSET_TYPES:
        return

    balance = (
        AccountBalance.objects.filter(account_id=account.ledger_account_id)
        .values_list("balance_minor", flat=True)
        .first()
        or 0
    )

    floor = -account.overdraft_limit_minor
    if balance - amount_minor >= floor:
        return

    # Only now is the workspace policy worth a query. Checking it up front
    # would cost a lookup on every expense a household ever records, to answer
    # a question that only matters for the few that would breach.
    if not _overdrafts_are_blocked():
        return

    available = balance + account.overdraft_limit_minor
    raise InsufficientFundsError(
        f"{account.name} doesn't have the funds for this. "
        f"It holds {_fmt_minor(balance)} {account.currency}"
        + (
            f" plus an overdraft of {_fmt_minor(account.overdraft_limit_minor)}"
            if account.overdraft_limit_minor
            else ""
        )
        + f", and this would need {_fmt_minor(amount_minor)}.",
        account_name=account.name,
        available_minor=available,
        shortfall_minor=amount_minor - available,
    )


def _overdrafts_are_blocked() -> bool:
    """The current workspace's overdraft policy.

    **No workspace means no policy**, and the posting goes through. That is not
    a hole: the model field defaults to True, so every real workspace blocks
    until its owner says otherwise, and an interactive request always resolves
    to one. Reaching here without a workspace means the caller is a management
    command, a background job or a test harness — the same category as the
    import exemption above, where the job is to record what happened rather
    than to authorise it.
    """
    from apps.common.tenant_context import get_current_tenant_id
    from apps.tenancy.models import Tenant

    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        return False
    blocked = Tenant.objects.filter(id=tenant_id).values_list("block_overdrafts", flat=True).first()
    return bool(blocked)


def _fmt_minor(amount_minor: int) -> str:
    """Minor units as a plain decimal string, for error messages only.

    Deliberately not locale- or currency-aware: this feeds an exception message
    that names the currency code separately, and pulling formatting machinery
    into the service layer to render an error would be the wrong dependency.
    """
    return f"{amount_minor / 100:,.2f}"


# --------------------------------------------------------------------------- accounts
@transaction.atomic
def create_financial_account(
    *,
    name: str,
    account_type: str,
    currency: str,
    institution=None,
    mask: str = "",
    external_id: str = "",
    metadata: dict | None = None,
    color: str = "",
    icon: str = "",
    notes: str = "",
    include_in_net_worth: bool = True,
    include_in_budgets: bool = True,
    opening_balance_minor: int = 0,
    opening_balance_at: datetime | None = None,
) -> FinancialAccount:
    """Provisions the backing ledger Account (+ its materialized balance) and
    the FinancialAccount in one transaction. They're 1:1 and created together
    so a FinancialAccount can never exist without somewhere to post to.

    When `opening_balance_minor` is non-zero a real journal entry is posted (see
    `set_opening_balance`) — never a stored column. A balance that isn't the sum
    of ledger lines is a number the product cannot defend, and it silently
    breaks reconciliation forever after.
    """
    from apps.billing.entitlements import ensure_can_add_account, lock_tenant_for_limit_check
    from apps.common.tenant_context import require_current_tenant_id

    # Lock before counting — see the seat-limit note in tenancy.add_member.
    lock_tenant_for_limit_check(require_current_tenant_id())
    ensure_can_add_account(
        tenant_id=require_current_tenant_id(),
        current_count=FinancialAccount.objects.filter(is_active=True).count(),
    )
    kind = AccountKind.ASSET if account_type in _ASSET_TYPES else AccountKind.LIABILITY
    ledger_account = ledger_services.create_account(name=name, kind=kind, currency=currency)
    account = FinancialAccount.objects.create(
        name=name,
        account_type=account_type,
        currency=currency,
        institution=institution,
        mask=mask,
        external_id=external_id,
        metadata=metadata or {},
        color=color,
        icon=icon,
        notes=notes,
        include_in_net_worth=include_in_net_worth,
        include_in_budgets=include_in_budgets,
        ledger_account=ledger_account,
    )
    if opening_balance_minor:
        set_opening_balance(
            financial_account=account,
            amount_minor=opening_balance_minor,
            occurred_at=opening_balance_at,
        )
    return account


# --------------------------------------------------------------- opening balances
OPENING_BALANCE_ACCOUNT_NAME = "Opening Balance Equity"


def opening_balance_equity_account(currency: str) -> LedgerAccount:
    """The system EQUITY account that opening balances are posted against.

    Standard bookkeeping: when you start tracking an account that already holds
    money, the money has to come from *somewhere* for the entry to balance. It
    didn't come from income — you didn't earn it this period — so it's booked to
    equity, which is precisely what equity means: value the owner already had.

    One per currency, because `post_journal_entry` enforces a single currency
    per entry. The currency is carried in the *name* as well as the column
    because ledger Account uniqueness is (tenant, name, kind) and does not
    include currency — so two same-named equity accounts would collide. Naming
    them explicitly is also plainer to read in a chart of accounts.

    Created lazily, so a workspace that never sets an opening balance never
    carries the account.
    """
    name = f"{OPENING_BALANCE_ACCOUNT_NAME} ({currency})"
    existing = LedgerAccount.objects.filter(name=name, kind=AccountKind.EQUITY).first()
    if existing is not None:
        return existing
    return ledger_services.create_account(
        name=name, kind=AccountKind.EQUITY, currency=currency, is_system=True
    )


@transaction.atomic
def set_opening_balance(
    *,
    financial_account: FinancialAccount,
    amount_minor: int,
    occurred_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> JournalEntry | None:
    """Records what an account already held when the user started tracking it.

    This is the entry point users hit on day one, and getting it wrong is
    unrecoverable: every balance, every net-worth figure and every reconciliation
    downstream inherits the error.

    Direction follows the account's normal balance:
      * asset      — DEBIT the account, CREDIT opening equity. You have it.
      * liability  — CREDIT the account, DEBIT opening equity. You owe it.

    `amount_minor` is always given as a positive magnitude in the account's own
    natural direction: 3_250_00 in a checking account means $3,250 held;
    1_200_00 on a credit card means $1,200 owed. Making the caller reason about
    signs is how sign-flip bugs get into production.

    Idempotent per account: the key is derived from the account id, so a
    retried request can never post the opening balance twice.
    """
    if amount_minor == 0:
        return None
    if amount_minor < 0:
        raise FinanceError(
            "Opening balance must be a positive magnitude; direction is derived from the account type."
        )

    ledger_account = financial_account.ledger_account
    equity = opening_balance_equity_account(financial_account.currency)
    when = occurred_at or timezone.now()

    if ledger_account.kind == AccountKind.ASSET:
        lines = [
            LineInput(
                account_id=str(ledger_account.id), direction=Direction.DEBIT, amount_minor=amount_minor
            ),
            LineInput(account_id=str(equity.id), direction=Direction.CREDIT, amount_minor=amount_minor),
        ]
    else:
        lines = [
            LineInput(account_id=str(equity.id), direction=Direction.DEBIT, amount_minor=amount_minor),
            LineInput(
                account_id=str(ledger_account.id), direction=Direction.CREDIT, amount_minor=amount_minor
            ),
        ]

    return ledger_services.post_journal_entry(
        occurred_at=when,
        lines=lines,
        idempotency_key=idempotency_key or f"opening:{financial_account.id}",
        memo=f"Opening balance — {financial_account.name}",
    )


# --------------------------------------------------------------- account lifecycle
@transaction.atomic
def archive_financial_account(*, financial_account: FinancialAccount) -> FinancialAccount:
    """Closes an account without destroying its history.

    Archiving is not deletion and must never become deletion: the ledger lines
    behind a closed account are immutable and still belong in historical
    reports. What changes is visibility — the account leaves pickers and default
    lists — and inclusion in forward-looking figures.

    A non-zero balance is allowed deliberately. Real accounts are sometimes
    closed with money still recorded against them, and refusing to archive would
    leave the user stuck; the balance stays visible in history either way.
    """
    if financial_account.archived_at is None:
        financial_account.archived_at = timezone.now()
    financial_account.is_active = False
    financial_account.save(update_fields=["archived_at", "is_active", "updated_at"])
    return financial_account


@transaction.atomic
def unarchive_financial_account(*, financial_account: FinancialAccount) -> FinancialAccount:
    """Reopens an archived account. Nothing about its history changes."""
    financial_account.archived_at = None
    financial_account.is_active = True
    financial_account.save(update_fields=["archived_at", "is_active", "updated_at"])
    return financial_account


@transaction.atomic
def update_financial_account(*, financial_account: FinancialAccount, **fields) -> FinancialAccount:
    """Updates presentation and inclusion settings.

    Deliberately narrow: `currency` and `account_type` are immutable because
    both are baked into every ledger line already posted, and `name` changes are
    allowed because they carry no accounting meaning.
    """
    allowed = {
        "name",
        "color",
        "icon",
        "notes",
        "mask",
        "is_hidden",
        "include_in_net_worth",
        "include_in_budgets",
        "wallet",
    }
    changed = []
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        setattr(financial_account, key, value)
        changed.append(key)
    if changed:
        financial_account.save(update_fields=[*changed, "updated_at"])
    return financial_account


@transaction.atomic
def delete_financial_account(*, financial_account: FinancialAccount) -> None:
    """Permanently removes an account with nothing to lose — unlike archive,
    this drops it from every list, including the archived view, so it's only
    allowed when there's no history, schedule, or bill left dangling."""
    in_use = Transaction.objects.filter(
        Q(financial_account=financial_account) | Q(counter_account=financial_account)
    ).exists()
    if in_use:
        raise FinanceError("This account has transactions. Deactivate it instead, or void its transactions first.")

    in_recurring = RecurringTransaction.objects.filter(
        Q(financial_account=financial_account) | Q(counter_account=financial_account)
    ).exists()
    if in_recurring:
        raise FinanceError("This account is used by a recurring schedule. Remove or repoint it first.")

    if Bill.objects.filter(autopay_account=financial_account).exists():
        raise FinanceError("This account is set as autopay for a bill. Change the bill's autopay account first.")

    financial_account.delete()  # soft delete


# --------------------------------------------------------------------------- categories
_CATEGORY_LEDGER_KIND = {
    CategoryKind.INCOME: AccountKind.INCOME,
    CategoryKind.EXPENSE: AccountKind.EXPENSE,
}


@transaction.atomic
def create_category(
    *,
    name: str,
    kind: str,
    currency: str,
    parent: Category | None = None,
    slug: str = "",
    color: str = "",
    icon: str = "",
) -> Category:
    """Income/expense categories get a backing ledger Account so postings
    balance. Transfer 'categories' don't (transfers never touch a category
    ledger account). Materialized `path`/`depth` give O(1) subtree filtering.
    `slug` is a stable machine reference (for automation rules); it defaults to
    a slugified name and is unique per tenant among live categories.
    """
    ledger_account = None
    if kind in _CATEGORY_LEDGER_KIND:
        ledger_account = ledger_services.create_account(
            name=f"{kind}:{name}", kind=_CATEGORY_LEDGER_KIND[kind], currency=currency
        )

    depth = 0 if parent is None else parent.depth + 1
    base_slug = (slug or name).strip().lower().replace(" ", "_")
    path = base_slug if parent is None else f"{parent.path}.{base_slug}"

    return Category.objects.create(
        name=name,
        slug=base_slug,
        kind=kind,
        parent=parent,
        depth=depth,
        path=path,
        color=color,
        icon=icon,
        ledger_account=ledger_account,
    )


_SENTINEL = object()


@transaction.atomic
def update_category(
    *,
    category: Category,
    name: str | None = None,
    color: str | None = None,
    icon: str | None = None,
    parent=_SENTINEL,
) -> Category:
    """Edit presentation-level fields, and optionally reparent. `kind` is
    immutable — changing it would invalidate every posting already made
    against the category's ledger account, so we don't allow it (delete +
    recreate is the honest path). `parent` uses a sentinel default (not
    `None`) so `parent=None` means "move to top-level" while omitting the
    argument means "leave the parent alone."
    """
    if category.is_system:
        raise FinanceError("System categories can't be edited.")
    fields = []
    if name is not None and name != category.name:
        category.name = name
        fields.append("name")
    if color is not None:
        category.color = color
        fields.append("color")
    if icon is not None:
        category.icon = icon
        fields.append("icon")

    if parent is not _SENTINEL and parent != category.parent:
        if parent is not None:
            if parent.id == category.id:
                raise FinanceError("A category can't be its own parent.")
            if parent.kind != category.kind:
                raise FinanceError("A category can only move under a parent of the same kind.")
            if parent.path.startswith(f"{category.path}."):
                raise FinanceError("Can't move a category under one of its own descendants.")

        old_path = category.path
        old_depth = category.depth
        new_depth = 0 if parent is None else parent.depth + 1
        new_path = category.slug if parent is None else f"{parent.path}.{category.slug}"
        depth_delta = new_depth - old_depth

        category.parent = parent
        category.depth = new_depth
        category.path = new_path
        fields.extend(["parent", "depth", "path"])

        # Materialized path: every live descendant's stored path/depth carries
        # the old prefix and must shift by the same delta as the category itself.
        for descendant in Category.objects.filter(path__startswith=f"{old_path}."):
            descendant.path = new_path + descendant.path[len(old_path) :]
            descendant.depth = descendant.depth + depth_delta
            descendant.save(update_fields=["path", "depth", "updated_at"])

    if fields:
        category.save(update_fields=[*fields, "updated_at"])
    return category


@transaction.atomic
def archive_category(*, category: Category) -> None:
    """Soft-delete a category. Guards:
      - system categories are never removable;
      - a category with live child categories can't be removed (orphaning);
      - a category still referenced by live transactions can't be removed —
        the caller must recategorize first, so historical postings never point
        at a dangling category.
    Soft delete preserves the ledger account and audit history."""
    if category.is_system:
        raise FinanceError("System categories can't be deleted.")

    has_children = Category.objects.filter(parent=category).exists()
    if has_children:
        raise FinanceError("Move or remove the sub-categories first.")

    in_use = Transaction.objects.filter(category=category).exists()
    if in_use:
        raise FinanceError(
            "This category is used by existing transactions. Recategorize them first, then delete it."
        )

    category.delete()  # soft delete


# --------------------------------------------------------------------------- postings
@dataclass(frozen=True, slots=True)
class _Posting:
    entry_lines: list[LineInput]
    signed_amount_minor: int


def _require_same_currency(*currencies: str) -> str:
    distinct = set(currencies)
    if len(distinct) != 1:
        raise CurrencyMismatchError(
            "All parts of this operation must share one currency; cross-currency needs an FX entry."
        )
    return distinct.pop()


def _idem(prefix: str, key: str | None) -> str:
    return key or f"{prefix}:{uuid.uuid4()}"


def _existing_transactions_for(entry) -> list[Transaction]:
    """Domain transactions already posted against a journal entry.

    `post_journal_entry` is idempotent on its own key and returns the
    *existing* entry on replay rather than raising — but a `Transaction` row
    is a separate, plain `ForeignKey` to that entry, not a `OneToOneField`, so
    nothing at the database level stops a naive caller from creating a second
    one every time it replays. This is the guard: a non-empty result means the
    entry already has its transaction(s), and the caller must return those
    rather than create new ones.

    Only non-empty on a genuine replay — a fresh entry can't yet have a
    transaction pointing at it, so this is nearly free on the common path.
    """
    return list(Transaction.objects.filter(journal_entry=entry))


def _category_ledger_for(category: Category, currency: str):
    """Resolve the ledger account a category posts to in a given currency.

    A category is currency-agnostic to the user ("Groceries"), but the ledger
    requires both legs of an entry to share a currency. The category's primary
    ledger account is created in the base currency; when a transaction lands in
    a different account currency we find-or-create a per-currency sibling so the
    entry balances. This is what lets you spend from a USD *and* a EUR account
    against the same category without a cross-currency error.
    """
    base = category.ledger_account
    if base is None:
        raise CategoryKindError("This category has no ledger account to post to.")
    if base.currency == currency:
        return base
    sibling_name = f"{base.name}@{currency}"
    existing = LedgerAccount.objects.filter(name=sibling_name, currency=currency, kind=base.kind).first()
    if existing is not None:
        return existing
    return ledger_services.create_account(name=sibling_name, kind=base.kind, currency=currency)


@transaction.atomic
def record_expense(
    *,
    financial_account: FinancialAccount,
    category: Category,
    amount_minor: int,
    occurred_at: datetime,
    memo: str = "",
    payee=None,
    source: str = TransactionSource.MANUAL,
    idempotency_key: str | None = None,
    tenant_metadata: dict | None = None,
) -> Transaction:
    # The trial's teeth: a lapsed workspace pauses *new* postings until a plan
    # is chosen. Reads and export stay open — see ensure_workspace_active.
    from apps.billing.entitlements import ensure_workspace_active
    from apps.common.tenant_context import get_current_tenant_id

    ensure_workspace_active(tenant_id=get_current_tenant_id())
    if amount_minor <= 0:
        raise FinanceError("Expense amount must be positive; sign is applied by the engine.")
    if category.kind != CategoryKind.EXPENSE:
        raise CategoryKindError("record_expense requires an expense category.")
    _assert_sufficient_funds(financial_account, amount_minor, source)
    currency = financial_account.currency
    category_ledger = _category_ledger_for(category, currency)

    entry = ledger_services.post_journal_entry(
        occurred_at=occurred_at,
        idempotency_key=_idem("expense", idempotency_key),
        memo=memo,
        lines=[
            # money out of the account (asset down / liability up) = CREDIT it
            LineInput(str(financial_account.ledger_account_id), Direction.CREDIT, amount_minor),
            LineInput(str(category_ledger.id), Direction.DEBIT, amount_minor),
        ],
    )
    existing = _existing_transactions_for(entry)
    if existing:
        return existing[0]
    return Transaction.objects.create(
        financial_account=financial_account,
        journal_entry=entry,
        amount_minor=-amount_minor,  # signed: money out
        currency=currency,
        occurred_at=occurred_at,
        posted_at=timezone.now(),
        status=TransactionStatus.POSTED,
        source=source,
        category=category,
        payee=payee,
        memo=memo,
        metadata=tenant_metadata or {},
    )


@transaction.atomic
def record_income(
    *,
    financial_account: FinancialAccount,
    category: Category,
    amount_minor: int,
    occurred_at: datetime,
    memo: str = "",
    payee=None,
    source: str = TransactionSource.MANUAL,
    idempotency_key: str | None = None,
    tenant_metadata: dict | None = None,
) -> Transaction:
    # The trial's teeth: a lapsed workspace pauses *new* postings until a plan
    # is chosen. Reads and export stay open — see ensure_workspace_active.
    from apps.billing.entitlements import ensure_workspace_active
    from apps.common.tenant_context import get_current_tenant_id

    ensure_workspace_active(tenant_id=get_current_tenant_id())
    if amount_minor <= 0:
        raise FinanceError("Income amount must be positive.")
    if category.kind != CategoryKind.INCOME:
        raise CategoryKindError("record_income requires an income category.")
    currency = financial_account.currency
    category_ledger = _category_ledger_for(category, currency)

    entry = ledger_services.post_journal_entry(
        occurred_at=occurred_at,
        idempotency_key=_idem("income", idempotency_key),
        memo=memo,
        lines=[
            # money into the account = DEBIT it; CREDIT the income source
            LineInput(str(financial_account.ledger_account_id), Direction.DEBIT, amount_minor),
            LineInput(str(category_ledger.id), Direction.CREDIT, amount_minor),
        ],
    )
    existing = _existing_transactions_for(entry)
    if existing:
        return existing[0]
    return Transaction.objects.create(
        financial_account=financial_account,
        journal_entry=entry,
        amount_minor=amount_minor,  # signed: money in
        currency=currency,
        occurred_at=occurred_at,
        posted_at=timezone.now(),
        status=TransactionStatus.POSTED,
        source=source,
        category=category,
        payee=payee,
        memo=memo,
        metadata=tenant_metadata or {},
    )


@transaction.atomic
def record_transfer(
    *,
    from_account: FinancialAccount,
    to_account: FinancialAccount,
    amount_minor: int,
    occurred_at: datetime,
    memo: str = "",
    source: str = TransactionSource.MANUAL,
    idempotency_key: str | None = None,
) -> tuple[Transaction, Transaction]:
    """A transfer is NOT income or expense — net worth is unchanged. It posts
    ONE balanced journal entry (credit source, debit destination, no
    category account) and surfaces as TWO linked domain transactions so each
    account's statement shows its own side. Reports exclude anything with a
    `transfer_group`, so a transfer never inflates spending or income.
    """
    if amount_minor <= 0:
        raise FinanceError("Transfer amount must be positive.")
    if from_account.id == to_account.id:
        raise FinanceError("Cannot transfer to the same account.")
    _assert_sufficient_funds(from_account, amount_minor, source)
    currency = _require_same_currency(from_account.currency, to_account.currency)

    entry = ledger_services.post_journal_entry(
        occurred_at=occurred_at,
        idempotency_key=_idem("transfer", idempotency_key),
        memo=memo or f"Transfer {from_account.name} -> {to_account.name}",
        lines=[
            LineInput(str(from_account.ledger_account_id), Direction.CREDIT, amount_minor),  # source down
            LineInput(str(to_account.ledger_account_id), Direction.DEBIT, amount_minor),  # dest up
        ],
    )
    existing = _existing_transactions_for(entry)
    if existing:
        out_txn = next(t for t in existing if t.financial_account_id == from_account.id)
        in_txn = next(t for t in existing if t.financial_account_id == to_account.id)
        return out_txn, in_txn

    group = uuid.uuid4()
    common = {
        "journal_entry": entry,
        "currency": currency,
        "occurred_at": occurred_at,
        "posted_at": timezone.now(),
        "status": TransactionStatus.POSTED,
        "source": source,
        "memo": memo,
        "transfer_group": group,
    }
    out_txn = Transaction.objects.create(
        financial_account=from_account, counter_account=to_account, amount_minor=-amount_minor, **common
    )
    in_txn = Transaction.objects.create(
        financial_account=to_account, counter_account=from_account, amount_minor=amount_minor, **common
    )
    return out_txn, in_txn


@transaction.atomic
def void_transaction(*, txn: Transaction, idempotency_key: str | None = None, memo: str = "") -> None:
    """Void by posting the reversing journal entry (never by mutating history)
    and marking the domain transaction(s) VOID. Handles transfers by voiding
    both halves off the single shared entry."""
    if txn.status == TransactionStatus.VOID:
        return
    if txn.journal_entry_id is None:
        raise FinanceError("Cannot void a transaction that was never posted to the ledger.")

    ledger_services.reverse_journal_entry(
        entry=txn.journal_entry,
        idempotency_key=_idem(f"void:{txn.id}", idempotency_key),
        memo=memo or f"Void of transaction {txn.id}",
    )

    siblings = Transaction.objects.filter(journal_entry_id=txn.journal_entry_id)
    for sibling in siblings:
        sibling.status = TransactionStatus.VOID
        sibling.save(update_fields=["status", "updated_at"])
        # Voiding is the destructive money operation a member can perform, and
        # in a shared household it is the one most worth being able to attribute.
        audit.record(
            action="transaction.voided",
            target=sibling,
            changes={"status": [TransactionStatus.POSTED, TransactionStatus.VOID]},
        )


@transaction.atomic
def reclassify_as_transfer(
    *,
    txn: Transaction,
    counter_account: FinancialAccount,
    idempotency_key: str | None = None,
) -> tuple[Transaction, Transaction]:
    """Void a misposted income/expense row and repost it as a real transfer.

    A statement import has no idea two of a household's own accounts are
    involved in one movement — it just sees a credit here and a debit there.
    This is the fix once a human recognizes that: direction is derived from
    the sign of the original row, never asked for, since asking invites
    getting it backwards. A positive (income) row means money arrived FROM
    `counter_account`; a negative (expense) row means money left TO it.
    `occurred_at` and `memo` are preserved so the reclassified row keeps its
    place in history.

    Posted with `source=IMPORTED`, not `MANUAL` — this never moves money that
    wasn't already moving. The original row is proof the amount already left
    one account and reached the other; reclassifying only corrects which
    account gets credited with which side. Gating that on the destination
    leg's current balance would refuse a true correction just because that
    account's own history isn't fully tracked yet, which is exactly the
    "an import disagrees with what the bank actually did" case
    `_assert_sufficient_funds` already carves out.
    """
    if txn.status == TransactionStatus.VOID:
        raise FinanceError("Cannot reclassify a voided transaction.")
    if txn.transfer_group is not None:
        raise FinanceError("This is already a transfer.")
    if txn.split_group is not None:
        raise FinanceError("This transaction is part of a split; void the split and re-enter it first.")
    if txn.reconciled_at is not None:
        raise FinanceError("Un-reconcile this transaction before reclassifying it.")

    amount = abs(txn.amount_minor)
    if txn.amount_minor > 0:  # income leg: money arrived FROM counter_account
        from_account, to_account = counter_account, txn.financial_account
    else:  # expense leg: money left TO counter_account
        from_account, to_account = txn.financial_account, counter_account

    void_transaction(txn=txn)
    return record_transfer(
        from_account=from_account,
        to_account=to_account,
        amount_minor=amount,
        occurred_at=txn.occurred_at,
        memo=txn.memo,
        source=TransactionSource.IMPORTED,
        idempotency_key=idempotency_key,
    )


@transaction.atomic
def update_transaction(
    *,
    txn: Transaction,
    category=_SENTINEL,
    payee=_SENTINEL,
    memo: str | None = None,
) -> Transaction:
    """Edits the parts of a transaction that do NOT affect the ledger:
    category, payee, memo. Amount, account, and direction are immutable —
    changing what actually happened financially requires `void_transaction`
    + a fresh posting, never a mutation, so the ledger stays the single
    source of truth for "what really moved." `category`/`payee` use a
    sentinel default (not `None`) so `category=None` means "clear it" while
    omitting the argument means "leave it alone."
    """
    if txn.status == TransactionStatus.VOID:
        raise FinanceError("Cannot edit a voided transaction.")

    fields: list[str] = []

    if category is not _SENTINEL:
        if category is not None:
            if txn.transfer_group is not None:
                raise CategoryKindError("Transfers cannot have a category.")
            expected_kind = CategoryKind.EXPENSE if txn.amount_minor < 0 else CategoryKind.INCOME
            if category.kind != expected_kind:
                raise CategoryKindError(
                    f"This transaction needs a {expected_kind} category, got {category.kind}."
                )
        txn.category = category
        fields.append("category")

    if payee is not _SENTINEL:
        txn.payee = payee
        fields.append("payee")

    if memo is not None:
        txn.memo = memo
        fields.append("memo")

    if fields:
        txn.save(update_fields=[*fields, "updated_at"])
    return txn


def flag_transaction_for_review(*, txn: Transaction, reason: str = "") -> Transaction:
    """Mark a transaction as needing human review (used by automation's
    flag_review action and manual review requests). A real, queryable state —
    surfaced by the review-queue index — not a no-op."""
    if not txn.needs_review or txn.review_reason != reason:
        txn.needs_review = True
        txn.review_reason = reason[:255]
        txn.save(update_fields=["needs_review", "review_reason", "updated_at"])
    return txn


@transaction.atomic
def bulk_categorize_transactions(*, txns, category) -> dict:
    """Apply one category to many transactions in a single unit of work. Each
    row goes through `update_transaction`, so the same kind/transfer rules and
    audit trail apply; per-row failures (e.g. an expense category on an income
    row) are collected and reported rather than aborting the whole batch. A
    failing row raises before any write, so the outer transaction stays clean."""
    updated = 0
    failed: list[dict] = []
    for txn in txns:
        try:
            update_transaction(txn=txn, category=category)
            updated += 1
        except FinanceError as exc:
            failed.append({"id": str(txn.id), "error": str(exc)})
    return {"updated": updated, "failed": failed}


@transaction.atomic
def bulk_void_transactions(*, txns) -> dict:
    """Void many transactions at once. Already-void rows are no-ops (idempotent);
    rows that were never posted are reported as failures."""
    updated = 0
    failed: list[dict] = []
    for txn in txns:
        try:
            void_transaction(txn=txn)
            updated += 1
        except FinanceError as exc:
            failed.append({"id": str(txn.id), "error": str(exc)})
    return {"updated": updated, "failed": failed}


@dataclass(frozen=True, slots=True)
class SplitPart:
    category: Category
    amount_minor: int
    memo: str = ""


@transaction.atomic
def split_transaction(*, txn: Transaction, parts: list[SplitPart]) -> list[Transaction]:
    """Divide a single expense across several categories.

    Personal-finance reality: one $200 store run is $150 groceries + $50
    household. The ledger already supports N-line entries, so a split is: void
    the original single-category entry, then post ONE new balanced entry
    (credit the account once, debit each category account) that surfaces as N
    linked domain transactions sharing a `split_group`. Net cash movement is
    unchanged; only the categorization becomes finer.

    Only expenses are splittable today (the common case) and the parts must sum
    to the original magnitude, so the split is category-only and never changes
    what left the account.
    """
    if txn.status == TransactionStatus.VOID:
        raise FinanceError("Cannot split a voided transaction.")
    if txn.transfer_group is not None:
        raise FinanceError("Transfers cannot be split.")
    if txn.split_group is not None:
        raise FinanceError("Transaction is already a split; void and re-create to change it.")
    if txn.amount_minor >= 0:
        raise FinanceError("Only expenses can be split.")
    if len(parts) < 2:
        raise FinanceError("A split needs at least two parts.")
    total = sum(p.amount_minor for p in parts)
    if total != abs(txn.amount_minor):
        raise FinanceError("Split parts must sum to the original amount.")
    for p in parts:
        if p.amount_minor <= 0:
            raise FinanceError("Each split part must be positive.")
        if p.category.kind != CategoryKind.EXPENSE:
            raise CategoryKindError("Split parts must use expense categories.")

    account = txn.financial_account
    occurred_at = txn.occurred_at

    # 1. reverse the original posting (keeps ledger history intact)
    ledger_services.reverse_journal_entry(
        entry=txn.journal_entry,
        idempotency_key=_idem(f"split-void:{txn.id}", None),
        memo=f"Split of transaction {txn.id}",
    )
    txn.status = TransactionStatus.VOID
    txn.save(update_fields=["status", "updated_at"])

    # 2. post one new balanced entry: credit account once, debit each category
    lines = [LineInput(str(account.ledger_account_id), Direction.CREDIT, total)]
    for p in parts:
        part_ledger = _category_ledger_for(p.category, txn.currency)
        lines.append(LineInput(str(part_ledger.id), Direction.DEBIT, p.amount_minor))
    entry = ledger_services.post_journal_entry(
        occurred_at=occurred_at,
        idempotency_key=_idem(f"split:{txn.id}", None),
        memo=txn.memo,
        lines=lines,
    )

    # 3. surface as N linked domain transactions
    group = uuid.uuid4()
    created: list[Transaction] = []
    for p in parts:
        created.append(
            Transaction.objects.create(
                financial_account=account,
                journal_entry=entry,
                amount_minor=-p.amount_minor,
                currency=txn.currency,
                occurred_at=occurred_at,
                posted_at=timezone.now(),
                status=TransactionStatus.POSTED,
                source=txn.source,
                category=p.category,
                payee=txn.payee,
                memo=p.memo or txn.memo,
                split_group=group,
            )
        )
    return created


def recompute_account_balance(*, financial_account: FinancialAccount) -> int:
    """Reconciliation helper: recompute the materialized balance from the
    immutable ledger lines and write it back. Returns the recomputed value."""
    from apps.ledger.selectors import recompute_balance_minor

    recomputed = recompute_balance_minor(financial_account.ledger_account)
    AccountBalance.objects.filter(account_id=financial_account.ledger_account_id).update(
        balance_minor=recomputed
    )
    return recomputed


__all__ = [
    "FinanceError",
    "CurrencyMismatchError",
    "CategoryKindError",
    "create_financial_account",
    "create_category",
    "record_expense",
    "record_income",
    "record_transfer",
    "void_transaction",
    "update_transaction",
    "flag_transaction_for_review",
    "recompute_account_balance",
]
