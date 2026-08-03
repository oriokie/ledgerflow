"""Quick Add — the fewest taps between "I just spent money" and a posted
transaction.

A normal transaction form asks for an account, a category, a payee and an
amount up front. On a phone, in a queue, that's the difference between logging
a purchase and not bothering. Quick Add asks for **only an amount and who it
was to**, and derives everything else:

  * **account** — the one most recently transacted on, because that's almost
    always the card or account actually in someone's hand;
  * **category** — the automation engine's own learned suggestion for this
    merchant, the same `suggest_category` the review queue uses, so Quick Add
    and the automation engine can never disagree about what a merchant
    "usually is";
  * **payee** — looked up or created from the free-text merchant name, exactly
    as any other transaction entry does.

Every inferred field is returned **alongside a flag saying it was inferred**,
never silently. A user who typed one word and an amount deserves to see what
was guessed on their behalf before it settles into their history — the same
transparency the automation review queue gives a machine-detected suggestion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from apps.finance.models import Category, CategoryKind, FinancialAccount, Transaction
from apps.finance.payees import get_or_create_payee
from apps.intelligence import automation_services
from apps.intelligence.detect import merchant_key


class QuickAddError(Exception): ...


def _lazy_category(*, name: str, kind: str, currency: str) -> Category:
    """Get-or-create a system category by name, mirroring the CSV importer's
    `_lazy_category` helper exactly.

    `currency` is not a field on `Category` — it only shapes the *backing
    ledger account* `create_category` provisions for a new row, so an existing
    category is looked up by name and kind alone, and the currency is used
    only on the creation path.
    """
    existing = Category.objects.filter(kind=kind, name=name).first()
    if existing is not None:
        return existing
    from apps.finance import services as finance_services

    return finance_services.create_category(name=name, kind=kind, currency=currency)


def _fallback_category(currency: str) -> Category:
    """The same lazily-created "Uncategorized" category the CSV importer uses.

    Reusing it rather than inventing a second placeholder means the automation
    engine's `is_placeholder_category` check — which already knows this name —
    covers a Quick Add transaction exactly as it covers an imported one.
    """
    return _lazy_category(name="Uncategorized", kind=CategoryKind.EXPENSE, currency=currency)


def _most_recently_used_account(*, currency: str | None = None) -> FinancialAccount | None:
    """The account most likely still in the user's hand.

    Derived from transaction history rather than a stored "default account" —
    a preference that drifts out of sync with actual behaviour is worse than
    no preference at all, and this can never go stale because it's read fresh
    every time.
    """
    qs = Transaction.objects.select_related("financial_account").order_by("-occurred_at")
    if currency:
        qs = qs.filter(currency=currency)
    latest = qs.first()
    if latest:
        return latest.financial_account
    accounts = FinancialAccount.objects.filter(archived_at__isnull=True)
    if currency:
        accounts = accounts.filter(currency=currency)
    return accounts.first()


@dataclass(frozen=True, slots=True)
class QuickAddResult:
    transaction: Transaction
    #: True when the account wasn't specified and was inferred from recent
    #: activity — the UI should let the user confirm or switch it.
    account_was_inferred: bool
    #: True when the category came from the automation engine's learned guess
    #: rather than being named explicitly.
    category_was_inferred: bool
    #: The confidence behind an inferred category, so a shaky guess can be
    #: visually hedged rather than presented with the same weight as a sure one.
    category_confidence: float | None


def quick_add(
    *,
    amount_minor: int,
    merchant: str,
    is_income: bool = False,
    financial_account: FinancialAccount | None = None,
    category: Category | None = None,
    occurred_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> QuickAddResult:
    """Post a transaction from the minimum viable input.

    Still goes through the ordinary `record_expense` / `record_income` path —
    Quick Add is a faster way to fill in a normal transaction, not a different
    kind of posting. Nothing about the ledger's accounting changes for a
    transaction entered this way.

    `idempotency_key` matters more here than on the desk-bound transaction
    form: Quick Add is the entry point the offline queue replays from, and a
    replay after a lost response — sent, but the confirmation never arrived —
    must land on the *same* journal entry rather than post twice. The client
    generates one key per queued entry and resends it unchanged on every
    retry; `post_journal_entry` does the actual dedupe.
    """
    from apps.finance import services as finance_services

    if amount_minor <= 0:
        raise QuickAddError("Amount must be positive.")
    if not merchant.strip():
        raise QuickAddError("Enter who this was to or from.")

    occurred_at = occurred_at or timezone.now()
    account_was_inferred = financial_account is None
    if financial_account is None:
        financial_account = _most_recently_used_account()
        if financial_account is None:
            raise QuickAddError("Add an account before using Quick Add.")

    payee, _ = get_or_create_payee(name=merchant.strip())

    category_was_inferred = False
    category_confidence = None
    if category is None and not is_income:
        # The same learned lookup the automation review queue suggests
        # from — Quick Add and the automation engine can never disagree
        # about what a merchant "usually is", because they read one store.
        stats = automation_services.merchant_stats()
        key = merchant_key(merchant)
        merchant_counts = stats.get(key)
        if merchant_counts:
            total = sum(merchant_counts.values())
            best_id, count = max(merchant_counts.items(), key=lambda kv: kv[1])
            if total >= 2 and count / total >= 0.6:
                category = Category.objects.filter(id=best_id).first()
                if category:
                    category_was_inferred = True
                    category_confidence = round(count / total, 2)
        if category is None:
            category = _fallback_category(financial_account.currency)

    if is_income:
        income_category = category or _income_fallback_category(financial_account.currency)
        txn = finance_services.record_income(
            financial_account=financial_account,
            category=income_category,
            amount_minor=amount_minor,
            occurred_at=occurred_at,
            payee=payee,
            idempotency_key=idempotency_key,
        )
    else:
        txn = finance_services.record_expense(
            financial_account=financial_account,
            category=category,
            amount_minor=amount_minor,
            occurred_at=occurred_at,
            payee=payee,
            idempotency_key=idempotency_key,
        )
        # A category the user typed explicitly (not inferred, not the
        # placeholder) is a real signal — feed it to the learning store, same
        # as any other categorised transaction.
        if not category_was_inferred and not automation_services.is_placeholder_category(category):
            automation_services.learn_from_transaction(txn)

    return QuickAddResult(
        transaction=txn,
        account_was_inferred=account_was_inferred,
        category_was_inferred=category_was_inferred,
        category_confidence=category_confidence,
    )


def _income_fallback_category(currency: str) -> Category:
    return _lazy_category(name="Uncategorized Income", kind=CategoryKind.INCOME, currency=currency)


def recent_merchants(*, limit: int = 8) -> list[str]:
    """Recently-used payee names, for a Quick Add autocomplete.

    Ordered by recency of use, not alphabetically — the one someone bought
    coffee from an hour ago should be the top suggestion, not wherever it
    falls alphabetically.
    """
    seen: list[str] = []
    for name in (
        Transaction.objects.exclude(payee__isnull=True)
        .select_related("payee")
        .order_by("-occurred_at")
        .values_list("payee__name", flat=True)
    ):
        if name and name not in seen:
            seen.append(name)
        if len(seen) >= limit:
            break
    return seen
