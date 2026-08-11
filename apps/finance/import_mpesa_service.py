"""Post a parsed M-Pesa statement to the ledger.

`import_mpesa.py` reads the PDF; this decides what each row *means* and posts
it. The split matters because the two jobs fail differently — a parsing bug
produces wrong numbers, a posting bug produces wrong books — and only the
second one needs a database to test.

Three decisions carry the weight here.

**Fuliza is debt, not income.** Safaricom reports an overdraft advance in the
Paid In column, identically to a salary. Imported literally, three months of
this statement would have declared ~KES 69,000 of income nobody earned and an
equal amount of spending on nothing — inflating the health score, the budget
and every projection downstream. Advances and repayments are posted instead as
transfers against a Fuliza credit line, which `record_transfer` already
excludes from income and spending totals, and which leaves the outstanding
balance visible as what it is: money owed. The *purchase* the overdraft funded
stays an ordinary expense, because it was one.

**Charges are transactions.** Each fee is its own row sharing a receipt number
with the payment that incurred it. They are small — a few shillings — and
there were 244 of them in one quarter. Folding them into the parent payment
would hide a recurring cost that is worth seeing; dropping them would put the
books out by their total. They post as ordinary expenses under one category,
so "what does M-Pesa cost me" is a single number.

**A counterparty is a payee.** M-Pesa names who was paid, and the same names
recur constantly. Each becomes a `Payee` via the existing pipeline, so
categorising "Naivas Kahawa Sukari" once teaches every future import — rather
than presenting the same 275 names for triage every month.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db import transaction
from django.utils import timezone

from .import_mpesa import MpesaKind, MpesaParseError, MpesaRow, ParsedStatement, parse_statement
from .models import AccountType, CategoryKind, FinancialAccount, Transaction, TransactionSource

#: The name of the credit line created on first sight of an overdraft. Looked
#: up by name so a re-import reuses it rather than stacking up duplicates.
FULIZA_ACCOUNT_NAME = "Fuliza (M-Pesa overdraft)"

#: Categories implied by the transaction type itself. Only the kinds where the
#: statement genuinely tells us the purpose — a till payment could be groceries
#: or fuel and guessing would be worse than leaving it open for the payee rule
#: or the user to settle.
_CATEGORY_FOR_KIND: dict[MpesaKind, tuple[str, str]] = {
    MpesaKind.CHARGE: ("M-Pesa Charges", CategoryKind.EXPENSE),
    MpesaKind.AIRTIME: ("Airtime & Data", CategoryKind.EXPENSE),
    MpesaKind.AGENT_WITHDRAWAL: ("Cash Withdrawal", CategoryKind.EXPENSE),
    MpesaKind.AGENT_DEPOSIT: ("Cash Deposit", CategoryKind.INCOME),
    MpesaKind.SALARY: ("Salary", CategoryKind.INCOME),
}


@dataclass
class MpesaImportResult:
    imported: int = 0
    skipped_duplicate: int = 0
    errors: list[dict] = field(default_factory=list)

    #: Reported separately because they are the figures a user will not believe
    #: unless shown: money that looked like income but was borrowing.
    overdraft_advanced_minor: int = 0
    overdraft_repaid_minor: int = 0
    charges_minor: int = 0

    payees_created: int = 0
    auto_categorised: int = 0

    statement_period: str = ""
    rows_found: int = 0
    #: How many of `rows_found` fell inside the requested window. Equal to
    #: rows_found when no window was given.
    rows_in_range: int = 0
    from_date: str = ""
    to_date: str = ""
    #: True/False/None — None means the statement printed no totals to check.
    reconciles: bool | None = None
    discrepancy: str = ""

    #: Things worth telling the user that are not errors. Chiefly the
    #: partial-history case below, which otherwise reads as a bug.
    notices: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "imported": self.imported,
            "skipped_duplicate": self.skipped_duplicate,
            "errors": self.errors,
            "notices": self.notices,
            "rows_found": self.rows_found,
            "rows_in_range": self.rows_in_range,
            "from_date": self.from_date,
            "to_date": self.to_date,
            "statement_period": self.statement_period,
            "reconciles": self.reconciles,
            "discrepancy": self.discrepancy,
            "overdraft_advanced_minor": self.overdraft_advanced_minor,
            "overdraft_repaid_minor": self.overdraft_repaid_minor,
            "charges_minor": self.charges_minor,
            "payees_created": self.payees_created,
            "auto_categorised": self.auto_categorised,
        }


def preview_statement(*, file_bytes: bytes, password: str = "") -> dict:
    """Read the statement and describe it without posting anything.

    Uploading three months of somebody's financial life is not a step to take
    on trust. This answers "what is in this file, and does it add up" before
    the user commits to writing 866 rows into their books.
    """
    statement = parse_statement(file_bytes, password)
    by_kind: dict[str, dict] = {}
    #: Rows per calendar day. Small — a quarterly statement spans ~92 keys — and
    #: it lets the client show how many transactions a chosen date window
    #: actually covers, instead of promising the whole statement and delivering
    #: a subset.
    by_day: dict[str, int] = {}
    for row in statement.rows:
        bucket = by_kind.setdefault(row.kind.value, {"count": 0, "total_minor": 0})
        bucket["count"] += 1
        bucket["total_minor"] += row.amount_minor
        day = row.completed_at.date().isoformat()
        by_day[day] = by_day.get(day, 0) + 1

    return {
        "customer_name": statement.customer_name,
        "mobile_number": statement.mobile_number,
        "period_start": statement.period_start,
        "period_end": statement.period_end,
        "rows_found": len(statement.rows),
        "paid_in_minor": statement.parsed_paid_in_minor,
        "withdrawn_minor": statement.parsed_withdrawn_minor,
        "reconciles": statement.reconciles,
        "discrepancy": statement.discrepancy(),
        "by_kind": by_kind,
        "by_day": by_day,
        # Derived from the rows rather than the printed header: the header is a
        # requested range, and the rows are what is actually in the file.
        "first_seen": min(r.completed_at for r in statement.rows).isoformat() if statement.rows else None,
        "last_seen": max(r.completed_at for r in statement.rows).isoformat() if statement.rows else None,
    }


def import_mpesa_statement(
    *,
    financial_account: FinancialAccount,
    file_bytes: bytes,
    password: str = "",
    track_overdraft_as_debt: bool = True,
    from_date: date | None = None,
    to_date: date | None = None,
) -> MpesaImportResult:
    """Import an M-Pesa PDF statement into `financial_account`.

    `password` is used to decrypt and then goes out of scope — it is never
    persisted, never logged and never returned.
    """
    return import_parsed_statement(
        financial_account=financial_account,
        statement=parse_statement(file_bytes, password),
        track_overdraft_as_debt=track_overdraft_as_debt,
        from_date=from_date,
        to_date=to_date,
    )


@transaction.atomic
def import_parsed_statement(
    *,
    financial_account: FinancialAccount,
    statement: ParsedStatement,
    track_overdraft_as_debt: bool = True,
    from_date: date | None = None,
    to_date: date | None = None,
) -> MpesaImportResult:
    """Post an already-parsed statement, optionally only part of it.

    Split out from the PDF path so the posting rules — the Fuliza direction,
    idempotency, category resolution — can be tested by constructing rows in
    code. That keeps the test suite free of a real statement fixture, which
    matters here: a genuine M-Pesa PDF is somebody's complete financial and
    social history, and it has no business living in a git repository.

    Why a date window exists
    ------------------------
    Re-importing the *same* statement is already safe: identity is derived from
    the row, so the second run skips everything. What that does not protect
    against is the far more likely overlap — somebody who has been entering
    transactions by hand since June, importing a statement that starts in May.
    A hand-entered transaction has no `external_id`, so it can never match an
    imported one, and June to August is silently recorded twice: once by the
    person, once by the importer.

    No amount of cleverness fixes that automatically. Guessing which manual
    entry corresponds to which statement row means matching on date and amount,
    which is wrong often enough to be worse than useless — two 200-shilling
    payments on the same day are not unusual, and merging the wrong pair
    destroys data the user typed themselves. So the window is the user's
    decision, made with the facts in front of them, and `_warn_about_overlap`
    tells them when it looks like they have chosen badly.
    """
    result = MpesaImportResult(
        rows_found=len(statement.rows),
        statement_period=f"{statement.period_start} – {statement.period_end}".strip(" –"),
        reconciles=statement.reconciles,
        discrepancy=statement.discrepancy(),
    )

    # Refuse a currency mismatch rather than silently posting shillings into a
    # dollar account: the numbers would look plausible and be wrong by a factor
    # of ~130, which is the kind of error nobody catches by eye.
    if financial_account.currency.upper() != "KES":
        raise MpesaParseError(
            f"M-Pesa statements are in KES but {financial_account.name} is in "
            f"{financial_account.currency}. Choose or create a KES account."
        )

    # Reconciliation is computed over the *whole* statement, above, before any
    # window is applied — it answers "did we read the file correctly", which is
    # a question about parsing, not about what the user chose to keep. Checking
    # a filtered subset against the statement's printed totals would fail every
    # time a window was used, and would train people to ignore the one signal
    # that catches a genuinely broken parse.
    selected = [r for r in statement.rows if _within(r, from_date, to_date)]
    result.rows_in_range = len(selected)
    result.from_date = from_date.isoformat() if from_date else ""
    result.to_date = to_date.isoformat() if to_date else ""

    fuliza = None
    if track_overdraft_as_debt and any(r.kind in _OVERDRAFT for r in selected):
        fuliza = _get_or_create_fuliza(financial_account.currency)

    _warn_about_overlap(financial_account, selected, result)

    # Oldest first. The statement reads newest-first, but posting in reverse
    # means every intermediate balance the ledger computes is one that never
    # existed, and an overdraft guard or a reconciliation looking at the running
    # figure would be reading fiction.
    for row in sorted(selected, key=lambda r: r.completed_at):
        if Transaction.objects.filter(
            financial_account=financial_account, external_id=row.external_id
        ).exists():
            result.skipped_duplicate += 1
            continue
        try:
            # Each row gets its own savepoint. Without one, a row that fails on
            # a database error marks the whole outer transaction as broken, and
            # every subsequent query raises TransactionManagementError instead
            # of doing anything — so a single bad row 800 rows in would abort
            # the entire import while *reporting* itself as one skipped line.
            # The savepoint is what makes "valid rows still import" true rather
            # than merely intended.
            with transaction.atomic():
                _post_row(row, financial_account, fuliza, result)
        except Exception as exc:  # noqa: BLE001 — report the row, keep going
            result.errors.append(
                {"receipt": row.receipt, "occurred_at": row.completed_at.isoformat(), "error": str(exc)}
            )

    _add_overdraft_notice(fuliza, result)
    return result


def _within(row: MpesaRow, from_date: date | None, to_date: date | None) -> bool:
    """Is this row inside the requested window? Both bounds are inclusive,
    because a person asking for "1 June to 30 June" means the whole of both
    days, and an exclusive end silently drops the last day's activity."""
    on = row.completed_at.date()
    return not (from_date and on < from_date) and not (to_date and on > to_date)


