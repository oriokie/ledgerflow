"""One filter contract, shared by every report.

Fourteen reports with fourteen filter shapes is fourteen things to learn and
fourteen places for a currency to be handled differently. A single value object
means a filter bar built once works everywhere, and a report added next year
inherits filtering rather than reimplementing it.

The object is frozen and hashable on purpose: it forms part of the cache key,
so two identical requests cannot produce two cache entries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.utils import timezone


class Period:
    """Named windows, resolved against a reference date.

    Named rather than raw dates because "this year" means something different
    tomorrow, and a cached "2026-01-01 to 2026-12-31" would silently answer a
    question nobody asked once the year turned.
    """

    LAST_30 = "last_30_days"
    LAST_90 = "last_90_days"
    LAST_12_MONTHS = "last_12_months"
    THIS_MONTH = "this_month"
    LAST_MONTH = "last_month"
    THIS_YEAR = "this_year"
    LAST_YEAR = "last_year"
    ALL_TIME = "all_time"
    CUSTOM = "custom"

    ALL = (
        LAST_30,
        LAST_90,
        LAST_12_MONTHS,
        THIS_MONTH,
        LAST_MONTH,
        THIS_YEAR,
        LAST_YEAR,
        ALL_TIME,
        CUSTOM,
    )


#: How far back "all time" actually reaches. Unbounded would mean scanning
#: every row a workspace has ever had for a chart nobody reads that far into.
ALL_TIME_YEARS = 10


def resolve_period(period: str, *, as_of: date | None = None) -> tuple[date, date]:
    """Turn a named period into a concrete window, inclusive of both ends."""
    today = as_of or timezone.localdate()

    if period == Period.LAST_30:
        return today - timedelta(days=29), today
    if period == Period.LAST_90:
        return today - timedelta(days=89), today
    if period == Period.LAST_12_MONTHS:
        start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        for _ in range(11):
            start = (start - timedelta(days=1)).replace(day=1)
        return start, today
    if period == Period.THIS_MONTH:
        return today.replace(day=1), today
    if period == Period.LAST_MONTH:
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if period == Period.THIS_YEAR:
        return today.replace(month=1, day=1), today
    if period == Period.LAST_YEAR:
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if period == Period.ALL_TIME:
        return date(today.year - ALL_TIME_YEARS, 1, 1), today

    raise ValueError(f"Unknown period {period!r}.")


@dataclass(frozen=True, slots=True)
class ReportFilters:
    """Everything a report can be narrowed by.

    Frozen and hashable so it can key a cache entry directly.
    """

    period: str = Period.LAST_12_MONTHS
    #: Only used when `period` is CUSTOM.
    start: date | None = None
    end: date | None = None
    #: Empty means every account; otherwise only these.
    account_ids: tuple[str, ...] = ()
    category_ids: tuple[str, ...] = ()
    #: `None` means "the workspace's dominant currency", resolved per report.
    currency: str | None = None
    #: Compare against the equivalent earlier window. Off by default because
    #: it doubles the query cost and most views don't show it.
    compare_previous: bool = False

    def window(self, *, as_of: date | None = None) -> tuple[date, date]:
        if self.period == Period.CUSTOM:
            if self.start is None or self.end is None:
                raise ValueError("A custom period needs both a start and an end.")
            if self.end < self.start:
                raise ValueError("A period cannot end before it starts.")
            return self.start, self.end
        return resolve_period(self.period, as_of=as_of)

    def previous_window(self, *, as_of: date | None = None) -> tuple[date, date]:
        """The comparable earlier window.

        Shifted by the window's own length rather than a fixed month, so a
        90-day view compares against the preceding 90 days and a yearly view
        against the preceding year. Comparing unequal spans is the most common
        way a "vs last period" figure ends up meaningless.
        """
        start, end = self.window(as_of=as_of)
        span = (end - start).days + 1
        return start - timedelta(days=span), start - timedelta(days=1)

    def cache_key_part(self) -> str:
        """Stable fragment identifying this filter set."""
        return "|".join(
            [
                self.period,
                self.start.isoformat() if self.start else "-",
                self.end.isoformat() if self.end else "-",
                ",".join(sorted(self.account_ids)) or "-",
                ",".join(sorted(self.category_ids)) or "-",
                self.currency or "-",
                "cmp" if self.compare_previous else "-",
            ]
        )
