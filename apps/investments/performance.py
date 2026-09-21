"""Portfolio performance — Modified Dietz, volatility, max drawdown.

Computed on read. Quotes in this product are typed in by hand, so a time-weighted
return at every cash-flow date would invent precision the prices do not have.
Modified Dietz is honest with sparse valuations: it weights each external flow
by how long it sat in the portfolio, and it says so when the quotes are too
irregular to trust the figure.

Nothing here is stored. A cached return is a return that silently goes stale
the moment someone records a trade or a price.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

from .models import InvestmentTransaction, InvestmentTransactionType, PriceQuote
from .selectors import portfolio_summary, valuation_history

#: A gap longer than this between quotes is "irregular" — the user is not
#: marking-to-market often enough for a monthly series to be a series.
IRREGULAR_GAP_DAYS = 45

#: External flows that change the capital in the portfolio. Dividends and
#: interest leave as income; they do not change units held, so they are not
#: capital flows for a holdings-value Dietz.
_CAPITAL_INFLOWS = {InvestmentTransactionType.BUY}
_CAPITAL_OUTFLOWS = {InvestmentTransactionType.SELL, InvestmentTransactionType.REDEMPTION}


@dataclass(frozen=True, slots=True)
class PortfolioPerformance:
    currency: str
    start: date
    end: date
    beginning_value_minor: int
    ending_value_minor: int
    net_flow_minor: int
    #: Holding-period Modified Dietz return, as a fraction. None when the
    #: denominator is zero — typically a window that starts empty.
    modified_dietz: float | None
    annualized_return: float | None
    #: Annualised standard deviation of month-end simple returns.
    volatility: float | None
    #: Peak-to-trough decline on the month-end series, as a negative fraction.
    max_drawdown: float | None
    months: int
    irregular_quotes: bool
    caveats: list[str] = field(default_factory=list)


def portfolio_performance(
    *, months: int = 12, as_of: date | None = None, currency: str | None = None
) -> PortfolioPerformance | None:
    """Modified Dietz plus vol and drawdown over the recent window.

    `None` when there are no holdings — the same absence the summary uses,
    rather than a zero return that would read as a wipeout.
    """
    as_of = as_of or timezone.localdate()
    summary = portfolio_summary(as_of=as_of, currency=currency)
    if summary is None:
        return None

    currency = summary.currency
    history = valuation_history(months=months, currency=currency)
    if len(history) < 2:
        return PortfolioPerformance(
            currency=currency,
            start=as_of,
            end=as_of,
            beginning_value_minor=summary.market_value_minor,
            ending_value_minor=summary.market_value_minor,
            net_flow_minor=0,
            modified_dietz=None,
            annualized_return=None,
            volatility=None,
            max_drawdown=None,
            months=len(history),
            irregular_quotes=True,
            caveats=["Fewer than two month-end valuations — a return needs a beginning and an end."],
        )

    start = history[0].as_of
    end = history[-1].as_of
    beginning = history[0].market_value_minor
    ending = history[-1].market_value_minor
    days = max(1, (end - start).days)

    flows = list(
        InvestmentTransaction.objects.filter(
            occurred_on__gt=start,
            occurred_on__lte=end,
            currency=currency,
            txn_type__in=_CAPITAL_INFLOWS | _CAPITAL_OUTFLOWS,
        )
    )
    weighted = 0.0
    net_flow = 0
    for txn in flows:
        signed = txn.amount_minor if txn.txn_type in _CAPITAL_INFLOWS else -txn.amount_minor
        net_flow += signed
        weight = (end - txn.occurred_on).days / days
        weighted += signed * weight

    denominator = beginning + weighted
    dietz = (ending - beginning - net_flow) / denominator if denominator else None

    annualized = None
    if dietz is not None and days > 0 and dietz > -0.999999:
        annualized = (1 + dietz) ** (365 / days) - 1

    monthly_returns: list[float] = []
    for prev, curr in zip(history, history[1:], strict=False):
        if prev.market_value_minor <= 0:
            continue
        monthly_returns.append(curr.market_value_minor / prev.market_value_minor - 1)

    volatility = None
    if len(monthly_returns) >= 2:
        mean = sum(monthly_returns) / len(monthly_returns)
        var = sum((r - mean) ** 2 for r in monthly_returns) / (len(monthly_returns) - 1)
        volatility = (var**0.5) * (12**0.5)

    peak = history[0].market_value_minor
    max_dd = 0.0
    for point in history:
        peak = max(peak, point.market_value_minor)
        if peak > 0:
            max_dd = min(max_dd, point.market_value_minor / peak - 1)

    quote_dates = list(
        PriceQuote.objects.filter(as_of__gte=start, as_of__lte=end)
        .values_list("as_of", flat=True)
        .distinct()
        .order_by("as_of")
    )
    irregular = False
    if len(quote_dates) < 2:
        irregular = True
    else:
        for earlier, later in zip(quote_dates, quote_dates[1:], strict=False):
            if (later - earlier).days > IRREGULAR_GAP_DAYS:
                irregular = True
                break
        if (quote_dates[0] - start).days > IRREGULAR_GAP_DAYS:
            irregular = True
        if (end - quote_dates[-1]).days > IRREGULAR_GAP_DAYS:
            irregular = True

    caveats: list[str] = []
    if irregular:
        caveats.append(
            "Quotes in this window are irregular, so the return is a Modified Dietz "
            "estimate rather than a true time-weighted figure."
        )
    caveats.append(
        "Modified Dietz weights cash flows by how long they sat in the portfolio. "
        "It is the honest figure when prices are entered by hand."
    )

    return PortfolioPerformance(
        currency=currency,
        start=start,
        end=end,
        beginning_value_minor=beginning,
        ending_value_minor=ending,
        net_flow_minor=net_flow,
        modified_dietz=round(dietz, 6) if dietz is not None else None,
        annualized_return=round(annualized, 6) if annualized is not None else None,
        volatility=round(volatility, 6) if volatility is not None else None,
        max_drawdown=round(max_dd, 6),
        months=len(history),
        irregular_quotes=irregular,
        caveats=caveats,
    )
