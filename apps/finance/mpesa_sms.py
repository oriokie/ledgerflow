"""Read a Safaricom M-Pesa confirmation SMS.

Parsing only — no Django import, so the shapes are testable without a
database. `mpesa_sms_service.py` posts what this returns.

Why this exists next to the PDF importer
----------------------------------------
The statement is the monthly source of truth, but it arrives days or weeks
late. Between statements people live in the SMS: copy the confirmation, paste
it, move on. The receipt number in that message is the same identifier the
statement will print later, so a paste today can be recognised as already
entered when the PDF lands — instead of being typed by hand with no identity
the importer can match.

What a message actually looks like
----------------------------------
One line (or a few), always starting with a receipt and "Confirmed":

    UI94368KUX Confirmed. Ksh250.00 sent to JOHN  NDUNGU 0707750700
    on 9/9/26 at 3:29 PM. New M-PESA balance is Ksh0.00.
    Transaction cost, Ksh7.00.

The receipt is typically ten alphanumeric characters. The amount is the first
``Ksh`` figure that is not the running balance or the fee. Dates are D/M/YY
in East Africa; times are 12-hour. A transfer and its fee share a receipt but
never an amount, which is the identity the importer later uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .import_mpesa import MpesaKind


class MpesaSmsParseError(ValueError):
    """The text is not an M-Pesa confirmation we can read."""


@dataclass(frozen=True, slots=True)
class ParsedMpesaSms:
    receipt: str
    occurred_at: datetime
    #: Signed minor units. Negative is money out, matching the rest of the app.
    amount_minor: int
    counterparty: str
    kind: MpesaKind
    #: Positive minor units of the fee named in the same SMS, or 0.
    charge_minor: int
    balance_minor: int | None
    raw: str

    @property
    def is_inflow(self) -> bool:
        return self.amount_minor > 0


def sms_external_id(receipt: str, amount_minor: int) -> str:
    """Idempotency key for a pasted SMS, distinct from a statement row.

    Statement identity hashes the Details wording, which an SMS does not
    carry. Receipt plus signed amount is unique for one Safaricom event —
    a transfer and its charge share a receipt and nothing else.
    """
    return f"mpesa-sms:{receipt}:{amount_minor}"


_RECEIPT = re.compile(r"^\s*([A-Z0-9]{8,12})\s*Confirmed\.?", re.I)
_KSH = re.compile(r"(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)", re.I)
_COST = re.compile(r"Transaction cost[,:]?\s*(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)", re.I)
_BALANCE = re.compile(
    r"(?:New M-PESA balance is|Your new M-PESA balance is)\s*(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)",
    re.I,
)
_WHEN = re.compile(
    r"\bon\s+(\d{1,2}/\d{1,2}/\d{2,4})\s+at\s+(\d{1,2}:\d{2}\s*(?:AM|PM)?)\b",
    re.I,
)
_PHONE = re.compile(r"\b(?:\+?254|0)\d{8,9}\b")

#: First matching rule wins. More specific phrasing before the generic
#: "sent to", which also covers paybill.
_KIND_RULES: list[tuple[re.Pattern[str], MpesaKind, bool]] = [
    # (pattern, kind, is_inflow). Amount is group 1; counterparty is group 2
    # when present.
    (
        re.compile(
            r"(?:You have\s+)?received\s+(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)\s+from\s+(.+?)\s+on\s+",
            re.I,
        ),
        MpesaKind.RECEIVE,
        True,
    ),
    (
        re.compile(
            r"(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)\s+paid to\s+(.+?)(?:\s+on\s+|\.\s+on\s+)",
            re.I,
        ),
        MpesaKind.BUY_GOODS,
        False,
    ),
    (
        re.compile(
            r"(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)\s+sent to\s+(.+?)\s+on\s+",
            re.I,
        ),
        MpesaKind.SEND_MONEY,
        False,
    ),
    (
        re.compile(
            r"Withdraw(?:n)?\s+(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)\s+from\s+(.+?)(?:\s+New |\s+Transaction |\s*$)",
            re.I,
        ),
        MpesaKind.AGENT_WITHDRAWAL,
        False,
    ),
    (
        re.compile(
            r"bought\s+(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)\s+of airtime",
            re.I,
        ),
        MpesaKind.AIRTIME,
        False,
    ),
]


def parse_sms(text: str) -> ParsedMpesaSms:
    """Extract the receipt, amount, date and counterparty from a confirmation.

    Raises `MpesaSmsParseError` with a sentence a person can act on, not a
    regex failure.
    """
    raw = (text or "").strip()
    if not raw:
        raise MpesaSmsParseError("Paste the M-Pesa confirmation SMS first.")

    collapsed = " ".join(raw.split())
    receipt_match = _RECEIPT.match(collapsed)
    if receipt_match is None:
        raise MpesaSmsParseError(
            "That doesn't look like an M-Pesa confirmation. Copy the whole SMS, "
            "starting with the receipt code."
        )
    receipt = receipt_match.group(1).upper()

    kind, is_inflow, amount_raw, who_raw = _classify(collapsed)
    amount_minor = _to_minor(amount_raw)
    if amount_minor <= 0:
        raise MpesaSmsParseError("Couldn't read the amount in that message.")
    if not is_inflow:
        amount_minor = -amount_minor

    when = _parse_when(collapsed)
    charge_raw = _COST.search(collapsed)
    charge_minor = _to_minor(charge_raw.group(1)) if charge_raw else 0
    balance_raw = _BALANCE.search(collapsed)
    balance_minor = _to_minor(balance_raw.group(1)) if balance_raw else None

    if kind is MpesaKind.SEND_MONEY and re.search(r"\s+for account\s+", who_raw, re.I):
        kind = MpesaKind.PAYBILL
        who_raw = re.split(r"\s+for account\s+", who_raw, maxsplit=1, flags=re.I)[0]

    return ParsedMpesaSms(
        receipt=receipt,
        occurred_at=when,
        amount_minor=amount_minor,
        counterparty=_clean_party(who_raw),
        kind=kind,
        charge_minor=charge_minor,
        balance_minor=balance_minor,
        raw=raw,
    )


def _classify(text: str) -> tuple[MpesaKind, bool, str, str]:
    for pattern, kind, is_inflow in _KIND_RULES:
        match = pattern.search(text)
        if match is None:
            continue
        amount_raw = match.group(1)
        who_raw = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
        return kind, is_inflow, amount_raw, who_raw

    # Last resort: first Ksh that isn't the balance or the fee. Direction
    # unknown is treated as money out — a confirmation without a verb is
    # almost always a payment, and guessing income would inflate totals.
    skip_spans = [m.span() for m in (*_COST.finditer(text), *_BALANCE.finditer(text))]
    for match in _KSH.finditer(text):
        if any(start <= match.start() < end for start, end in skip_spans):
            continue
        return MpesaKind.OTHER, False, match.group(1), ""

    raise MpesaSmsParseError("Couldn't find an amount in that message.")


def _parse_when(text: str) -> datetime:
    match = _WHEN.search(text)
    if match is None:
        raise MpesaSmsParseError("Couldn't find the date in that message.")
    date_s, time_s = match.group(1), match.group(2)
    day, month, year = _dmy(date_s)
    hour, minute = _hm(time_s)
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError as exc:
        raise MpesaSmsParseError("The date in that message isn't one we can read.") from exc


def _dmy(raw: str) -> tuple[int, int, int]:
    """Kenya writes D/M/YY. Ambiguous dates (both parts ≤ 12) follow that."""
    a_s, b_s, y_s = raw.split("/")
    a, b, y = int(a_s), int(b_s), int(y_s)
    year = y if y >= 100 else 2000 + y
    if a > 12:
        return a, b, year
    if b > 12:
        return b, a, year
    return a, b, year


def _hm(raw: str) -> tuple[int, int]:
    cleaned = raw.strip().upper().replace(".", "")
    for fmt in ("%I:%M %p", "%H:%M"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.hour, parsed.minute
        except ValueError:
            continue
    raise MpesaSmsParseError("Couldn't read the time in that message.")


def _clean_party(raw: str) -> str:
    who = _PHONE.sub("", raw or "")
    who = re.sub(r"\s+", " ", who).strip(" .-")
    return who


def _to_minor(raw: str) -> int:
    s = raw.strip().replace(",", "")
    return int((Decimal(s) * 100).to_integral_value())
