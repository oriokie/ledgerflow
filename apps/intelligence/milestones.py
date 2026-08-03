"""Financial milestones — things that have already happened.

The roadmap is explicit that this is the *only* engagement mechanic worth
having here, and that badges, streaks and social comparison are not: they are
borrowed from products whose users are not looking at their debt. The
distinction this module holds to is what keeps it on the right side of that
line:

**A milestone is a dated fact, reconstructed from the ledger.** "You passed
KES 50,000 for the first time, in March." It is not a reward the product hands
out, it cannot be lost, there is no next tier to chase, and nothing here
congratulates anyone for logging in. If the ledger says it happened, it
happened; if it does not, the milestone is simply absent.

That also means every milestone must be *derivable*. Nothing is stored, for the
same reason payoff plans and cash-flow calendars are not: a stored milestone is
one that survives the transaction being deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.utils import timezone

#: Round numbers people actually notice, in major units.
#:
#: Deliberately not currency-adjusted. A "first 100,000" means something
#: different in KES than in USD, and inventing a conversion would be a claim
#: about purchasing power this product has no basis for. The ladder is the
#: user's own currency, and the figure speaks for itself.
THRESHOLDS_MAJOR = (1_000, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000)


@dataclass(frozen=True, slots=True)
class Milestone:
    key: str
    title: str
    #: What actually happened, in the user's words.
    detail: str
    achieved_on: date
    #: Present for figures; absent for milestones that are not an amount.
    amount_minor: int | None = None
    currency: str = ""


def net_worth_milestones(history: list[dict], currency: str) -> list[Milestone]:
    """First crossing of each round number, from a net-worth series.

    *First* crossing, not most recent: someone who passed 50,000, dropped back
    and passed it again did that once, in the month it first happened. Reporting
    the later date would quietly rewrite their history to look better.

    A threshold already exceeded at the start of the series is skipped — the
    series does not go back far enough to know when it was crossed, and dating
    it to the first month on record would be a fabricated anniversary.
    """
    points = sorted(
        (p for p in history if p.get("as_of") and p.get("net_minor") is not None),
        key=lambda p: p["as_of"],
    )
    if len(points) < 2:
        return []

    out: list[Milestone] = []
    opening = points[0]["net_minor"]

    for threshold in THRESHOLDS_MAJOR:
        minor = threshold * 100
        if opening >= minor:
            continue  # already past it before the record starts
        crossing = next((p for p in points if p["net_minor"] >= minor), None)
        if crossing is None:
            continue
        out.append(
            Milestone(
                key=f"net-worth-{threshold}",
                title=f"Passed {threshold:,} for the first time",
                detail="Everything you own, minus everything you owe.",
                achieved_on=date.fromisoformat(crossing["as_of"]),
                amount_minor=minor,
                currency=currency,
            )
        )
    return out


def debt_free_milestone(history: list[dict], currency: str) -> Milestone | None:
    """The month liabilities first reached zero, having previously not been.

    Requires a prior month with debt: a user who has never borrowed has not
    achieved anything by not borrowing, and telling them they are "debt free"
    would be the product congratulating itself.
    """
    points = sorted(
        (p for p in history if p.get("as_of") and p.get("liabilities_minor") is not None),
        key=lambda p: p["as_of"],
    )
    had_debt = False
    for point in points:
        owed = point["liabilities_minor"]
        if owed > 0:
            had_debt = True
            continue
        if had_debt and owed <= 0:
            return Milestone(
                key="debt-free",
                title="Cleared the last of your debt",
                detail="Nothing owed across your credit cards and loans.",
                achieved_on=date.fromisoformat(point["as_of"]),
                currency=currency,
            )
    return None


def milestones(*, history: list[dict], currency: str, limit: int = 3) -> list[Milestone]:
    """The most recent achievements, newest first.

    Capped, and capped low. The whole ladder at once is a trophy cabinet, which
    is the thing this module exists not to be.
    """
    found = net_worth_milestones(history, currency)
    debt_free = debt_free_milestone(history, currency)
    if debt_free is not None:
        found.append(debt_free)

    today = timezone.localdate()
    found = [m for m in found if m.achieved_on <= today]
    found.sort(key=lambda m: m.achieved_on, reverse=True)
    return found[:limit]
