"""Recurrence date math.

Occurrences are always computed as `starts_on + n periods` from the ORIGINAL
anchor, never by repeatedly incrementing the previous date. That preserves
the anchor day across month-length differences: a "31st of the month"
schedule starting Jan 31 yields Feb 28 (or 29), then Mar 31 — not Feb 28,
Mar 28, Apr 28, which is what incrementing month-by-month would drift into.
`relativedelta` does the month/year clamping correctly.
"""

from __future__ import annotations

from datetime import date

from dateutil.relativedelta import relativedelta

from .models import Frequency

_UNIT = {
    Frequency.DAILY: lambda n: relativedelta(days=n),
    Frequency.WEEKLY: lambda n: relativedelta(weeks=n),
    Frequency.MONTHLY: lambda n: relativedelta(months=n),
    Frequency.YEARLY: lambda n: relativedelta(years=n),
}


def nth_occurrence(*, starts_on: date, frequency: str, interval: int, n: int) -> date:
    """Date of the n-th occurrence (0-indexed: n=0 is `starts_on`)."""
    return starts_on + _UNIT[frequency](interval * n)


def add_period(anchor: date, frequency: str, interval: int = 1) -> date:
    """Advance `anchor` by one recurrence step. Used to spawn the next
    occurrence of a recurring bill from the one just paid. For an unbroken
    series, prefer `nth_occurrence` from the original anchor to avoid drift;
    single-step advance is correct here because each bill stores its own due
    date as the anchor for the next."""
    return anchor + _UNIT[frequency](interval)