def _warn_about_overlap(
    financial_account: FinancialAccount, selected: list[MpesaRow], result: MpesaImportResult
) -> None:
    """Say so when the window overlaps transactions the user entered by hand.

    The importer's idempotency only recognises its own work: a row it posted
    carries an `external_id`, and a second import of the same statement matches
    on it. A transaction somebody typed in has no `external_id` and never will,
    so nothing stops the same coffee appearing twice — once as they recorded it,
    once as Safaricom did.

    This does not refuse the import, because it cannot know: the manual entries
    might be for a completely different account's activity, or deliberate
    placeholders the user wants replaced. It states the fact and leaves the
    judgement where it belongs.
    """
    if not selected:
        return
    # Localised through the same helper the posting path uses. Comparing the
    # statement's naive timestamps directly against an aware column makes Django
    # assume UTC, which in East Africa shifts the window by three hours and
    # quietly mis-reports the overlap at both ends.
    first = _aware(min(r.completed_at for r in selected))
    last = _aware(max(r.completed_at for r in selected))

    existing = (
        Transaction.objects.filter(
            financial_account=financial_account,
            occurred_at__gte=first,
            occurred_at__lte=last,
            external_id="",
        )
        .exclude(source=TransactionSource.IMPORTED)
        .count()
    )
    if existing == 0:
        return

    result.notices.append(
        f"{existing} transaction{'s' if existing != 1 else ''} already recorded on this account "
        f"between {first.date()} and {last.date()} did not come from a statement import, so the "
        "importer cannot tell whether they are the same money. If you entered them by hand, "
        "importing this period will record it twice — set a start date after your last manual "
        "entry, or remove those entries first."
    )


