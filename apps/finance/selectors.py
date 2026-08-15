"""Finance read side — financial calculations as optimized queries.

Every function here is a pure read: it aggregates in the database (never a
per-row Python loop over the whole table) and returns plain dataclasses/dicts.
Balances come from the materialized `AccountBalance`, so net worth is O(number
of accounts), not O(number of transactions).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db.models import F, Q, Sum, Value, Window
from django.db.models.functions import Abs, Coalesce
from django.utils import timezone

from apps.ledger.models import AccountBalance, AccountKind

from .models import AccountType, FinancialAccount, Transaction, TransactionStatus
from .services import _ASSET_TYPES

# transactions that actually count toward reported figures
_COUNTED = Q(status__in=[TransactionStatus.POSTED, TransactionStatus.RECONCILED])
_NOT_TRANSFER = Q(transfer_group__isnull=True)


def _kind_sign(financial_account: FinancialAccount) -> int:
    """+1 if the account's real balance moves with the user's cash-flow sign
    (assets), -1 for liabilities (a purchase is cash-negative but grows the
    balance owed)."""
    return 1 if financial_account.account_type in _ASSET_TYPES else -1


@dataclass(frozen=True, slots=True)
class NetWorth:
    currency: str
    assets_minor: int
    liabilities_minor: int

    @property
    def net_minor(self) -> int:
        return self.assets_minor - self.liabilities_minor


def net_worth() -> list[NetWorth]:
    """Per-currency assets, liabilities, and net. Reads materialized balances
    only. Cross-currency consolidation is intentionally left to an FX layer —
    silently summing mixed currencies would be a correctness bug, not a
    feature.

    Excluded from the roll-up:
      * accounts the user marked `include_in_net_worth=False` (a business
        account in a personal workspace, money held for someone else);
      * archived accounts, which are closed and no longer part of the position;
      * EQUITY accounts such as opening-balance equity — including them would
        double-count, since equity is the *counterparty* to the assets it
        funded, not a second asset.

    Every excluded balance still exists in the ledger and still appears in
    history. Exclusion is a reporting choice, never an accounting one.
    """
    excluded_ledger_ids = FinancialAccount.objects.filter(
        Q(include_in_net_worth=False) | Q(archived_at__isnull=False)
    ).values_list("ledger_account_id", flat=True)

    rows = (
        AccountBalance.objects.filter(account__kind__in=[AccountKind.ASSET, AccountKind.LIABILITY])
        .exclude(account_id__in=excluded_ledger_ids)
        .values("currency", "account__kind")
        .annotate(total=Sum("balance_minor"))
    )
    by_currency: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = by_currency.setdefault(row["currency"], {"asset": 0, "liability": 0})
        bucket[row["account__kind"]] = row["total"] or 0
    return [
        NetWorth(currency=cur, assets_minor=v["asset"], liabilities_minor=v["liability"])
        for cur, v in sorted(by_currency.items())
    ]


@dataclass(frozen=True, slots=True)
class CashFlow:
    currency: str
    income_minor: int
    expense_minor: int

    @property
    def net_minor(self) -> int:
        return self.income_minor - self.expense_minor


def cash_flow(*, start: datetime, end: datetime) -> list[CashFlow]:
    """Income vs expense over [start, end), per currency. Transfers are
    excluded — moving your own money between accounts is neither."""
    rows = (
        Transaction.objects.filter(_COUNTED, _NOT_TRANSFER, occurred_at__gte=start, occurred_at__lt=end)
        .values("currency")
        .annotate(
            income=Coalesce(Sum("amount_minor", filter=Q(amount_minor__gt=0)), Value(0)),
            expense=Coalesce(Sum("amount_minor", filter=Q(amount_minor__lt=0)), Value(0)),
        )
    )
    return [
        CashFlow(currency=r["currency"], income_minor=r["income"], expense_minor=-r["expense"])
        for r in sorted(rows, key=lambda r: r["currency"])
    ]


@dataclass(frozen=True, slots=True)
class CategorySpend:
    category_id: str
    category_name: str
    amount_minor: int  # positive magnitude


def category_breakdown(*, start: datetime, end: datetime, expense: bool = True) -> list[CategorySpend]:
    """Spending (or income) grouped by category over [start, end), transfers
    excluded, biggest first. One grouped query, no N+1."""
    amount_filter = Q(amount_minor__lt=0) if expense else Q(amount_minor__gt=0)
    rows = (
        Transaction.objects.filter(
            _COUNTED,
            _NOT_TRANSFER,
            amount_filter,
            category__isnull=False,
            occurred_at__gte=start,
            occurred_at__lt=end,
        )
        .values("category_id", "category__name")
        .annotate(total=Sum("amount_minor"))
    )
    out = [
        CategorySpend(
            category_id=str(r["category_id"]),
            category_name=r["category__name"],
            amount_minor=abs(r["total"]),
        )
        for r in rows
    ]
    return sorted(out, key=lambda c: c.amount_minor, reverse=True)


def category_monthly_trend(
    *, category_id: str, months: int = 6, as_of: date | None = None, expense: bool = True
) -> list[dict]:
    """Per-month total for a single category over the trailing `months`, oldest
    first and zero-filled so the series is dense. Mirrors the cashflow-history
    month grid — one cheap aggregate per month for the single category, not an
    N+1 over transactions (`months` is small)."""
    as_of = as_of or timezone.localdate()
    amount_filter = Q(amount_minor__lt=0) if expense else Q(amount_minor__gt=0)

    starts: list[date] = []
    cursor = as_of.replace(day=1)
    for _ in range(max(1, months)):
        starts.append(cursor)
        cursor = (cursor - timedelta(days=1)).replace(day=1)

    out: list[dict] = []
    for start in reversed(starts):  # oldest first
        nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        agg = Transaction.objects.filter(
            _COUNTED,
            _NOT_TRANSFER,
            amount_filter,
            category_id=category_id,
            occurred_at__date__gte=start,
            occurred_at__date__lt=nxt,
        ).aggregate(total=Sum("amount_minor"))
        out.append({"period_start": start.isoformat(), "amount_minor": abs(agg["total"] or 0)})
    return out


def account_statement(*, financial_account: FinancialAccount, start: datetime, end: datetime):
    """Ordered transactions for one account over [start, end) with a running
    balance after each row. Includes transfers (they DO move the balance).
    Running balance is the account's true balance, so liability accounts show
    the amount owed growing on a purchase.

    Two aggregate reads + one windowed read — no per-row queries.
    """
    sign = _kind_sign(financial_account)
    counted = Transaction.objects.filter(_COUNTED, financial_account=financial_account)

    # Opening is reconstructed from today's materialized balance minus later
    # counted activity, not from summing historical rows. Opening-balance
    # journals never become Transactions, and a void reverses the ledger
    # without leaving a reversing Transaction — so a sum of remaining rows
    # quietly drops both, and the statement disagrees with the account header
    # the moment either is present.
    current = account_current_balance_minor(financial_account)
    later = counted.filter(occurred_at__gte=start).aggregate(s=Coalesce(Sum("amount_minor"), Value(0)))["s"]
    opening_balance = current - sign * later

    rows = (
        counted.filter(occurred_at__gte=start, occurred_at__lt=end)
        # No select_related: the statement serializer reads only *_id fields
        # (category_id, counter_account_id, ...), so joining those tables would
        # fetch columns nothing uses. Keep the read lean.
        .annotate(
            cumulative_cashflow=Window(
                expression=Sum("amount_minor"),
                order_by=[F("occurred_at").asc(), F("id").asc()],
            )
        ).order_by("occurred_at", "id")
    )

    statement = []
    for txn in rows:
        running = opening_balance + sign * txn.cumulative_cashflow
        statement.append((txn, running))
    return opening_balance, statement


@dataclass(frozen=True, slots=True)
class TransactionFilters:
    """Read-side filter spec for the transaction list. Every field is optional;
    an all-None instance reproduces the old "just list everything" behaviour.

    Kept as a plain dataclass (not a django-filter FilterSet) so the same
    filters are reusable outside HTTP — exports, reports, tests — without a
    request object, and so the API layer stays a thin adapter over it.
    """

    account: FinancialAccount | None = None
    category_id: object | None = None
    payee_id: object | None = None
    tag_id: object | None = None
    status: str | None = None
    txn_type: str | None = None  # "income" | "expense" | "transfer"
    start: datetime | None = None
    end: datetime | None = None
    min_amount_minor: int | None = None  # bounds compare on ABSOLUTE magnitude
    max_amount_minor: int | None = None
    search: str | None = None  # matches memo or payee name (icontains)
    needs_review: bool | None = None


def list_transactions(
    *,
    financial_account: FinancialAccount | None = None,
    filters: TransactionFilters | None = None,
):
    """Ordered, UNSLICED queryset — callers paginate (cursor pagination is
    the only correct strategy for a high-churn table like this; see
    `apps.common.pagination`). Do not slice this selector directly.

    No select_related: the list serializer (`_txn_out`) reads only *_id fields
    (category_id, payee_id, ...), so joining those tables would fetch columns
    nothing renders.

    `filters` narrows the result set (date range, category, payee, tag, status,
    type, amount range, free-text). The leading `(tenant_id, -occurred_at, -id)`
    and `(tenant_id, financial_account, -occurred_at)` indexes keep the common
    account + date-range case an index scan rather than a full-table sort.
    """
    f = filters or TransactionFilters()
    account = financial_account if financial_account is not None else f.account

    qs = Transaction.objects.all()
    if account is not None:
        qs = qs.filter(financial_account=account)
    if f.category_id is not None:
        qs = qs.filter(category_id=f.category_id)
    if f.payee_id is not None:
        qs = qs.filter(payee_id=f.payee_id)
    if f.tag_id is not None:
        # distinct(): a txn could match on the join once per live tag row
        qs = qs.filter(transactiontag__tag_id=f.tag_id, transactiontag__deleted_at__isnull=True).distinct()
    # Default list hides voids so the activity feed is live money. Asking
    # for status=void must not then exclude them — that combination used
    # to return an empty page.
    qs = qs.filter(status=f.status) if f.status is not None else qs.exclude(status=TransactionStatus.VOID)
    if f.txn_type == "transfer":
        qs = qs.filter(transfer_group__isnull=False)
    elif f.txn_type == "income":
        qs = qs.filter(transfer_group__isnull=True, amount_minor__gt=0)
    elif f.txn_type == "expense":
        qs = qs.filter(transfer_group__isnull=True, amount_minor__lt=0)
    if f.start is not None:
        qs = qs.filter(occurred_at__gte=f.start)
    if f.end is not None:
        qs = qs.filter(occurred_at__lt=f.end)
    if f.min_amount_minor is not None:
        qs = qs.annotate(_abs=Abs("amount_minor")).filter(_abs__gte=f.min_amount_minor)
    if f.max_amount_minor is not None:
        qs = qs.annotate(_abs2=Abs("amount_minor")).filter(_abs2__lte=f.max_amount_minor)
    if f.search:
        qs = qs.filter(
            Q(memo__icontains=f.search)
            | Q(payee__name__icontains=f.search)
            | Q(metadata__mpesa_receipt__icontains=f.search)
        )
    if f.needs_review is not None:
        qs = qs.filter(needs_review=f.needs_review)
    return qs.order_by("-occurred_at", "-id")


def account_current_balance_minor(financial_account: FinancialAccount) -> int:
    return (
        AccountBalance.objects.filter(account_id=financial_account.ledger_account_id)
        .values_list("balance_minor", flat=True)
        .first()
        or 0
    )


@dataclass(frozen=True, slots=True)
class WalletBalance:
    currency: str
    balance_minor: int


def wallet_balances(wallet) -> list[WalletBalance]:
    """Per-currency sum of a wallet's member accounts' materialized balances.
    Never summed across currencies — same discipline as net_worth()."""
    rows = (
        AccountBalance.objects.filter(account__financial_account__wallet=wallet)
        .values("currency")
        .annotate(total=Sum("balance_minor"))
    )
    return [
        WalletBalance(currency=r["currency"], balance_minor=r["total"] or 0)
        for r in sorted(rows, key=lambda r: r["currency"])
    ]


# --------------------------------------------------------------- liquidity ---

#: Cash you can spend this week. Investments are assets but not liquidity;
#: liabilities never are.
_LIQUID_TYPES = {AccountType.CHECKING, AccountType.SAVINGS, AccountType.CASH}


@dataclass(frozen=True, slots=True)
class CashflowStatementRow:
    period_start: date
    inflow_minor: int
    outflow_minor: int
    ending_balance_minor: int

    @property
    def net_minor(self) -> int:
        return self.inflow_minor - self.outflow_minor


@dataclass(frozen=True, slots=True)
class CashflowStatement:
    currency: str
    liquid_balance_minor: int
    rows: list[CashflowStatementRow]


def _dominant_liquid_currency() -> str | None:
    """The currency holding the largest share of liquid cash — the statement is
    single-currency on purpose (see net_worth's FX note)."""
    rows = (
        FinancialAccount.objects.filter(is_active=True, account_type__in=_LIQUID_TYPES)
        .values("currency")
        .annotate(total=Sum("ledger_account__balance__balance_minor"))
        .order_by("-total")
    )
    first = rows.first()
    return first["currency"] if first else None


def liquid_balance_minor(currency: str) -> int:
    return (
        AccountBalance.objects.filter(
            currency=currency,
            account__financial_account__is_active=True,
            account__financial_account__account_type__in=_LIQUID_TYPES,
        ).aggregate(total=Sum("balance_minor"))["total"]
        or 0
    )


def cashflow_statement(*, months: int = 6, as_of: date | None = None) -> CashflowStatement | None:
    """Monthly liquidity statement, oldest first: inflow, outflow, net, and the
    ending liquid balance for each month.

    Ending balances are walked backwards from today's actual liquid balance
    using each month's *true* liquid movement (every transaction touching a
    liquid account, transfer legs included) — so moving cash into an investment
    correctly shows liquidity leaving. The inflow/outflow columns exclude
    transfers, matching the cash-flow endpoint's income/spending semantics.
    """
    currency = _dominant_liquid_currency()
    if currency is None:
        return None
    as_of = as_of or timezone.localdate()

    starts: list[date] = []
    month_start = as_of.replace(day=1)
    for _ in range(months):
        starts.append(month_start)
        month_start = (month_start - timedelta(days=1)).replace(day=1)
    starts.reverse()  # oldest first

    base = Transaction.objects.filter(_COUNTED, currency=currency)
    liquid = base.filter(financial_account__account_type__in=_LIQUID_TYPES)

    flows: list[tuple[date, int, int, int]] = []
    for start in starts:
        nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        in_month = Q(occurred_at__date__gte=start, occurred_at__date__lt=nxt)
        agg = base.filter(in_month, _NOT_TRANSFER).aggregate(
            inflow=Sum("amount_minor", filter=Q(amount_minor__gt=0)),
            outflow=Sum("amount_minor", filter=Q(amount_minor__lt=0)),
        )
        delta = liquid.filter(in_month).aggregate(d=Sum("amount_minor"))["d"] or 0
        flows.append((start, agg["inflow"] or 0, abs(agg["outflow"] or 0), delta))

    balance_now = liquid_balance_minor(currency)
    rows: list[CashflowStatementRow] = []
    ending = balance_now
    for start, inflow, outflow, delta in reversed(flows):  # newest → oldest
        rows.append(
            CashflowStatementRow(
                period_start=start, inflow_minor=inflow, outflow_minor=outflow, ending_balance_minor=ending
            )
        )
        ending -= delta  # previous month ended before this month's movement
    rows.reverse()
    return CashflowStatement(currency=currency, liquid_balance_minor=balance_now, rows=rows)


def net_worth_in_base(base_currency: str) -> dict:
    """Consolidate per-currency net worth into a single base-currency total via
    FX. `converted` is False when any currency lacks a rate, so the UI can show
    an honest "≈" or omit the roll-up rather than present a wrong number."""
    from apps.fx.services import convert

    rows = net_worth()
    total = 0
    all_converted = True
    currencies = 0
    for row in rows:
        currencies += 1
        if row.currency == base_currency:
            total += row.net_minor
            continue
        c = convert(amount_minor=row.net_minor, from_currency=row.currency, to_currency=base_currency)
        if c is None:
            all_converted = False
            continue
        total += c
    return {
        "base_currency": base_currency,
        "total_minor": total,
        "converted": all_converted,
        "currency_count": currencies,
    }
