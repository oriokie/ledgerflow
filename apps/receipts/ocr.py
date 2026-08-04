"""OCR provider abstraction.

Same shape as the intelligence app's LLM seam: a `Protocol`, a settings-driven
registry, and a real default implementation rather than a placeholder. Adding a
cloud OCR vendor later — Textract, Google Vision, Azure Form Recognizer — is a
new class implementing `OCRProvider` and a settings change, not a rewrite of
this module or of `services.py`.

Two things every provider must return, and nothing more:

  * `raw_text` — what was literally read, for a human to fall back to when the
    structured guess is wrong;
  * `extraction` — a best-effort structured guess, with its own confidence.

Providers never touch the ORM and never decide what happens with their output;
`services.py` owns that, exactly as `automation_services.py` owns what happens
with a detector's findings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LineItemGuess:
    description: str
    amount_minor: int | None = None


@dataclass(frozen=True, slots=True)
class ReceiptExtraction:
    """A provider's best guess at the structured fields on a receipt.

    Every field is optional and independently confident-or-not; a receipt
    where the total is legible but the date is smudged should still return the
    total. Forcing an all-or-nothing extraction would throw away the part that
    worked.
    """

    merchant: str | None = None
    amount_minor: int | None = None
    occurred_on: date | None = None
    line_items: tuple[LineItemGuess, ...] = ()
    #: 0-1. The engine's own estimate of how much to trust this, distinct from
    #: whether individual fields are present at all.
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class OCRResult:
    raw_text: str
    extraction: ReceiptExtraction
    provider: str


@runtime_checkable
class OCRProvider(Protocol):
    """Reads an image and returns text plus a structured guess."""

    name: str

    def read(self, image_bytes: bytes, *, content_type: str) -> OCRResult: ...


# ---------------------------------------------------------------------------
# Field extraction from raw text — shared by any text-based provider
# ---------------------------------------------------------------------------

#: Lines mentioning these are almost always the grand total, not a subtotal or
#: a line item. Checked in order; the first match wins, so "total" alone is a
#: weaker signal than "grand total" and is tried last among the strong forms.
_TOTAL_MARKERS = ("grand total", "total due", "amount due", "balance due", "total")

_MONEY_RE = re.compile(r"(?<!\d)(\d{1,6}[.,]\d{2})(?!\d)")

_DATE_PATTERNS = (
    re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"),  # 2026-06-15
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b"),  # 06/15/2026 or 15/06/26
)


def _parse_money(text: str) -> int | None:
    match = _MONEY_RE.search(text)
    if not match:
        return None
    normalized = match.group(1).replace(",", ".")
    try:
        return round(float(normalized) * 100)
    except ValueError:
        return None


def _parse_date_token(text: str, *, today: date) -> date | None:
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groups()
        try:
            if len(groups[0]) == 4:
                year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
            else:
                month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
                if year < 100:
                    # Two-digit years on a receipt are always recent; anchoring
                    # to the current century is right for decades either way.
                    year += 2000 if year <= today.year % 100 + 1 else 1900
            candidate = date(year, month, day)
        except ValueError:
            continue
        # A receipt cannot be dated in the future, and one more than a few
        # years old is more likely a misread than a genuine old scan.
        if candidate <= today and (today.year - candidate.year) <= 5:
            return candidate
    return None


def extract_fields(raw_text: str, *, today: date | None = None) -> ReceiptExtraction:
    """Heuristic field extraction from OCR text.

    Deliberately simple pattern matching rather than a model: a receipt's
    layout is semi-structured enough that "the merchant is usually the first
    non-empty line, the total is the amount next to a total-like word" gets
    most of the way there, and a wrong heuristic is easier for a user to spot
    and correct than a wrong black-box prediction.
    """
    import datetime as _dt

    today = today or _dt.date.today()
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if not lines:
        return ReceiptExtraction(confidence=0.0)

    # Merchant: the first line that isn't purely numeric/punctuation — receipts
    # put the store name at the top, before any address or transaction detail.
    merchant = None
    for line in lines[:5]:
        if re.search(r"[a-zA-Z]{3,}", line) and not re.match(r"^[\d\s\-/:.,]+$", line):
            merchant = line.strip(" *#-")
            break

    # Amount: prefer a line carrying a total marker; fall back to the largest
    # money-shaped figure anywhere, since a total is nearly always the biggest
    # number on a receipt.
    amount = None
    for marker in _TOTAL_MARKERS:
        for line in lines:
            lowered = line.lower()
            if marker not in lowered:
                continue
            # "subtotal" contains "total" as a substring, and a subtotal is
            # exactly the figure a total-seeking match must not land on —
            # it's smaller than the real total by definition.
            if marker == "total" and "subtotal" in lowered:
                continue
            amount = _parse_money(line)
            if amount:
                break
        if amount:
            break
    if amount is None:
        candidates = [m for line in lines if (m := _parse_money(line)) is not None]
        amount = max(candidates) if candidates else None

    occurred_on = None
    for line in lines:
        occurred_on = _parse_date_token(line, today=today)
        if occurred_on:
            break

    # Confidence reflects how much was actually found, not a fixed constant —
    # a receipt that yielded nothing should never claim the same confidence as
    # one that yielded all three fields.
    found = sum(x is not None for x in (merchant, amount, occurred_on))
    confidence = round(found / 3, 2)

    return ReceiptExtraction(
        merchant=merchant,
        amount_minor=amount,
        occurred_on=occurred_on,
        confidence=confidence,
    )
