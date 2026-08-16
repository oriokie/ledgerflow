"""Recurrence date math.

Occurrences are always computed as `starts_on + n periods` from the ORIGINAL
anchor, never by repeatedly incrementing the previous date. That preserves
the anchor day across month-length differences: a "31st of the month"
schedule starting Jan 31 yields Feb 28 (or 29), then Mar 31 — not Feb 28,
Mar 28, Apr 28, which is what incrementing month-by-month would drift into.
`relativedelta` does the month/year clamping correctly.
"""

from __future__ import annotations

from datetime import date, timedelta

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


def first_month_day_on_or_after(starts_on: date, *, day: int) -> date:
    """First `day`-of-month on or after `starts_on`.

    `day` is clamped to 28 so a "31st" payday does not silently skip February.
    """
    day = min(max(1, day), 28)
    candidate = date(starts_on.year, starts_on.month, day)
    if candidate < starts_on:
        candidate = candidate + relativedelta(months=1)
        candidate = date(candidate.year, candidate.month, day)
    return candidate


def add_period(anchor: date, frequency: str, interval: int = 1) -> date:
    """Advance `anchor` by one recurrence step. Used to spawn the next
    occurrence of a recurring bill from the one just paid. For an unbroken
    series, prefer `nth_occurrence` from the original anchor to avoid drift;
    single-step advance is correct here because each bill stores its own due
    date as the anchor for the next."""
    return anchor + _UNIT[frequency](interval)


#: Cadences that fire at most once per calendar month. Their amount is the
#: block that lands on the due date, not a monthly smear — quarterly school
#: fees, annual insurance, land rates. Daily / weekly / fortnightly still
#: convert to a run-rate because they hit more than once a month.
_PERIODICAL_UNITS = frozenset({"yearly", "annual", "quarterly"})
_RUN_RATE_PER_MONTH = {
    "daily": 30.0,
    "weekly": 52 / 12,
    "monthly": 1.0,
    "yearly": 1 / 12,
}
#: How far `iter_occurrences` will walk. Forty years of a daily schedule is
#: the projection ceiling; anything longer is a runaway loop, not a bill.
_MAX_OCCURRENCE_WALK = 480 * 31


def is_periodical(frequency: str, interval: int = 1) -> bool:
    """True when the schedule fires at most once in any calendar month."""
    freq = str(frequency).lower()
    n = max(1, int(interval or 1))
    if freq in _PERIODICAL_UNITS:
        return True
    return freq == "monthly" and n >= 2


def monthly_run_rate_minor(amount_minor: int, frequency: str, interval: int = 1) -> int:
    """Monthly equivalent for cadences that hit a month more than once.

    Periodical schedules must not go through here — they are recognized in
    the occurrence month at the full block amount.
    """
    per_month = _RUN_RATE_PER_MONTH.get(str(frequency).lower(), 1.0)
    return round(amount_minor * per_month / max(1, int(interval or 1)))


def iter_occurrences(
    *,
    anchor: date,
    frequency: str,
    interval: int = 1,
    start: date,
    end: date,
    ends_on: date | None = None,
    max_n: int | None = None,
):
    """Yield occurrence dates in `[start, end]`, inclusive, from `anchor`.

    `anchor` is the next due date (or the original `starts_on` when no run
    has happened yet). Walking `nth_occurrence` from that date, not from a
    rolling increment, keeps the day-of-month stable across short months.
    """
    if frequency not in _UNIT:
        return
    cap = _MAX_OCCURRENCE_WALK if max_n is None else min(max_n, _MAX_OCCURRENCE_WALK)
    step = max(1, int(interval or 1))
    for n in range(cap):
        occurs = nth_occurrence(starts_on=anchor, frequency=frequency, interval=step, n=n)
        if occurs > end:
            return
        if ends_on is not None and occurs > ends_on:
            return
        if occurs >= start:
            yield occurs


def amount_in_month(
    *,
    amount_minor: int,
    frequency: str,
    interval: int = 1,
    anchor: date,
    as_of: date,
    ends_on: date | None = None,
) -> int:
    """What this schedule contributes to the calendar month containing `as_of`.

    Periodical: the full block if an occurrence falls in that month, else 0.
    Otherwise: the monthly run-rate.
    """
    if amount_minor <= 0:
        return 0
    if not is_periodical(frequency, interval):
        return monthly_run_rate_minor(amount_minor, frequency, interval)
    month_start = as_of.replace(day=1)
    next_month = date(as_of.year + 1, 1, 1) if as_of.month == 12 else date(as_of.year, as_of.month + 1, 1)
    month_end = next_month - timedelta(days=1)
    for _ in iter_occurrences(
        anchor=anchor,
        frequency=frequency,
        interval=interval,
        start=month_start,
        end=month_end,
        ends_on=ends_on,
    ):
        return amount_minor
    return 0