def _add_overdraft_notice(fuliza: FinancialAccount | None, result: MpesaImportResult) -> None:
    """Explain a Fuliza balance that ends up negative.

    A statement is a window, not a history. If the user was already carrying
    Fuliza debt on the first day of it, the repayments inside the window exceed
    the advances inside the window, and the credit line finishes showing less
    than nothing owed. That is arithmetic, not a bug — but "-841.02 owed" reads
    exactly like a bug, so it is named here rather than left to be discovered.
    """
    if fuliza is None:
        return
    from .selectors import account_current_balance_minor

    balance = account_current_balance_minor(fuliza)
    if balance >= 0:
        return
    result.notices.append(
        f"The Fuliza credit line shows {abs(balance) / 100:,.2f} more repaid than borrowed. "
        "That happens when the statement begins partway through an outstanding "
        "overdraft — the repayments are in the window but the borrowing came "
        "before it. Import an earlier statement, or set the opening balance on "
        "the Fuliza account, to square it."
    )


_OVERDRAFT = {MpesaKind.OVERDRAFT_ADVANCE, MpesaKind.OVERDRAFT_REPAYMENT}


def _post_row(
    row: MpesaRow,
    account: FinancialAccount,
    fuliza: FinancialAccount | None,
    result: MpesaImportResult,
) -> None:
    from . import services as finance_services

    occurred_at = _aware(row.completed_at)

    # --- the Fuliza pair -----------------------------------------------------
    #
    # Direction follows double entry rather than intuition: crediting a
    # liability *increases* what is owed. So an advance flows from the credit
    # line into M-Pesa (Fuliza credited, cash debited) and a repayment flows
    # back. `record_transfer` excludes both from income and spending, which is
    # the entire point.
    if row.kind in _OVERDRAFT and fuliza is not None:
        amount = abs(row.amount_minor)
        if row.kind is MpesaKind.OVERDRAFT_ADVANCE:
            source, destination = fuliza, account
            result.overdraft_advanced_minor += amount
        else:
            source, destination = account, fuliza
            result.overdraft_repaid_minor += amount

        legs = finance_services.record_transfer(
            from_account=source,
            to_account=destination,
            amount_minor=amount,
            occurred_at=occurred_at,
            memo=row.details,
            source=TransactionSource.IMPORTED,
        )
        # Stamp the leg sitting on the *statement's* account, not whichever one
        # happens to be first. A transfer has two legs on two accounts, and the
        # duplicate check queries the statement account — so stamping the Fuliza
        # leg of an advance (which flows Fuliza -> M-Pesa) left those 95 rows
        # invisible to it, and every re-import posted them again.
        for leg in legs:
            if leg.financial_account_id == account.id:
                _stamp(leg, external_id=row.external_id, receipt=row.receipt)
            else:
                # Both halves represent the same imported statement event.
                # Keep the receipt on each for audit/display, while only the
                # statement-account leg carries dedupe identity.
                _stamp(leg, receipt=row.receipt)
        result.imported += 1
        return

    # --- everything else -----------------------------------------------------
    payee = _resolve_payee(row, result)
    category, learned = _resolve_category(row, account.currency, payee)
    if learned:
        result.auto_categorised += 1
    if row.kind is MpesaKind.CHARGE:
        result.charges_minor += abs(row.amount_minor)

    post = finance_services.record_income if row.is_inflow else finance_services.record_expense
    txn = post(
        financial_account=account,
        category=category,
        amount_minor=abs(row.amount_minor),
        occurred_at=occurred_at,
        memo=row.details,
        payee=payee,
        source=TransactionSource.IMPORTED,
    )
    _stamp(txn, external_id=row.external_id, receipt=row.receipt)
    result.imported += 1


