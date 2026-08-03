"""Financial milestones.

The properties worth pinning are the ones that keep this a record rather than a
rewards scheme: a milestone is dated to when it actually happened, it is never
awarded for an absence, and it is never invented from a series that does not go
back far enough to know.
"""

from __future__ import annotations

from datetime import date

from apps.intelligence.milestones import (
    debt_free_milestone,
    milestones,
    net_worth_milestones,
)


def _point(as_of: str, net: int, liabilities: int = 0) -> dict:
    return {"as_of": as_of, "net_minor": net, "liabilities_minor": liabilities}


def test_a_milestone_is_dated_to_the_first_crossing_not_the_latest():
    """Someone who passed 1,000, fell back and passed it again did that once,
    in the month it first happened. Reporting the later date would quietly
    rewrite their history to look better than it was."""
    history = [
        _point("2026-01-31", 50_000),
        _point("2026-02-28", 120_000),  # first crossing of 1,000
        _point("2026-03-31", 80_000),
        _point("2026-04-30", 150_000),
    ]
    [found] = [m for m in net_worth_milestones(history, "KES") if m.key == "net-worth-1000"]
    assert found.achieved_on == date(2026, 2, 28)


def test_a_threshold_already_passed_before_the_record_starts_is_not_dated():
    """The series cannot say when it was crossed, and dating it to the first
    month on record would be a fabricated anniversary."""
    history = [_point("2026-01-31", 500_000), _point("2026-02-28", 600_000)]
    keys = {m.key for m in net_worth_milestones(history, "KES")}
    assert "net-worth-1000" not in keys
    assert "net-worth-5000" not in keys


def test_nothing_is_claimed_from_a_single_data_point():
    assert net_worth_milestones([_point("2026-01-31", 900_000)], "KES") == []


def test_debt_free_requires_having_had_debt():
    """A user who has never borrowed has not achieved anything by not
    borrowing, and saying so would be the product congratulating itself."""
    never = [_point("2026-01-31", 10_000, liabilities=0), _point("2026-02-28", 20_000, liabilities=0)]
    assert debt_free_milestone(never, "KES") is None

    cleared = [
        _point("2026-01-31", 10_000, liabilities=40_000),
        _point("2026-02-28", 20_000, liabilities=0),
    ]
    found = debt_free_milestone(cleared, "KES")
    assert found is not None
    assert found.achieved_on == date(2026, 2, 28)


def test_the_feed_is_recent_first_and_capped():
    """The whole ladder at once is a trophy cabinet, which is the thing this
    module exists not to be."""
    history = [
        _point("2026-01-31", 0),
        _point("2026-02-28", 200_000),
        _point("2026-03-31", 1_200_000),
        _point("2026-04-30", 3_000_000),
        _point("2026-05-31", 6_000_000),
    ]
    found = milestones(history=history, currency="KES", limit=3)
    assert len(found) == 3
    assert found == sorted(found, key=lambda m: m.achieved_on, reverse=True)


def test_a_future_dated_point_is_never_reported_as_achieved():
    future = date.today().replace(year=date.today().year + 1).isoformat()
    history = [_point("2026-01-31", 0), _point(future, 9_000_000)]
    assert all(m.achieved_on <= date.today() for m in milestones(history=history, currency="KES"))
