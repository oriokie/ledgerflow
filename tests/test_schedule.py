"""Occurrence-month recognition for periodical schedules.

A quarterly premium is the block that lands on the due date, not a third of
it smeared across three months. Daily and weekly still convert to a run-rate
because they hit a month more than once.
"""

from __future__ import annotations

from datetime import date

from apps.finance.schedule import amount_in_month, is_periodical, monthly_run_rate_minor


def test_quarterly_and_yearly_are_periodical():
    assert is_periodical("monthly", 3)
    assert is_periodical("monthly", 2)
    assert is_periodical("yearly", 1)
    assert is_periodical("annual", 1)
    assert is_periodical("quarterly", 1)
    assert not is_periodical("monthly", 1)
    assert not is_periodical("weekly", 1)
    assert not is_periodical("weekly", 2)


def test_periodical_amount_is_the_block_in_the_due_month_only():
    anchor = date(2026, 1, 15)
    assert (
        amount_in_month(
            amount_minor=30_000,
            frequency="monthly",
            interval=3,
            anchor=anchor,
            as_of=date(2026, 1, 20),
        )
        == 30_000
    )
    assert (
        amount_in_month(
            amount_minor=30_000,
            frequency="monthly",
            interval=3,
            anchor=anchor,
            as_of=date(2026, 2, 20),
        )
        == 0
    )
    assert (
        amount_in_month(
            amount_minor=30_000,
            frequency="monthly",
            interval=3,
            anchor=anchor,
            as_of=date(2026, 4, 1),
        )
        == 30_000
    )


def test_monthly_run_rate_is_unchanged_for_weekly_and_monthly():
    assert monthly_run_rate_minor(80_000, "monthly", 1) == 80_000
    assert monthly_run_rate_minor(3_000, "monthly", 3) == 1_000
    assert (
        amount_in_month(
            amount_minor=80_000,
            frequency="monthly",
            interval=1,
            anchor=date(2026, 1, 1),
            as_of=date(2026, 8, 13),
        )
        == 80_000
    )
