"""Assets read side — including what a thing was worth on a date nobody valued it.

The interpolation rule, stated once
-----------------------------------
Valuations are sparse. A house gets looked at every few years, and the net-worth
chart draws a point every month, so most months have no figure of their own.
Three cases, and the third is the one that matters:

* **Between two valuations** — interpolate linearly. A house valued at 6m in
  2022 and 8m in 2026 was, as far as anyone can honestly say, worth about 7m in
  2024. A step function would instead show four flat years and a 2m jump in a
  single month, which is a claim about *when* the value changed that nobody made.

* **Before the first valuation** — interpolate back to the purchase price if
  both it and an acquisition date are known; otherwise hold the first valuation
  flat. Before the acquisition date the asset is worth nothing, because it
  wasn't owned.

* **After the last valuation — hold flat. Never extrapolate.** This is the
  important one. Continuing the trend past the last real figure would invent
  growth nobody measured, and it would compound: a chart drawn today would show
  a different past than the same chart drawn next year. Flat is the only line
  that says "this is the last thing we actually know".

The same discipline the rest of the codebase applies to absent data — the health
score's None, the income module's speculative flag, the cash-flow calendar's
refusal to manufacture a dip.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Prefetch
from django.utils import timezone

from .models import Asset, Valuation


@dataclass(frozen=True, slots=True)
class AssetView:
    asset_id: str
    name: str
    kind: str
    currency: str
    description: str

    acquired_on: date | None
    acquisition_cost_minor: int | None

    #: The latest recorded figure, and when. Both None when nobody has ever
    #: valued it — never the purchase price standing in for a valuation.
    value_minor: int | None
    valued_on: date | None
    valuation_source: str | None
    valuation_count: int

    #: Owed against it, from the linked liability's real ledger balance.
    secured_debt_account_id: str | None
    secured_debt_name: str | None
    debt_minor: int

    include_in_net_worth: bool

    @property
    def equity_minor(self) -> int | None:
        """Worth less owed. None while unvalued — the whole point of the figure
        is the gap between two known numbers, and one of them is missing."""
        if self.value_minor is None:
            return None
        return self.value_minor - self.debt_minor

    @property
    def loan_to_value_pct(self) -> float | None:
        """What share of the asset the lender has a claim on.

        None without both a value and a debt: an asset owned outright has no
        ratio to report, and reporting 0% would be a different statement from
        "nothing is owed on this".
        """
        if not self.value_minor or self.debt_minor <= 0:
            return None
        return round(self.debt_minor / self.value_minor * 100, 1)

    @property
    def gain_minor(self) -> int | None:
        """Change since purchase. None unless both figures exist."""
        if self.value_minor is None or self.acquisition_cost_minor is None:
            return None
        return self.value_minor - self.acquisition_cost_minor


def value_at(asset: Asset, on: date, *, valuations: list[Valuation] | None = None) -> int:
    """What `asset` was worth on `on`, interpolating between known valuations.

    Zero before the acquisition date, because it wasn't owned. See the module
    docstring for the three cases and why the last one never extrapolates.

    `valuations` may be passed pre-fetched, so a caller walking twelve month
    boundaries does not issue twelve queries per asset.
    """
    if asset.acquired_on and on < asset.acquired_on:
        return 0

    points = valuations if valuations is not None else list(asset.valuations.all())
    points = sorted(points, key=lambda v: v.as_of)

    if not points:
        # No judgement has ever been made. The purchase price is a fact about
        # the past, not a claim about today, so it stands in only for dates at
        # or after acquisition and only because it is the one figure the owner
        # actually knows.
        if asset.acquisition_cost_minor is not None and asset.acquired_on:
            return asset.acquisition_cost_minor
        return 0

    first, last = points[0], points[-1]

    if on >= last.as_of:
        return last.value_minor  # flat. never extrapolated.

    if on <= first.as_of:
        # Interpolate back toward what it cost, when that is known.
        if asset.acquisition_cost_minor is not None and asset.acquired_on and asset.acquired_on < first.as_of:
            return _interpolate(
                on,
                (asset.acquired_on, asset.acquisition_cost_minor),
                (first.as_of, first.value_minor),
            )
        return first.value_minor

    # Between two known points.
    before = max((p for p in points if p.as_of <= on), key=lambda p: p.as_of)
    after = min((p for p in points if p.as_of > on), key=lambda p: p.as_of)
    return _interpolate(on, (before.as_of, before.value_minor), (after.as_of, after.value_minor))


def _interpolate(on: date, start: tuple[date, int], end: tuple[date, int]) -> int:
    """Straight line between two dated figures."""
    (start_on, start_value), (end_on, end_value) = start, end
    span = (end_on - start_on).days
    if span <= 0:
        return end_value
    elapsed = (on - start_on).days
    step = Decimal(end_value - start_value) * Decimal(elapsed) / Decimal(span)
    return int(Decimal(start_value) + step)


def _debt_balance_minor(account) -> int:
    """What is owed on the securing account, as a positive figure.

    Read from the materialized ledger balance, so the debt half of every equity
    figure traces to real postings even though the asset half does not.
    """
    from apps.ledger.models import AccountBalance

    if account is None:
        return 0
    balance = (
        AccountBalance.objects.filter(account_id=account.ledger_account_id)
        .values_list("balance_minor", flat=True)
        .first()
        or 0
    )
    return max(0, balance)


def asset_views(*, as_of: date | None = None) -> list[AssetView]:
    """Every asset, most valuable first."""
    as_of = as_of or timezone.localdate()
    rows = Asset.objects.select_related("secured_by_debt").prefetch_related(
        Prefetch("valuations", queryset=Valuation.objects.order_by("-as_of"))
    )

    views: list[AssetView] = []
    for asset in rows:
        points = list(asset.valuations.all())
        latest = points[0] if points else None
        debt_account = asset.secured_by_debt
        views.append(
            AssetView(
                asset_id=str(asset.id),
                name=asset.name,
                kind=asset.kind,
                currency=asset.currency,
                description=asset.description,
                acquired_on=asset.acquired_on,
                acquisition_cost_minor=asset.acquisition_cost_minor,
                value_minor=latest.value_minor if latest else None,
                valued_on=latest.as_of if latest else None,
                valuation_source=latest.source if latest else None,
                valuation_count=len(points),
                secured_debt_account_id=str(debt_account.id) if debt_account else None,
                secured_debt_name=debt_account.name if debt_account else None,
                debt_minor=_debt_balance_minor(debt_account),
                include_in_net_worth=asset.include_in_net_worth,
            )
        )
    views.sort(key=lambda v: (v.value_minor is None, -(v.value_minor or 0)))
    return views


@dataclass(frozen=True, slots=True)
class AssetSummary:
    currency: str
    value_minor: int
    debt_minor: int
    equity_minor: int
    count: int
    #: Assets nobody has ever valued. Reported rather than hidden: they are the
    #: reason the total is lower than the household expects.
    unvalued_count: int


def summary(*, as_of: date | None = None) -> AssetSummary | None:
    """Headline figures, or None when nothing has been recorded.

    None rather than zeroes, for the same reason the income and receivables
    endpoints answer 204: "you own nothing" and "you haven't told us about
    anything" are different statements.
    """
    views = [v for v in asset_views(as_of=as_of) if v.include_in_net_worth]
    if not views:
        return None

    counts: dict[str, int] = {}
    for v in views:
        counts[v.currency] = counts.get(v.currency, 0) + 1
    currency = max(counts.items(), key=lambda kv: kv[1])[0]
    scoped = [v for v in views if v.currency == currency]

    value = sum(v.value_minor or 0 for v in scoped)
    debt = sum(v.debt_minor for v in scoped)
    return AssetSummary(
        currency=currency,
        value_minor=value,
        debt_minor=debt,
        equity_minor=value - debt,
        count=len(scoped),
        unvalued_count=sum(1 for v in scoped if v.value_minor is None),
    )


def total_value_minor(*, currency: str, as_of: date | None = None) -> int:
    """What the household's assets are worth, for the net-worth overlay.

    Unvalued assets contribute nothing, so the overlay is conservative in the
    same way the investments one is: it never claims a value nobody supplied.
    """
    as_of = as_of or timezone.localdate()
    total = 0
    for asset in Asset.objects.filter(currency=currency, include_in_net_worth=True).prefetch_related(
        "valuations"
    ):
        if not asset.valuations.all() and asset.acquisition_cost_minor is None:
            continue
        total += value_at(asset, as_of, valuations=list(asset.valuations.all()))
    return total


def total_value_on(dates: list[date], *, currency: str) -> dict[date, int]:
    """Asset value at each of several dates, in one pass.

    For the net-worth history, which walks a year of month boundaries. Fetching
    each asset's valuations once and interpolating in Python keeps that a
    handful of queries rather than one per asset per boundary.
    """
    assets = list(
        Asset.objects.filter(currency=currency, include_in_net_worth=True).prefetch_related("valuations")
    )
    by_asset = {a.id: list(a.valuations.all()) for a in assets}

    out: dict[date, int] = {}
    for on in dates:
        total = 0
        for asset in assets:
            points = by_asset[asset.id]
            if not points and asset.acquisition_cost_minor is None:
                continue
            total += value_at(asset, on, valuations=points)
        out[on] = total
    return out
