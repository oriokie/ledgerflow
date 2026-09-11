"""Post a pasted M-Pesa confirmation SMS to the default M-Pesa account.

The SMS is a real movement that already happened, so it posts as an imported
row (the overdraft guard does not apply — refusing would leave the books
disagreeing with the phone). Identity is the receipt plus the signed amount,
which is what the statement importer later uses to skip the same event rather
than record it twice.

Category is optional. A blank category lands in the same Uncategorized bucket
the PDF importer uses, so the review queue and a later categorisation treat a
paste the same way they treat a statement row.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.db.models.functions import Lower

from apps.billing.entitlements import PlanLimitExceeded
from apps.finance.import_mpesa import MpesaKind
from apps.finance.import_mpesa_service import _aware, _lazy_category
from apps.finance.models import (
    AccountType,
    Category,
    CategoryKind,
    FinancialAccount,
    Transaction,
    TransactionSource,
    TransactionStatus,
)
from apps.finance.mpesa_sms import MpesaSmsParseError, ParsedMpesaSms, parse_sms, sms_external_id
from apps.finance.payees import get_or_create_payee

MPESA_ACCOUNT_NAME = "M-Pesa"
#: Names a workspace might already be using. Looked up case-insensitively so
#: "M-PESA" and "mpesa" reuse one account rather than minting a second.
_MPESA_ACCOUNT_NAMES = frozenset({"m-pesa", "mpesa", "m pesa"})
_CHARGE_DETAILS = {
    MpesaKind.PAYBILL: "Pay Bill Charge",
    MpesaKind.BUY_GOODS: "Pay Merchant Charge",
    MpesaKind.AGENT_WITHDRAWAL: "Withdrawal Charge",
}


class MpesaSmsError(ValueError):
    """A capture the user can fix — missing account, bad category, etc."""


@dataclass
class MpesaSmsCaptureResult:
    parsed: ParsedMpesaSms
    transaction: Transaction
    charge: Transaction | None
    account: FinancialAccount
    already_recorded: bool
    category_was_set: bool


def get_or_create_default_mpesa_account() -> FinancialAccount:
    """The KES cash account SMS pastes debit.

    Preference order: an account already marked as the M-Pesa default, then
    one named M-Pesa, then create it. Looked up by name rather than a new
    column so existing workspaces that already imported statements into an
    "M-Pesa" account keep using it.
    """
    marked = (
        FinancialAccount.objects.filter(
            is_active=True, archived_at__isnull=True, metadata__mpesa_role="default"
        )
        .order_by("created_at")
        .first()
    )
    if marked is not None:
        return marked

    named = (
        FinancialAccount.objects.annotate(name_l=Lower("name"))
        .filter(
            is_active=True,
            archived_at__isnull=True,
            currency__iexact="KES",
            name_l__in=_MPESA_ACCOUNT_NAMES,
        )
        .order_by("created_at")
        .first()
    )
    if named is not None:
        _mark_default(named)
        return named

    from apps.finance import services as finance_services

    try:
        account = finance_services.create_financial_account(
            name=MPESA_ACCOUNT_NAME,
            account_type=AccountType.CASH,
            currency="KES",
            metadata={"mpesa_role": "default"},
        )
    except PlanLimitExceeded as exc:
        raise MpesaSmsError(
            "Couldn't create the M-Pesa account — this workspace is at its account "
            "limit. Create or rename a KES account to 'M-Pesa', or upgrade."
        ) from exc
    return account


def capture_mpesa_sms(
    *,
    message: str,
    purpose: str = "",
    category: Category | None = None,
    financial_account: FinancialAccount | None = None,
) -> MpesaSmsCaptureResult:
    """Parse `message` and post it to the default M-Pesa account.

    Re-pasting the same receipt and amount returns the existing row and, when
    given, updates purpose and category. That is also how a statement row
    picked up later can receive a purpose: paste the SMS against it.
    """
    parsed = parse_sms(message)
    if category is not None:
        wanted = CategoryKind.INCOME if parsed.is_inflow else CategoryKind.EXPENSE
        if category.kind != wanted:
            raise MpesaSmsError(
                f"That category is {category.kind}, but this message is "
                f"{'money in' if parsed.is_inflow else 'money out'}."
            )

    account = financial_account or get_or_create_default_mpesa_account()
    if account.currency.upper() != "KES":
        raise MpesaSmsError(
            f"{account.name} is in {account.currency}, but M-Pesa is in KES. "
            "Rename or create a KES M-Pesa account."
        )

    with transaction.atomic():
        txn, already = _post_leg(
            parsed=parsed,
            account=account,
            amount_minor=parsed.amount_minor,
            kind=parsed.kind,
            purpose=purpose.strip(),
            category=category,
            is_charge=False,
        )
        charge = None
        if parsed.charge_minor:
            charge, _ = _post_leg(
                parsed=parsed,
                account=account,
                amount_minor=-parsed.charge_minor,
                kind=MpesaKind.CHARGE,
                purpose="",
                category=None,
                is_charge=True,
            )

    return MpesaSmsCaptureResult(
        parsed=parsed,
        transaction=txn,
        charge=charge,
        account=account,
        already_recorded=already,
        category_was_set=category is not None,
    )


def list_sms_captures(*, limit: int = 50) -> list[Transaction]:
    """Recent payment legs posted from an SMS, newest first."""
    return list(
        Transaction.objects.filter(metadata__mpesa_source="sms", metadata__mpesa_leg="payment")
        .exclude(status=TransactionStatus.VOID)
        .select_related("payee", "category", "financial_account")
        .order_by("-occurred_at", "-id")[:limit]
    )


def charges_for(receipts: list[str]) -> dict[str, Transaction]:
    """Charge legs keyed by receipt, for grouping a payment with its fee."""
    if not receipts:
        return {}
    rows = Transaction.objects.filter(
        metadata__mpesa_source="sms",
        metadata__mpesa_leg="charge",
        metadata__mpesa_receipt__in=receipts,
    ).exclude(status=TransactionStatus.VOID)
    return {str(row.metadata.get("mpesa_receipt")): row for row in rows}


def _mark_default(account: FinancialAccount) -> None:
    if account.metadata.get("mpesa_role") == "default":
        return
    account.metadata = {**account.metadata, "mpesa_role": "default"}
    account.save(update_fields=["metadata", "updated_at"])


def _post_leg(
    *,
    parsed: ParsedMpesaSms,
    account: FinancialAccount,
    amount_minor: int,
    kind: MpesaKind,
    purpose: str,
    category: Category | None,
    is_charge: bool,
) -> tuple[Transaction, bool]:
    from apps.finance import services as finance_services

    existing = (
        Transaction.objects.filter(metadata__mpesa_receipt=parsed.receipt, amount_minor=amount_minor)
        .exclude(status=TransactionStatus.VOID)
        .first()
    )
    if existing is not None:
        _refresh_existing(existing, purpose=purpose, category=category, is_charge=is_charge)
        return existing, True

    payee = None
    if not is_charge and parsed.counterparty:
        payee, _ = get_or_create_payee(name=parsed.counterparty)

    resolved = category
    if resolved is None:
        resolved = _category_for(
            kind=kind, currency=account.currency, payee=payee, is_inflow=amount_minor > 0
        )

    memo = (
        purpose if purpose and not is_charge else (_charge_memo(parsed) if is_charge else parsed.counterparty)
    )
    occurred_at = _aware(parsed.occurred_at)
    post = finance_services.record_income if amount_minor > 0 else finance_services.record_expense
    txn = post(
        financial_account=account,
        category=resolved,
        amount_minor=abs(amount_minor),
        occurred_at=occurred_at,
        memo=memo[:255],
        payee=payee,
        source=TransactionSource.IMPORTED,
        tenant_metadata=_metadata(parsed, is_charge=is_charge),
    )
    txn.external_id = sms_external_id(parsed.receipt, amount_minor)
    txn.save(update_fields=["external_id", "updated_at"])
    return txn, False


def _refresh_existing(txn: Transaction, *, purpose: str, category: Category | None, is_charge: bool) -> None:
    """A re-paste, or a paste against a statement row already in the books."""
    from apps.finance import services as finance_services

    meta = {**txn.metadata, "mpesa_source": "sms", "mpesa_leg": "charge" if is_charge else "payment"}
    if txn.metadata != meta:
        txn.metadata = meta
        txn.save(update_fields=["metadata", "updated_at"])
    if is_charge:
        return
    fields: dict = {}
    if purpose and purpose != txn.memo:
        fields["memo"] = purpose
    if category is not None and txn.category_id != category.id:
        fields["category"] = category
    if not fields:
        return
    finance_services.update_transaction(txn=txn, **fields)


def _category_for(*, kind: MpesaKind, currency: str, payee, is_inflow: bool) -> Category:
    wanted = CategoryKind.INCOME if is_inflow else CategoryKind.EXPENSE
    if payee is not None and payee.default_category_id:
        chosen = payee.default_category
        if chosen is not None and chosen.kind == wanted:
            return chosen
    if kind is MpesaKind.CHARGE:
        return _lazy_category(name="M-Pesa Charges", kind=CategoryKind.EXPENSE, currency=currency)
    if kind is MpesaKind.AIRTIME:
        return _lazy_category(name="Airtime & Data", kind=CategoryKind.EXPENSE, currency=currency)
    if kind is MpesaKind.AGENT_WITHDRAWAL:
        return _lazy_category(name="Cash Withdrawal", kind=CategoryKind.EXPENSE, currency=currency)
    name = "Uncategorized Income" if is_inflow else "Uncategorized"
    return _lazy_category(name=name, kind=wanted, currency=currency)


def _metadata(parsed: ParsedMpesaSms, *, is_charge: bool) -> dict:
    return {
        "mpesa_receipt": parsed.receipt,
        "mpesa_source": "sms",
        "mpesa_leg": "charge" if is_charge else "payment",
        "mpesa_kind": parsed.kind.value,
    }


def _charge_memo(parsed: ParsedMpesaSms) -> str:
    label = _CHARGE_DETAILS.get(parsed.kind, "Customer Transfer of Funds Charge")
    return f"{label} · {parsed.receipt}"


# Re-export so callers can catch one module's errors.
__all__ = [
    "MPESA_ACCOUNT_NAME",
    "MpesaSmsCaptureResult",
    "MpesaSmsError",
    "MpesaSmsParseError",
    "capture_mpesa_sms",
    "charges_for",
    "get_or_create_default_mpesa_account",
    "list_sms_captures",
]