def _stamp(txn: Transaction, *, receipt: str, external_id: str = "") -> None:
    """Record M-Pesa audit metadata and, on the statement leg, dedupe identity."""
    txn.metadata = {**txn.metadata, "mpesa_receipt": receipt}
    fields = ["metadata", "updated_at"]
    if external_id:
        txn.external_id = external_id
        fields.append("external_id")
    txn.save(update_fields=fields)


def _aware(naive):
    """M-Pesa timestamps carry no zone; they are East Africa Time in practice,
    so they are localised to the workspace's zone rather than assumed UTC —
    which would shift every late-evening transaction onto the previous day and
    quietly move spending between months."""
    if timezone.is_aware(naive):
        return naive
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _resolve_payee(row: MpesaRow, result: MpesaImportResult):
    """Turn the counterparty into a `Payee`, if the row named one."""
    if not row.counterparty:
        return None
    from .payees import get_or_create_payee

    payee, created = get_or_create_payee(name=row.counterparty)
    if created:
        result.payees_created += 1
    return payee


def _resolve_category(row: MpesaRow, currency: str, payee):
    """Pick a category, most-specific source first.

    Returns `(category, was_auto_assigned)`. The order is deliberate: a payee
    rule is something the user themselves established, so it outranks anything
    inferred from the transaction type.
    """
    kind_wanted = CategoryKind.INCOME if row.is_inflow else CategoryKind.EXPENSE

    # 1. What the user already decided for this payee.
    if payee is not None and payee.default_category_id:
        category = payee.default_category
        if category is not None and category.kind == kind_wanted:
            return category, True

    # 2. What the transaction type unambiguously implies.
    mapped = _CATEGORY_FOR_KIND.get(row.kind)
    if mapped is not None:
        name, kind = mapped
        if kind == kind_wanted:
            return _lazy_category(name=name, kind=kind, currency=currency), True

    # 3. Nothing known — leave it for the auto-categorisation pipeline and the
    #    user, rather than inventing a category that reads as a real decision.
    name = "Uncategorized Income" if row.is_inflow else "Uncategorized"
    return _lazy_category(name=name, kind=kind_wanted, currency=currency), False


