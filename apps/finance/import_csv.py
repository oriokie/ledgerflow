"""Transaction import — bring external activity in from a CSV.

The first concrete import path (bank-aggregator connections like Plaid are the
larger, later build; the model scaffolding — `Transaction.external_id`, the
`(account, external_id)` unique constraint, `TransactionSource.IMPORTED` — was
put in place for both). CSV is universal: every bank and every other finance
app can produce one, and it needs no third-party credentials.

Design choices that make this safe to run repeatedly:

* **Idempotent** — each row may carry an `external_id`; re-importing the same
  file skips rows whose `(account, external_id)` already exists, so a
  double-upload never double-posts. Rows without an external id fall back to a
  content hash of (date, amount, description) for the same protection.
* **Real postings** — imported rows go through `record_expense`/`record_income`
  like any other money movement, so the ledger stays the single source of
  truth. They're marked `source=IMPORTED` and left uncategorized, which lets
  the auto-categorization pipeline suggest categories on create.
* **All-or-report** — parsing errors are collected per-row and returned; valid
  rows still import. The caller sees exactly what succeeded and what didn't.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from .models import FinancialAccount, Transaction, TransactionSource


class ImportError_(Exception):
    """Named with a trailing underscore to avoid shadowing the builtin."""


@dataclass
class ImportResult:
    imported: int = 0
    skipped_duplicate: int = 0
    errors: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "imported": self.imported,
            "skipped_duplicate": self.skipped_duplicate,
            "errors": self.errors,
        }


# Column aliases accepted for each logical field (case-insensitive). Keeps the
# importer forgiving of the many near-identical CSV dialects banks emit.
_ALIASES = {
    "date": {"date", "posted", "posted_date", "transaction_date", "occurred_at"},
    "amount": {"amount", "value", "debit_credit"},
    "description": {"description", "memo", "name", "details", "payee"},
    "external_id": {"external_id", "id", "reference", "fitid", "transaction_id"},
}


#: The canonical header, and one example row per sign.
#:
#: Handed to users as a downloadable template. The importer accepts any of the
#: aliases above, but somebody starting from scratch needs *one* answer rather
#: than a list of things that would also work — and the two example rows carry
#: the only rule that isn't guessable: sign is direction, so a negative amount
#: is money out and a positive one is money in.
TEMPLATE_HEADER = ["date", "amount", "description", "external_id"]
TEMPLATE_ROWS = [
    ["2026-01-15", "-42.50", "Naivas — groceries", "REF-00001"],
    ["2026-01-25", "3200.00", "Salary — January", "REF-00002"],
]


def template_csv() -> str:
    """The blank import template, as CSV text."""
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(TEMPLATE_HEADER)
    writer.writerows(TEMPLATE_ROWS)
    return buf.getvalue()


def _resolve_columns(header: list[str]) -> dict[str, str]:
    lower = {h.lower().strip(): h for h in header}
    resolved: dict[str, str] = {}
    for logical, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in lower:
                resolved[logical] = lower[alias]
                break
    return resolved


def _parse_amount_minor(raw: str) -> int:
    """Parse a decimal string to signed minor units. Accepts parentheses for
    negatives and thousands separators."""
    s = raw.strip().replace(",", "")
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").strip()
    value = float(s)
    minor = int(round(value * 100))
    return -abs(minor) if negative else minor


def _parse_date(raw: str) -> datetime:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%m/%d/%y"):
        try:
            dt = datetime.strptime(raw, fmt)
            return timezone.make_aware(dt, timezone.get_current_timezone())
        except ValueError:
            continue
    # last resort: ISO parser
    dt = datetime.fromisoformat(raw)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _fallback_external_id(occurred_at: datetime, amount_minor: int, description: str) -> str:
    digest = hashlib.sha256(
        f"{occurred_at.date()}|{amount_minor}|{description.strip().lower()}".encode()
    ).hexdigest()
    return f"csvhash:{digest[:24]}"


@transaction.atomic
def import_transactions_csv(
    *,
    financial_account: FinancialAccount,
    file_content: str,
    default_category=None,
) -> ImportResult:
    """Import rows from CSV text into `financial_account`. `default_category`
    is required only if you want a category assigned at import; otherwise rows
    import uncategorized (the auto-categorization pipeline will suggest one)."""
    from . import services as finance_services

    result = ImportResult()
    reader = csv.reader(io.StringIO(file_content))
    try:
        header = next(reader)
    except StopIteration:
        raise ImportError_("CSV is empty.") from None

    cols = _resolve_columns(header)
    missing = {"date", "amount", "description"} - set(cols)
    if missing:
        raise ImportError_(f"CSV missing required column(s): {', '.join(sorted(missing))}.")
    index = {logical: header.index(actual) for logical, actual in cols.items()}

    for line_no, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue  # blank line
        try:
            occurred_at = _parse_date(row[index["date"]])
            amount_minor = _parse_amount_minor(row[index["amount"]])
            description = row[index["description"]].strip()
            if amount_minor == 0:
                raise ValueError("amount is zero")
            external_id = (
                row[index["external_id"]].strip()
                if "external_id" in index and index["external_id"] < len(row)
                else ""
            )
            if not external_id:
                external_id = _fallback_external_id(occurred_at, amount_minor, description)
        except (ValueError, IndexError) as exc:
            result.errors.append({"line": line_no, "error": str(exc)})
            continue

        # idempotency: skip if this external_id already imported for the account
        if Transaction.objects.filter(financial_account=financial_account, external_id=external_id).exists():
            result.skipped_duplicate += 1
            continue

        try:
            # Each row gets its own savepoint, which is what makes the
            # "all-or-report" promise above actually true. Without one, a row
            # that fails on a *database* error (rather than a parse error, which
            # is caught further up) marks the enclosing atomic block as broken,
            # and every subsequent query raises TransactionManagementError. The
            # symptom is nasty: a single bad row part-way through aborts the
            # whole import while reporting itself as one skipped line, so the
            # caller is told 900 rows imported cleanly when none of them did.
            with transaction.atomic():
                if amount_minor < 0:
                    if default_category is None:
                        txn = _import_uncategorized(
                            finance_services, financial_account, amount_minor, occurred_at, description
                        )
                    else:
                        txn = finance_services.record_expense(
                            financial_account=financial_account,
                            category=default_category,
                            amount_minor=abs(amount_minor),
                            occurred_at=occurred_at,
                            memo=description,
                            source=TransactionSource.IMPORTED,
                        )
                else:
                    txn = _import_uncategorized(
                        finance_services, financial_account, amount_minor, occurred_at, description
                    )
                txn.external_id = external_id
                txn.save(update_fields=["external_id", "updated_at"])
            result.imported += 1
        except Exception as exc:  # noqa: BLE001 - report and continue
            result.errors.append({"line": line_no, "error": str(exc)})

    return result


def _import_uncategorized(finance_services, account, amount_minor, occurred_at, description):
    """Import a row we can't cleanly categorize yet.

    Income posts normally (income needs no category-account choice beyond a
    default income category is out of scope here, so we require the caller's
    default for expenses only). For an uncategorized expense we still need a
    ledger-valid posting; we route it through a per-account "Uncategorized"
    expense category, created lazily, so the money movement is real and the
    auto-categorization pipeline can refine it afterward.
    """
    from .models import CategoryKind

    if amount_minor > 0:
        category = _lazy_category(finance_services, account, CategoryKind.INCOME, "Uncategorized Income")
        return finance_services.record_income(
            financial_account=account,
            category=category,
            amount_minor=amount_minor,
            occurred_at=occurred_at,
            memo=description,
            source=TransactionSource.IMPORTED,
        )
    category = _lazy_category(finance_services, account, CategoryKind.EXPENSE, "Uncategorized")
    return finance_services.record_expense(
        financial_account=account,
        category=category,
        amount_minor=abs(amount_minor),
        occurred_at=occurred_at,
        memo=description,
        source=TransactionSource.IMPORTED,
    )


def _lazy_category(finance_services, account, kind, name):
    from .models import Category

    existing = Category.objects.filter(kind=kind, name=name).first()
    if existing is not None:
        return existing
    return finance_services.create_category(name=name, kind=kind, currency=account.currency)
