"""Investment read side — market value, allocation, performance.

Everything here is derived. Nothing in this module writes, and nothing it
computes is stored, for the reason set out in `models.py`: market value is an
observation that changes continuously and that the user has not realised.

The distinction that runs through all of it:

    cost basis        what you paid       — from the ledger, always exact
    market value      what it's worth     — from the latest quote, always an estimate
    unrealised gain   the difference      — reported, never posted
    realised gain     booked on disposal  — real income, in the ledger

A portfolio view that blurs those four is how people end up believing they have
money they haven't made.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.finance.models import AccountType

from .models import AssetClass, Holding, InvestmentTransaction, InvestmentTransactionType, Lot, PriceQuote

#: Account types whose holdings count as investments.
INVESTMENT_ACCOUNT_TYPES = {AccountType.INVESTMENT}


def latest_price(security_id: str, *, as_of: date | None = None) -> tuple[int, date] | None:
    """Most recent quote at or before `as_of`, **with the date it was taken**.

    The date is not decoration. Quotes in this product are entered by hand —
    there is an "Update prices" button, not a market feed — so a portfolio's
    "market value" is only ever as current as the last time someone typed a
    number in. Returning the price alone let the UI present a six-month-old
    quote as what a holding is worth today, which is the one thing a valuation
    must never do.

    `None` when the security has never been priced — distinct from a price of
    zero, which would be a claim that the holding is worthless. Callers surface
    the absence rather than valuing the position at nothing.
    """
    quote = (
        PriceQuote.objects.filter(security_id=security_id)
        .filter(as_of__lte=as_of or timezone.localdate())
        .order_by("-as_of")
        .values_list("price_minor", "as_of")
        .first()
    )
    return quote


def latest_price_minor(security_id: str, *, as_of: date | None = None) -> int | None:
    """Just the price. Prefer `latest_price` anywhere the age can matter."""
    quote = latest_price(security_id, as_of=as_of)
    return quote[0] if quote else None


def holding_cost_basis_minor(holding: Holding) -> int:
    """Sum of what remains attributable to open lots.

    Computed rather than stored: the holding's cost basis *is* the sum of its
    lots, and a cached copy would be a second source of truth for the number
    every gain calculation depends on.
    """
    total = 0
    for lot in Lot.objects.filter(holding=holding, quantity_remaining__gt=0):
        total += lot.cost_remaining_minor
    return total


@dataclass(frozen=True, slots=True)
class HoldingValuation:
    holding_id: str
    account_id: str
    account_name: str
    security_id: str
    symbol: str
    security_name: str
    asset_class: str
    sector: str
    currency: str
    quantity: Decimal
    cost_basis_minor: int
    #: `None` when the security has no quote — the UI must show "not priced"
    #: rather than a zero that looks like a wipeout.
    price_minor: int | None
    #: The date that price was taken. Quotes are entered by hand, so this is
    #: how fresh the valuation actually is — `None` alongside `price_minor`.
    priced_as_of: date | None
    market_value_minor: int | None
    unrealized_gain_minor: int | None

    @property
    def unrealized_gain_pct(self) -> float | None:
        if self.unrealized_gain_minor is None or self.cost_basis_minor <= 0:
            return None
        return round(self.unrealized_gain_minor / self.cost_basis_minor * 100, 2)

    @property
    def is_priced(self) -> bool:
        return self.price_minor is not None


def holding_valuations(*, as_of: date | None = None) -> list[HoldingValuation]:
    """Every open position, valued at the latest available price."""
    as_of = as_of or timezone.localdate()
    holdings = (
        Holding.objects.filter(quantity__gt=0)
        .select_related("security", "financial_account")
        .order_by("security__symbol")
    )

    out: list[HoldingValuation] = []
    for holding in holdings:
        cost = holding_cost_basis_minor(holding)
        quote = latest_price(str(holding.security_id), as_of=as_of)
        price, priced_on = quote if quote else (None, None)
        market = int(Decimal(price) * holding.quantity) if price is not None else None
        out.append(
            HoldingValuation(
                holding_id=str(holding.id),
                account_id=str(holding.financial_account_id),
                account_name=holding.financial_account.name,
                security_id=str(holding.security_id),
                symbol=holding.security.symbol,
                security_name=holding.security.name,
                asset_class=holding.security.asset_class,
                sector=holding.security.sector or "Unclassified",
                currency=holding.security.currency,
                quantity=holding.quantity,
                cost_basis_minor=cost,
                price_minor=price,
                priced_as_of=priced_on,
                market_value_minor=market,
                unrealized_gain_minor=(market - cost) if market is not None else None,
            )
        )
    return out


@dataclass(frozen=True, slots=True)
class AllocationSlice:
    label: str
    market_value_minor: int
    percent: float


def _allocate(valuations: list[HoldingValuation], key) -> list[AllocationSlice]:
    """Group priced holdings by a key and convert to percentages.

    Unpriced holdings are excluded entirely rather than counted as zero. A
    position with no quote has an unknown weight, and treating it as 0% would
    silently inflate every other slice — the pie would still sum to 100% and
    still be wrong.
    """
    priced = [v for v in valuations if v.market_value_minor is not None]
    total = sum(v.market_value_minor for v in priced)
    if total <= 0:
        return []

    buckets: dict[str, int] = {}
    for v in priced:
        buckets[key(v)] = buckets.get(key(v), 0) + v.market_value_minor

    return [
        AllocationSlice(
            label=label,
            market_value_minor=value,
            percent=round(value / total * 100, 2),
        )
        for label, value in sorted(buckets.items(), key=lambda kv: -kv[1])
    ]


def asset_allocation(*, as_of: date | None = None) -> list[AllocationSlice]:
    labels = dict(AssetClass.choices)
    return _allocate(holding_valuations(as_of=as_of), lambda v: labels.get(v.asset_class, v.asset_class))


def sector_allocation(*, as_of: date | None = None) -> list[AllocationSlice]:
    return _allocate(holding_valuations(as_of=as_of), lambda v: v.sector)


def account_allocation(*, as_of: date | None = None) -> list[AllocationSlice]:
    return _allocate(holding_valuations(as_of=as_of), lambda v: v.account_name)


@dataclass(frozen=True, slots=True)
class PortfolioSummary:
    currency: str
    cost_basis_minor: int
    market_value_minor: int
    unrealized_gain_minor: int
    realized_gain_minor: int
    dividend_income_minor: int
    holding_count: int
    #: Positions with no quote. Reported so the UI can say the total is partial
    #: rather than presenting it as complete.
    unpriced_count: int
    #: Date of the *oldest* quote behind this total. A sum is only as current
    #: as its stalest input, so reporting the newest would flatter it: one
    #: symbol updated this morning would present a portfolio last valued in
    #: March as today's worth. `None` when nothing is priced.
    priced_as_of: date | None = None
    #: Holdings whose quote predates `as_of` — priced, but not priced today.
    stale_count: int = 0

    @property
    def unrealized_gain_pct(self) -> float:
        if self.cost_basis_minor <= 0:
            return 0.0
        return round(self.unrealized_gain_minor / self.cost_basis_minor * 100, 2)

    @property
    def total_return_minor(self) -> int:
        """Everything the portfolio has produced: paper gains, booked gains,
        and income. The figure most people mean by "how am I doing"."""
        return self.unrealized_gain_minor + self.realized_gain_minor + self.dividend_income_minor


def portfolio_summary(*, as_of: date | None = None, currency: str | None = None) -> PortfolioSummary | None:
    """Headline portfolio figures.

    `None` when there are no holdings — an all-zero summary would look like a
    portfolio that lost everything rather than one that doesn't exist.

    Single-currency, matching net worth and the cash-flow statement: summing a
    dollar position and a euro position without a rate is a correctness bug.
    """
    valuations = holding_valuations(as_of=as_of)
    if not valuations:
        return None

    if currency is None:
        # The currency holding the most positions, so a token foreign holding
        # doesn't decide the report's denomination.
        counts: dict[str, int] = {}
        for v in valuations:
            counts[v.currency] = counts.get(v.currency, 0) + 1
        currency = max(counts.items(), key=lambda kv: kv[1])[0]

    scoped = [v for v in valuations if v.currency == currency]
    priced = [v for v in scoped if v.market_value_minor is not None]

    realized = (
        InvestmentTransaction.objects.filter(
            txn_type=InvestmentTransactionType.SELL, currency=currency
        ).aggregate(total=Sum("realized_gain_minor"))["total"]
        or 0
    )
    dividends = (
        InvestmentTransaction.objects.filter(
            txn_type=InvestmentTransactionType.DIVIDEND, currency=currency
        ).aggregate(total=Sum("amount_minor"))["total"]
        or 0
    )

    cost = sum(v.cost_basis_minor for v in priced)
    market = sum(v.market_value_minor for v in priced)
    quote_dates = [v.priced_as_of for v in priced if v.priced_as_of is not None]
    today = as_of or timezone.localdate()

    return PortfolioSummary(
        currency=currency,
        cost_basis_minor=cost,
        market_value_minor=market,
        unrealized_gain_minor=market - cost,
        realized_gain_minor=realized,
        dividend_income_minor=dividends,
        holding_count=len(scoped),
        unpriced_count=len(scoped) - len(priced),
        priced_as_of=min(quote_dates) if quote_dates else None,
        stale_count=sum(1 for d in quote_dates if d < today),
    )


@dataclass(frozen=True, slots=True)
class ValuationPoint:
    as_of: date
    market_value_minor: int
    cost_basis_minor: int

    @property
    def unrealized_gain_minor(self) -> int:
        return self.market_value_minor - self.cost_basis_minor


def valuation_history(*, months: int = 12, currency: str | None = None) -> list[ValuationPoint]:
    """Month-end portfolio value over time, for the performance chart.

    Each point values the positions **held at that date** using the best price
    known at that date. It does not apply today's prices to past holdings, which
    would draw a chart of a portfolio nobody owned.

    Months before any quote exists are omitted rather than plotted at zero — a
    line dropping to the axis reads as a loss, not as missing data.
    """
    today = timezone.localdate()
    points: list[ValuationPoint] = []

    for offset in range(months - 1, -1, -1):
        # Last day of the month, `offset` months back.
        anchor = today.replace(day=1)
        for _ in range(offset):
            anchor = (anchor - timedelta(days=1)).replace(day=1)
        month_end = min(
            (anchor.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1), today
        )

        market = 0
        cost = 0
        priced_any = False
        for holding in Holding.objects.select_related("security").all():
            if currency and holding.security.currency != currency:
                continue
            qty = _quantity_at(holding, month_end)
            if qty <= 0:
                continue
            price = latest_price_minor(str(holding.security_id), as_of=month_end)
            if price is None:
                continue
            priced_any = True
            market += int(Decimal(price) * qty)
            cost += _cost_at(holding, month_end)

        if priced_any:
            points.append(ValuationPoint(as_of=month_end, market_value_minor=market, cost_basis_minor=cost))
    return points


def _quantity_at(holding: Holding, as_of: date) -> Decimal:
    """Units held on a date, replayed from the transaction log.

    Replaying rather than storing a snapshot per day: the log is the source of
    truth, and a daily snapshot table would be a large amount of storage
    duplicating something already derivable.
    """
    quantity = Decimal("0")
    for txn in InvestmentTransaction.objects.filter(holding=holding, occurred_on__lte=as_of).order_by(
        "occurred_on", "id"
    ):
        if txn.txn_type == InvestmentTransactionType.BUY:
            quantity += txn.quantity
        elif txn.txn_type == InvestmentTransactionType.SELL:
            quantity -= txn.quantity
        elif txn.txn_type == InvestmentTransactionType.SPLIT:
            quantity += txn.quantity
    return quantity


def _cost_at(holding: Holding, as_of: date) -> int:
    """Cost basis of the position as it stood on a given date.

    Replays the transaction log rather than reading each lot's *current*
    remaining quantity. The difference matters: a lot bought in January and sold
    in June has zero remaining today, so reading current state would report the
    January position as having cost nothing — the cost line on a performance
    chart would sag toward zero in exactly the months a user was invested.

    Disposals are applied FIFO, matching how they were actually consumed, so the
    replayed figure agrees with what the sale booked at the time.
    """
    # Lots as they were created, oldest first — the FIFO order disposals used.
    lots = [
        {"acquired_on": lot.acquired_on, "quantity": lot.quantity, "cost": Decimal(lot.cost_minor)}
        for lot in Lot.objects.filter(holding=holding, acquired_on__lte=as_of).order_by("acquired_on", "id")
    ]
    if not lots:
        return 0

    # Replay disposals that had happened by `as_of`, consuming oldest first.
    sold = Decimal("0")
    for txn in InvestmentTransaction.objects.filter(
        holding=holding, occurred_on__lte=as_of, txn_type=InvestmentTransactionType.SELL
    ):
        sold += txn.quantity

    total = Decimal("0")
    for lot in lots:
        if sold <= 0:
            total += lot["cost"]
            continue
        consumed = min(sold, lot["quantity"])
        sold -= consumed
        remaining = lot["quantity"] - consumed
        if remaining > 0 and lot["quantity"] > 0:
            total += lot["cost"] * remaining / lot["quantity"]
    return int(total)


@dataclass(frozen=True, slots=True)
class DividendSummary:
    currency: str
    total_minor: int
    by_security: list[dict] = field(default_factory=list)


def dividend_income(*, months: int = 12, currency: str | None = None) -> DividendSummary | None:
    """Dividend income received, in total and per security."""
    since = timezone.localdate() - timedelta(days=months * 31)
    qs = InvestmentTransaction.objects.filter(
        txn_type=InvestmentTransactionType.DIVIDEND, occurred_on__gte=since
    ).select_related("holding__security")
    if currency:
        qs = qs.filter(currency=currency)

    rows = list(qs)
    if not rows:
        return None

    resolved = currency or rows[0].currency
    by_security: dict[str, dict] = {}
    total = 0
    for txn in rows:
        if txn.currency != resolved:
            continue
        symbol = txn.holding.security.symbol
        bucket = by_security.setdefault(symbol, {"symbol": symbol, "amount_minor": 0})
        bucket["amount_minor"] += txn.amount_minor
        total += txn.amount_minor

    return DividendSummary(
        currency=resolved,
        total_minor=total,
        by_security=sorted(by_security.values(), key=lambda b: -b["amount_minor"]),
    )


def unrealized_gain_for_net_worth(*, currency: str) -> int:
    """The adjustment net worth needs to move from book value to market value.

    The ledger carries investments at cost, so a net-worth figure read straight
    from balances understates a portfolio that has grown. This returns the
    difference, letting the net-worth view present a market-value total while
    the ledger stays internally consistent and free of unposted gains.

    Unpriced holdings contribute nothing, so the adjustment is conservative: it
    never claims a gain on a position nobody has valued.
    """
    total = 0
    for valuation in holding_valuations():
        if valuation.currency != currency or valuation.unrealized_gain_minor is None:
            continue
        total += valuation.unrealized_gain_minor
    return total
