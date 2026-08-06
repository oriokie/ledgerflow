"""Read an M-Pesa PDF statement.

Parsing only — no Django import anywhere in this module, so the whole thing is
testable against a fixture without a database, and the messy work of
understanding Safaricom's layout stays separate from the work of posting to a
ledger. `import_mpesa_service.py` does the posting.

Why a PDF importer at all, when `import_csv.py` exists
------------------------------------------------------
Because M-Pesa does not give you a CSV. The statement Safaricom emails is a
password-protected PDF, and for a great many people in Kenya it *is* their
bank statement — the primary record of what they earn and spend. Telling that
user to retype 866 rows into a CSV template is telling them not to use the
product.

What the format actually is
---------------------------
Every page carries the same seven-column table:

    Receipt No. | Completion Time | Details | Transaction Status | Paid In | Withdrawn | Balance

with three properties worth knowing before trusting any of it:

* **The receipt number is not unique.** A single transfer produces up to three
  rows sharing one receipt: the transfer, its charge, and — when Fuliza covers
  a shortfall — the overdraft advance. Keying on the receipt alone would
  silently drop the charges, which are real money. The identity used here is
  ``(receipt, details, amount)``, verified unique across a real 866-row
  statement.

* **Exactly one of Paid In / Withdrawn is populated,** and the sign is already
  correct in the source: Paid In is positive, Withdrawn carries its own minus.
  So the amount is simply whichever column is non-empty — no sign inference,
  which is the usual way importers get direction backwards.

* **The statement states its own totals**, on the summary page. That makes the
  parse checkable rather than merely plausible: `ParsedStatement.reconciles`
  compares what was parsed against what Safaricom printed, and a mismatch means
  rows were missed. An importer that silently drops 5% of a statement is worse
  than one that refuses, because the resulting books look complete.

Fuliza, and why it is not income
--------------------------------
Fuliza is M-Pesa's overdraft. When a payment exceeds the balance, Safaricom
posts an ``OverDraft of Credit Party`` row — money arriving in the Paid In
column — and later ``OD Loan Repayment`` rows going out. Read literally, a
statement with heavy Fuliza use reports tens of thousands of shillings of
income that nobody ever earned, and an equal amount of spending on nothing.
Both figures are borrowing. The classifier tags these two kinds so the
importer can route them to a credit line instead of to income and expense.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class MpesaParseError(ValueError):
    """The file is not a statement we can read, or the password is wrong."""


class MpesaKind(StrEnum):
    """What a row *is*, derived from the Details column.

    Coarser than Safaricom's own wording on purpose: "Merchant Payment Online",
    "Merchant Payment to" and "Merchant Payment Fuliza M-Pesa Online" differ
    only in the rail used, and a person reading their spending does not care
    which. What they care about is that it was a till.
    """

    SEND_MONEY = "send_money"
    RECEIVE = "receive"
    PAYBILL = "paybill"
    BUY_GOODS = "buy_goods"
    AIRTIME = "airtime"
    AGENT_WITHDRAWAL = "agent_withdrawal"
    AGENT_DEPOSIT = "agent_deposit"
    SALARY = "salary"
    CHARGE = "charge"
    #: Fuliza lending you money. Paid In, but not income.
    OVERDRAFT_ADVANCE = "overdraft_advance"
    #: Paying Fuliza back. Withdrawn, but not spending.
    OVERDRAFT_REPAYMENT = "overdraft_repayment"
    REVERSAL = "reversal"
    OTHER = "other"


#: Kinds that are movements on the Fuliza credit line rather than income or
#: spending. The importer posts these as transfers against a debt account.
OVERDRAFT_KINDS = frozenset({MpesaKind.OVERDRAFT_ADVANCE, MpesaKind.OVERDRAFT_REPAYMENT})


# Ordered: the first pattern that matches wins, so the more specific phrasing
# must come first. "Customer Transfer of Funds Charge" has to be tested before
# "Customer Transfer to", or every charge is misread as a transfer.
#
# Each entry is (compiled pattern, kind, name of the counterparty group).
_RULES: list[tuple[re.Pattern[str], MpesaKind, str | None]] = [
    # --- charges. Always their own row, always an outflow. -------------------
    (
        re.compile(
            r"^(Customer Transfer of Funds|Pay Bill|Pay Merchant|Withdrawal|Buy Goods)\s+Charge", re.I
        ),
        MpesaKind.CHARGE,
        None,
    ),
    # --- the Fuliza pair, checked early because they are easy to mistake -----
    (re.compile(r"^OverDraft of Credit Party", re.I), MpesaKind.OVERDRAFT_ADVANCE, None),
    (re.compile(r"^OD Loan Repayment", re.I), MpesaKind.OVERDRAFT_REPAYMENT, None),
    (re.compile(r"^Reversal", re.I), MpesaKind.REVERSAL, None),
    # --- airtime and data ----------------------------------------------------
    (re.compile(r"^Airtime Purchase", re.I), MpesaKind.AIRTIME, None),
    (
        re.compile(r"^Customer Bundle Purchase(?: with Fuliza)? to \d*(?P<who>[A-Z][A-Z ]+?) by\b", re.I),
        MpesaKind.AIRTIME,
        "who",
    ),
    (re.compile(r"^Recharge for Customer to \d*(?P<who>[A-Z][A-Z ]+?) by\b", re.I), MpesaKind.AIRTIME, "who"),
    # --- agent cash ----------------------------------------------------------
    (
        re.compile(r"^Customer Withdrawal At Agent Till \d+\s*-\s*(?P<who>.+)$", re.I),
        MpesaKind.AGENT_WITHDRAWAL,
        "who",
    ),
    (
        re.compile(r"^Deposit of Funds at Agent Till \d+\s*-\s*(?P<who>.+)$", re.I),
        MpesaKind.AGENT_DEPOSIT,
        "who",
    ),
    # --- money in ------------------------------------------------------------
    # Salary before the generic bank credit: both arrive "from <paybill> - <bank>
    # via API", and only the wording distinguishes a wage from a transfer.
    # Captured greedily to the end and trimmed afterwards by `_clean_party`.
    # An optional "(?:\s+via API)?" inside the pattern reads well but behaves
    # badly: combined with a non-greedy name it backtracks to either the
    # shortest possible match ("EXAMPLE" out of "EXAMPLE BULK") or the longest
    # ("EXAMPLE BANK via API"), depending on what follows. Suffix stripping is
    # predictable in a way that optional groups next to `.+?` are not.
    (re.compile(r"^Salary Payment from \d+\s*-\s*(?P<who>.+)$", re.I), MpesaKind.SALARY, "who"),
    (re.compile(r"^Business Payment from \d+\s*-\s*(?P<who>.+)$", re.I), MpesaKind.RECEIVE, "who"),
    (
        re.compile(r"^Funds received from\s*-?\s*(?:\+?\d[\d*]*\s+)?(?P<who>.+)$", re.I),
        MpesaKind.RECEIVE,
        "who",
    ),
    (
        re.compile(r"^Receive International Transfer From \d+\s*-\s*(?P<who>.+?)[.\s]*$", re.I),
        MpesaKind.RECEIVE,
        "who",
    ),
    (
        re.compile(
            r"^Small Business Payment to Customer via API from\s*-?\s*(?:\+?\d[\d*]*\s+)?(?P<who>.+)$", re.I
        ),
        MpesaKind.RECEIVE,
        "who",
    ),
    (re.compile(r"^Transfer from Bank \d+\s*-\s*(?P<who>.+?)\s+to Customer", re.I), MpesaKind.RECEIVE, "who"),
    # --- paybill -------------------------------------------------------------
    # The trailing "Acc. <ref>" is dropped: it is the biller's account number
    # for this customer, so keeping it in the payee name would make every
    # payment to the same biller look like a different one.
    (
        re.compile(r"^Pay Bill Online(?: Fuliza M-Pesa)? to \d+\s*-\s*(?P<who>.+?)(?:\s+Acc\..*)?$", re.I),
        MpesaKind.PAYBILL,
        "who",
    ),
    # --- till / buy goods ----------------------------------------------------
    (
        re.compile(r"^Merchant Payment(?: Fuliza M-Pesa)?(?: Online)?(?: to)? \d+\s*-\s*(?P<who>.+)$", re.I),
        MpesaKind.BUY_GOODS,
        "who",
    ),
    # --- person to person ----------------------------------------------------
    # The phone number is stripped; it is already partly masked by Safaricom
    # and the name is the useful half for grouping repeat recipients.
    (
        re.compile(
            r"^(?:Customer Transfer(?: Fuliza MPesa)? to|Customer Payment to Small Business to|"
            r"Customer Send Money to Micro SME Business(?: with Fuliza MPesa)? to)"
            r"\s*-?\s*(?:\+?\d[\d*]*\s+)?(?P<who>.+)$",
            re.I,
        ),
        MpesaKind.SEND_MONEY,
        "who",
    ),
]


@dataclass(frozen=True, slots=True)
class MpesaRow:
    receipt: str
    completed_at: datetime
    details: str
    status: str
    #: Signed minor units. Negative is money out, matching the rest of the app.
    amount_minor: int
    balance_minor: int | None
    kind: MpesaKind
    #: Who the money went to or came from, blank when the row names nobody
    #: (charges, overdraft movements, plain airtime).
    counterparty: str

    @property
    def is_inflow(self) -> bool:
        return self.amount_minor > 0

    @property
    def external_id(self) -> str:
        """Stable identity for idempotency.

        Not the receipt number alone — see the module docstring. Built from the
        three fields that together distinguish the rows sharing a receipt, so
        re-importing an overlapping statement (they overlap by design: people
        request three months at a time, every month) skips what is already
        there instead of duplicating it.
        """
        import hashlib

        digest = hashlib.sha256(f"{self.receipt}|{self.details}|{self.amount_minor}".encode()).hexdigest()
        return f"mpesa:{self.receipt}:{digest[:12]}"


@dataclass
class ParsedStatement:
    rows: list[MpesaRow] = field(default_factory=list)
    customer_name: str = ""
    mobile_number: str = ""
    period_start: str = ""
    period_end: str = ""
    #: The totals Safaricom printed on the summary page, in minor units.
    #: None when the summary was absent (some exports omit it).
    declared_paid_in_minor: int | None = None
    declared_withdrawn_minor: int | None = None

    @property
    def parsed_paid_in_minor(self) -> int:
        return sum(r.amount_minor for r in self.rows if r.amount_minor > 0)

    @property
    def parsed_withdrawn_minor(self) -> int:
        return -sum(r.amount_minor for r in self.rows if r.amount_minor < 0)

    @property
    def reconciles(self) -> bool | None:
        """Does what we read add up to what the statement claims?

        None when the statement printed no totals to check against — an honest
        "cannot tell", not a pass. The importer surfaces all three states
        rather than collapsing unknown into success.
        """
        if self.declared_paid_in_minor is None or self.declared_withdrawn_minor is None:
            return None
        return (
            self.parsed_paid_in_minor == self.declared_paid_in_minor
            and self.parsed_withdrawn_minor == self.declared_withdrawn_minor
        )

    def discrepancy(self) -> str:
        """Human-readable reconciliation gap, for the import report."""
        if self.reconciles is not False:
            return ""
        return (
            f"parsed in {self.parsed_paid_in_minor / 100:,.2f} "
            f"vs stated {self.declared_paid_in_minor / 100:,.2f}; "
            f"parsed out {self.parsed_withdrawn_minor / 100:,.2f} "
            f"vs stated {self.declared_withdrawn_minor / 100:,.2f}"
        )


_HEADER = [
    "Receipt No.",
    "Completion Time",
    "Details",
    "Transaction Status",
    "Paid In",
    "Withdrawn",
    "Balance",
]


def _to_minor(raw: str | None) -> int | None:
    """'-1,234.50' -> -123450. Decimal, not float: these are money."""
    if raw is None:
        return None
    s = raw.strip().replace(",", "").replace("KES", "").strip()
    if not s:
        return None
    try:
        return int((Decimal(s) * 100).to_integral_value())
    except Exception:  # noqa: BLE001 — a malformed cell is a skipped cell
        return None


def classify(details: str) -> tuple[MpesaKind, str]:
    """Work out what a row is, and who it involved."""
    text = " ".join((details or "").split())
    for pattern, kind, group in _RULES:
        match = pattern.match(text)
        if match is None:
            continue
        who = _clean_party(match.group(group)) if group else ""
        return kind, who
    return MpesaKind.OTHER, ""


#: Boilerplate Safaricom appends to bank-rail credits. Stripped so that the
#: same employer or bank resolves to one payee instead of one per reference.
_PARTY_NOISE = (
    re.compile(r"\s*Original conversation ID.*$", re.I),
    re.compile(r"\s+via\s+API\b.*$", re.I),
    re.compile(r"\s+to\s+Customer\b.*$", re.I),
)


def _clean_party(raw: str | None) -> str:
    who = " ".join((raw or "").split())
    for pattern in _PARTY_NOISE:
        who = pattern.sub("", who)
    return who.strip(" .-")


def parse_statement(file_bytes: bytes, password: str = "") -> ParsedStatement:
    """Read a Safaricom M-Pesa PDF statement.

    `password` is the one Safaricom sends with the statement. It is used to
    decrypt and then dropped — never stored, never logged.
    """
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise MpesaParseError("PDF support is not installed on the server (pdfplumber).") from exc

    import io

    try:
        pdf = pdfplumber.open(io.BytesIO(file_bytes), password=password or "")
    except Exception as exc:  # noqa: BLE001
        # pdfminer raises several different types for a bad password; they all
        # mean the same thing to the person who typed it.
        message = str(exc).lower()
        if "password" in message or "decrypt" in message:
            raise MpesaParseError(
                "Could not open the statement — check the password Safaricom sent with it."
            ) from exc
        raise MpesaParseError("That file does not look like a PDF statement.") from exc

    statement = ParsedStatement()
    with pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if not statement.customer_name:
                _read_summary(text, statement)

            for table in page.extract_tables():
                if not table:
                    continue
                header = [(c or "").strip() for c in table[0]]
                if header != _HEADER:
                    continue
                for raw in table[1:]:
                    row = _build_row(raw)
                    if row is not None:
                        statement.rows.append(row)

    if not statement.rows:
        raise MpesaParseError(
            "No transactions found. This may be a summary-only statement, or a "
            "format we do not recognise yet."
        )
    return statement


def _build_row(raw: list[str | None]) -> MpesaRow | None:
    if len(raw) < 7:
        return None
    receipt = (raw[0] or "").strip()
    if not receipt:
        return None

    when = (raw[1] or "").strip()
    try:
        completed_at = datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

    details = " ".join((raw[2] or "").split())
    status = (raw[3] or "").strip()

    # Exactly one of the two is populated, and each already carries its sign.
    amount = _to_minor(raw[4])
    if amount is None:
        amount = _to_minor(raw[5])
    if amount is None or amount == 0:
        return None

    kind, counterparty = classify(details)
    return MpesaRow(
        receipt=receipt,
        completed_at=completed_at,
        details=details,
        status=status,
        amount_minor=amount,
        balance_minor=_to_minor(raw[6]),
        kind=kind,
        counterparty=counterparty,
    )


_SUMMARY_PATTERNS = {
    "customer_name": re.compile(r"Customer Name:\s*(.+)"),
    "mobile_number": re.compile(r"Mobile Number:\s*(.+)"),
}


def _read_summary(text: str, statement: ParsedStatement) -> None:
    """Pull the identifying header and the declared totals off page one."""
    for attr, pattern in _SUMMARY_PATTERNS.items():
        match = pattern.search(text)
        if match:
            setattr(statement, attr, match.group(1).strip())

    period = re.search(r"Statement Period:\s*(.+?)\s*-\s*(.+)", text)
    if period:
        statement.period_start = period.group(1).strip()
        statement.period_end = period.group(2).strip()

    # "TOTAL: 1,067,014.04 1,065,064.30" — the figures that make the parse
    # checkable. Absent in some exports, hence the None-tolerant handling.
    total = re.search(r"TOTAL:\s*([\d,]+\.\d{2})\s+([\d,]+\.\d{2})", text)
    if total:
        statement.declared_paid_in_minor = _to_minor(total.group(1))
        statement.declared_withdrawn_minor = _to_minor(total.group(2))