def _lazy_category(*, name: str, kind: str, currency: str):
    """Get-or-create a system category, mirroring the CSV importer's helper so
    both importers land in the same buckets rather than two parallel sets."""
    from .models import Category

    existing = Category.objects.filter(kind=kind, name=name).first()
    if existing is not None:
        return existing
    from . import services as finance_services

    return finance_services.create_category(name=name, kind=kind, currency=currency)


def _get_or_create_fuliza(currency: str) -> FinancialAccount:
    """The Fuliza credit line, created on first sight of an overdraft.

    A real liability account rather than a bookkeeping flag, so the outstanding
    balance appears in net worth and the debt module's payoff tooling works on
    it like any other borrowing.
    """
    existing = FinancialAccount.objects.filter(
        name=FULIZA_ACCOUNT_NAME, account_type=AccountType.LOAN
    ).first()
    if existing is not None:
        return existing

    from apps.debt.models import DebtKind
    from apps.debt.services import create_debt

    profile = create_debt(
        name=FULIZA_ACCOUNT_NAME,
        currency=currency,
        balance_minor=0,
        debt_kind=DebtKind.OTHER,
        lender="Safaricom",
    )
    return profile.financial_account


def statement_summary(statement: ParsedStatement) -> dict:
    """Small helper for tests and the preview endpoint."""
    return {
        "rows": len(statement.rows),
        "reconciles": statement.reconciles,
        "paid_in_minor": statement.parsed_paid_in_minor,
        "withdrawn_minor": statement.parsed_withdrawn_minor,
    }
