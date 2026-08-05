"""Investment services — every position change posts to the ledger.

Nothing here writes a balance directly. Buying, selling, and receiving a
dividend are all money movements, and each one goes through
`post_journal_entry` like any other transaction in the product. That is what
keeps a portfolio reconcilable against the accounts that funded it.

The accounting, stated plainly:

    Buy      DEBIT  investment asset (cost + fees)
             CREDIT cash

    Sell     DEBIT  cash (net proceeds)
             CREDIT investment asset (at COST of the lots disposed)
             + a balancing line to realised gain/loss for the difference

    Dividend DEBIT  cash
             CREDIT dividend income

    Fee      DEBIT  investment fees (expense)
             CREDIT cash

The subtle one is the sale. The asset is relieved at what it *cost*, not at what
it sold for, and the gap between the two is the realised gain — real income, the
moment it happens. Crediting the asset at proceeds instead would make the
position's book value drift away from every lot that formed it, and the error
compounds silently with each sale.

Unrealised gains are never posted. See the note in `models.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common import audit
from apps.finance.models import FinancialAccount, TransactionStatus
from apps.finance.models import Transaction as FinanceTransaction
from apps.ledger import services as ledger_services
from apps.ledger.models import Account as LedgerAccount
from apps.ledger.models import AccountKind, Direction
from apps.ledger.services import LineInput

from .models import (
    AssetClass,
    Holding,
    InvestmentTransaction,
    InvestmentTransactionType,
    Lot,
    PriceQuote,
    Security,
)


class InvestmentError(Exception): ...


#: System ledger accounts the module provisions on demand. Names carry the
#: currency because ledger Account uniqueness is (tenant, name, kind) and does
#: not include currency — the same constraint opening balances work around.
_INVESTMENT_ASSET = "Investments"
_REALIZED_GAIN = "Realised investment gains"
_DIVIDEND_INCOME = "Dividend income"
_INTEREST_INCOME = "Investment interest"
_INVESTMENT_FEES = "Investment fees"


def _system_account(name: str, kind: str, currency: str) -> LedgerAccount:
    """Get-or-create a system ledger account, lazily.

    A workspace that never invests never carries these accounts.
    """
    full_name = f"{name} ({currency})"
    existing = LedgerAccount.objects.filter(name=full_name, kind=kind).first()
    if existing is not None:
        return existing
    return ledger_services.create_account(name=full_name, kind=kind, currency=currency, is_system=True)


def investment_asset_account(currency: str) -> LedgerAccount:
    return _system_account(_INVESTMENT_ASSET, AccountKind.ASSET, currency)


def realized_gain_account(currency: str) -> LedgerAccount:
    return _system_account(_REALIZED_GAIN, AccountKind.INCOME, currency)


def dividend_income_account(currency: str) -> LedgerAccount:
    return _system_account(_DIVIDEND_INCOME, AccountKind.INCOME, currency)


def interest_income_account(currency: str) -> LedgerAccount:
    """Interest earned on a holding — an MMF distribution, a bond coupon.

    Kept apart from dividend income rather than lumped in with it. They are
    taxed differently in most jurisdictions, and a money-market fund paying
    monthly interest is a fundamentally different cash-flow shape from an
    equity paying a discretionary dividend twice a year. Reporting has to be
    able to tell them apart.
    """
    return _system_account(_INTEREST_INCOME, AccountKind.INCOME, currency)


def investment_fee_account(currency: str) -> LedgerAccount:
    return _system_account(_INVESTMENT_FEES, AccountKind.EXPENSE, currency)


# --------------------------------------------------------------------- securities
@transaction.atomic
def create_security(
    *,
    symbol: str,
    name: str,
    asset_class: str,
    currency: str,
    sector: str = "",
    exchange: str = "",
    external_id: str = "",
) -> Security:
    if not symbol.strip():
        raise InvestmentError("A security needs a symbol.")
    if asset_class not in AssetClass.values:
        raise InvestmentError(f"Unknown asset class {asset_class!r}.")

    # Checked explicitly, ahead of the write: `Security.save()` uppercases and
    # strips the symbol, so "vti" and "VTI" collide at the database constraint
    # even though they look different as typed. Letting that surface as a raw
    # IntegrityError is exactly the failure mode that looks like a dead
    # button — the request 500s with no message, so a retried submission
    # (which looks like the reasonable thing to do when nothing seems to have
    # happened) is what actually trips it, on a symbol that in fact already
    # exists.
    normalized = symbol.strip().upper()
    if Security.objects.filter(symbol=normalized).exists():
        raise InvestmentError(f"{normalized} is already tracked in this workspace.")

    # The check above is a courtesy, not the actual guarantee — it isn't
    # atomic with the write, so two concurrent submissions of the same new
    # symbol could both pass it. The database constraint is the real
    # guarantee; this backstop only makes sure hitting it still produces the
    # same clean, actionable error instead of a raw 500 either way.
    try:
        return Security.objects.create(
            symbol=symbol,
            name=name or symbol,
            asset_class=asset_class,
            currency=currency.upper(),
            sector=sector,
            exchange=exchange,
            external_id=external_id,
        )
    except IntegrityError as exc:
        raise InvestmentError(f"{normalized} is already tracked in this workspace.") from exc


@transaction.atomic
def record_price(
    *, security: Security, price_minor: int, as_of: date | None = None, source: str = "manual"
) -> PriceQuote:
    """Record a market price. Updates rather than duplicates for a given day."""
    if price_minor < 0:
        raise InvestmentError("Price cannot be negative.")
    as_of = as_of or timezone.localdate()
    quote, _ = PriceQuote.objects.update_or_create(
        security=security,
        as_of=as_of,
        defaults={"price_minor": price_minor, "source": source},
    )
    return quote


# ----------------------------------------------------------------------- holdings
def _get_or_create_holding(*, financial_account: FinancialAccount, security: Security) -> Holding:
    if financial_account.currency != security.currency:
        # A GBP account holding a USD security needs an FX policy this module
        # doesn't have. Refusing is honest; guessing a rate would not be.
        raise InvestmentError(
            "Security currency must match the account currency. "
            "Hold foreign securities in an account of that currency."
        )
    holding, _ = Holding.objects.get_or_create(financial_account=financial_account, security=security)
    return holding


@dataclass(frozen=True, slots=True)
class Disposal:
    """One lot consumed by a sale."""

    lot_id: str
    quantity: Decimal
    cost_minor: int


def _consume_lots_fifo(*, holding: Holding, quantity: Decimal) -> list[Disposal]:
    """Relieve `quantity` from the oldest open lots first.

    FIFO by default because it applies in the most jurisdictions and is what a
    user without a stated preference means. The lot model makes LIFO or specific
    identification a change to this function alone — no schema, no migration.

    Locks the lots for update: two concurrent sales of the same holding must not
    both believe they consumed the same shares.
    """
    remaining = quantity
    disposals: list[Disposal] = []

    lots = (
        Lot.objects.select_for_update()
        .filter(holding=holding, quantity_remaining__gt=0)
        .order_by("acquired_on", "id")
    )
    for lot in lots:
        if remaining <= 0:
            break
        take = min(lot.quantity_remaining, remaining)
        # Pro-rate this lot's cost by the fraction being disposed of.
        cost = int(Decimal(lot.cost_minor) * take / lot.quantity)
        disposals.append(Disposal(lot_id=str(lot.id), quantity=take, cost_minor=cost))

        lot.quantity_remaining -= take
        lot.save(update_fields=["quantity_remaining", "updated_at"])
        remaining -= take

    if remaining > 0:
        raise InvestmentError(
            f"Not enough units to sell: short by {remaining}. Short positions aren't supported."
        )
    return disposals


@transaction.atomic
def buy(
    *,
    financial_account: FinancialAccount,
    security: Security,
    quantity: Decimal,
    amount_minor: int,
    occurred_on: date | None = None,
    fee_minor: int = 0,
    cash_account: FinancialAccount | None = None,
    memo: str = "",
    idempotency_key: str | None = None,
) -> InvestmentTransaction:
    """Record a purchase and post it to the ledger.

    `amount_minor` is the gross consideration before fees. Fees are capitalised
    into the lot's cost, which is the correct treatment: what you paid to acquire
    the position *is* part of what it cost you, and excluding them would
    overstate every future gain.
    """
    if quantity <= 0:
        raise InvestmentError("Buy quantity must be positive.")
    if amount_minor <= 0:
        raise InvestmentError("Buy amount must be positive.")
    if fee_minor < 0:
        raise InvestmentError("Fee cannot be negative.")

    occurred_on = occurred_on or timezone.localdate()
    holding = _get_or_create_holding(financial_account=financial_account, security=security)
    currency = security.currency
    total_cost = amount_minor + fee_minor

    # Money comes from the investment account itself unless a separate cash
    # account is named — a brokerage sweep balance is the common case.
    source = cash_account or financial_account
    if source.currency != currency:
        raise InvestmentError("Cash account currency must match the security currency.")

    entry = ledger_services.post_journal_entry(
        occurred_at=timezone.make_aware(timezone.datetime.combine(occurred_on, timezone.datetime.min.time())),
        lines=[
            LineInput(
                account_id=str(investment_asset_account(currency).id),
                direction=Direction.DEBIT,
                amount_minor=total_cost,
            ),
            LineInput(
                account_id=str(source.ledger_account_id),
                direction=Direction.CREDIT,
                amount_minor=total_cost,
            ),
        ],
        idempotency_key=idempotency_key or f"inv-buy:{holding.id}:{occurred_on}:{quantity}:{total_cost}",
        memo=memo or f"Buy {quantity} {security.symbol}",
    )

    Lot.objects.create(
        holding=holding,
        acquired_on=occurred_on,
        quantity=quantity,
        quantity_remaining=quantity,
        cost_minor=total_cost,
        journal_entry=entry,
    )
    holding.quantity = Decimal(holding.quantity) + quantity
    holding.save(update_fields=["quantity", "updated_at"])

    return InvestmentTransaction.objects.create(
        holding=holding,
        txn_type=InvestmentTransactionType.BUY,
        occurred_on=occurred_on,
        quantity=quantity,
        amount_minor=amount_minor,
        fee_minor=fee_minor,
        currency=currency,
        memo=memo,
        journal_entry=entry,
    )


@transaction.atomic
def sell(
    *,
    financial_account: FinancialAccount,
    security: Security,
    quantity: Decimal,
    amount_minor: int,
    occurred_on: date | None = None,
    fee_minor: int = 0,
    cash_account: FinancialAccount | None = None,
    memo: str = "",
    idempotency_key: str | None = None,
) -> InvestmentTransaction:
    """Record a disposal, relieve the lots, and book the realised gain.

    The asset is credited at the **cost** of the lots consumed, not at the sale
    price. The difference between net proceeds and that cost is the realised
    gain, and it gets its own line. Getting this backwards is the single most
    common way an investment tracker's numbers stop reconciling.
    """
    if quantity <= 0:
        raise InvestmentError("Sell quantity must be positive.")
    if amount_minor <= 0:
        raise InvestmentError("Sale amount must be positive.")
    if fee_minor < 0:
        raise InvestmentError("Fee cannot be negative.")

    occurred_on = occurred_on or timezone.localdate()
    holding = Holding.objects.filter(financial_account=financial_account, security=security).first()
    if holding is None:
        raise InvestmentError("No holding to sell from.")

    currency = security.currency
    destination = cash_account or financial_account
    if destination.currency != currency:
        raise InvestmentError("Cash account currency must match the security currency.")

    disposals = _consume_lots_fifo(holding=holding, quantity=quantity)
    cost_basis = sum(d.cost_minor for d in disposals)
    net_proceeds = amount_minor - fee_minor
    gain = net_proceeds - cost_basis

    lines = [
        LineInput(
            account_id=str(destination.ledger_account_id),
            direction=Direction.DEBIT,
            amount_minor=net_proceeds,
        ),
        LineInput(
            account_id=str(investment_asset_account(currency).id),
            direction=Direction.CREDIT,
            amount_minor=cost_basis,
        ),
    ]
    if gain > 0:
        # Income increases on the credit side.
        lines.append(
            LineInput(
                account_id=str(realized_gain_account(currency).id),
                direction=Direction.CREDIT,
                amount_minor=gain,
            )
        )
    elif gain < 0:
        # A loss debits the same income account, reducing it. Using one account
        # for both directions keeps "realised gains" a single net figure rather
        # than two that have to be subtracted to mean anything.
        lines.append(
            LineInput(
                account_id=str(realized_gain_account(currency).id),
                direction=Direction.DEBIT,
                amount_minor=-gain,
            )
        )

    entry = ledger_services.post_journal_entry(
        occurred_at=timezone.make_aware(timezone.datetime.combine(occurred_on, timezone.datetime.min.time())),
        lines=lines,
        idempotency_key=idempotency_key or f"inv-sell:{holding.id}:{occurred_on}:{quantity}:{amount_minor}",
        memo=memo or f"Sell {quantity} {security.symbol}",
    )

    holding.quantity = Decimal(holding.quantity) - quantity
    holding.save(update_fields=["quantity", "updated_at"])

    return InvestmentTransaction.objects.create(
        holding=holding,
        txn_type=InvestmentTransactionType.SELL,
        occurred_on=occurred_on,
        quantity=quantity,
        amount_minor=amount_minor,
        fee_minor=fee_minor,
        realized_gain_minor=gain,
        currency=currency,
        memo=memo,
        journal_entry=entry,
    )


def _record_investment_income(
    *,
    financial_account: FinancialAccount,
    security: Security,
    amount_minor: int,
    txn_type: str,
    income_account: LedgerAccount,
    occurred_on: date | None,
    cash_account: FinancialAccount | None,
    memo: str,
    default_memo: str,
    idem_prefix: str,
    idempotency_key: str | None,
) -> InvestmentTransaction:
    """Post an income distribution from a holding: dividend or interest.

    Shared because the two differ only in which income account they credit and
    what they are called. The accounting, the cash-flow visibility and the
    idempotency shape are identical, and two copies of that would drift.
    """
    if amount_minor <= 0:
        raise InvestmentError(f"{default_memo.split(' ')[0]} amount must be positive.")

    occurred_on = occurred_on or timezone.localdate()
    holding = _get_or_create_holding(financial_account=financial_account, security=security)
    currency = security.currency
    destination = cash_account or financial_account
    occurred_at = timezone.make_aware(timezone.datetime.combine(occurred_on, timezone.datetime.min.time()))

    entry = ledger_services.post_journal_entry(
        occurred_at=occurred_at,
        lines=[
            LineInput(
                account_id=str(destination.ledger_account_id),
                direction=Direction.DEBIT,
                amount_minor=amount_minor,
            ),
            LineInput(
                account_id=str(income_account.id),
                direction=Direction.CREDIT,
                amount_minor=amount_minor,
            ),
        ],
        idempotency_key=idempotency_key or f"{idem_prefix}:{holding.id}:{occurred_on}:{amount_minor}",
        memo=memo or default_memo,
    )

    # Surface it as a domain Transaction as well as a ledger entry.
    #
    # Without this the money reached the account's *balance* but never appeared
    # in cash flow, the transaction list, or any income figure — because all of
    # those read `finance.Transaction`, not the ledger. Investment income was
    # therefore invisible everywhere a user would look for it, which for an MMF
    # paying monthly interest is most of what the holding does.
    #
    # Guarded on the entry so a retried request cannot produce a second row
    # against the same idempotent posting.
    if not FinanceTransaction.objects.filter(journal_entry=entry).exists():
        FinanceTransaction.objects.create(
            financial_account=destination,
            journal_entry=entry,
            amount_minor=amount_minor,  # signed: money in
            currency=currency,
            occurred_at=occurred_at,
            posted_at=timezone.now(),
            status=TransactionStatus.POSTED,
            memo=memo or default_memo,
        )

    return InvestmentTransaction.objects.create(
        holding=holding,
        txn_type=txn_type,
        occurred_on=occurred_on,
        amount_minor=amount_minor,
        currency=currency,
        memo=memo,
        journal_entry=entry,
    )


@transaction.atomic
def record_dividend(
    *,
    financial_account: FinancialAccount,
    security: Security,
    amount_minor: int,
    occurred_on: date | None = None,
    cash_account: FinancialAccount | None = None,
    memo: str = "",
    idempotency_key: str | None = None,
) -> InvestmentTransaction:
    """Cash dividend: real income, posted as such.

    Not added to cost basis. A dividend is a return *on* the investment, not a
    further investment in it — capitalising it would understate every subsequent
    gain and overstate the position's cost.
    """
    return _record_investment_income(
        financial_account=financial_account,
        security=security,
        amount_minor=amount_minor,
        txn_type=InvestmentTransactionType.DIVIDEND,
        income_account=dividend_income_account(security.currency),
        occurred_on=occurred_on,
        cash_account=cash_account,
        memo=memo,
        default_memo=f"Dividend from {security.symbol}",
        idem_prefix="inv-div",
        idempotency_key=idempotency_key,
    )


@transaction.atomic
def record_interest(
    *,
    financial_account: FinancialAccount,
    security: Security,
    amount_minor: int,
    occurred_on: date | None = None,
    cash_account: FinancialAccount | None = None,
    memo: str = "",
    idempotency_key: str | None = None,
) -> InvestmentTransaction:
    """Interest paid out by a holding — an MMF distribution, a bond coupon.

    `InvestmentTransactionType.INTEREST` existed from the start but nothing
    could produce one: there was no service and no endpoint, so the periodic
    payments that are the *entire point* of a money-market fund or a bond had
    nowhere to go. A user could only record them as unrelated manual income,
    which severed them from the holding that generated them.

    Like a dividend, interest is a return *on* the investment and is never
    added to cost basis. Reinvested interest is two events, not one — this,
    then a buy — and recording it that way keeps both the income and the larger
    position true.
    """
    return _record_investment_income(
        financial_account=financial_account,
        security=security,
        amount_minor=amount_minor,
        txn_type=InvestmentTransactionType.INTEREST,
        income_account=interest_income_account(security.currency),
        occurred_on=occurred_on,
        cash_account=cash_account,
        memo=memo,
        default_memo=f"Interest from {security.symbol}",
        idem_prefix="inv-int",
        idempotency_key=idempotency_key,
    )


@transaction.atomic
def apply_split(
    *,
    financial_account: FinancialAccount,
    security: Security,
    ratio: Decimal,
    occurred_on: date | None = None,
    memo: str = "",
) -> InvestmentTransaction:
    """A share split: more units, same money.

    No ledger entry, deliberately — nothing moved. Cost basis per lot is
    unchanged in total and simply spreads over more units, which is exactly what
    a split is. Posting anything here would invent value from a relabelling.
    """
    if ratio <= 0:
        raise InvestmentError("Split ratio must be positive.")

    occurred_on = occurred_on or timezone.localdate()
    holding = Holding.objects.filter(financial_account=financial_account, security=security).first()
    if holding is None:
        raise InvestmentError("No holding to split.")

    for lot in Lot.objects.select_for_update().filter(holding=holding):
        lot.quantity = lot.quantity * ratio
        lot.quantity_remaining = lot.quantity_remaining * ratio
        lot.save(update_fields=["quantity", "quantity_remaining", "updated_at"])

    before = Decimal(holding.quantity)
    holding.quantity = before * ratio
    holding.save(update_fields=["quantity", "updated_at"])

    return InvestmentTransaction.objects.create(
        holding=holding,
        txn_type=InvestmentTransactionType.SPLIT,
        occurred_on=occurred_on,
        quantity=holding.quantity - before,
        currency=security.currency,
        memo=memo or f"{ratio}:1 split",
    )


@transaction.atomic
def update_security(*, security: Security, **fields) -> Security:
    """Correct a security's details.

    Exists because it did not: a security could be created and never touched
    again, so a mistyped ticker became permanent — and, because `create_security`
    rejects duplicates case-insensitively, it also blocked creating the correct
    symbol if the typo collided with it. The only escape was database access.

    `symbol` is editable and re-checked for collisions, since the typo people
    most want to fix is in the symbol itself.
    """
    editable = {"symbol", "name", "asset_class", "currency", "sector", "exchange"}
    unknown = set(fields) - editable
    if unknown:
        raise InvestmentError(f"Cannot edit: {', '.join(sorted(unknown))}.")

    new_symbol = (fields.get("symbol") or "").strip().upper()
    if new_symbol and new_symbol != security.symbol:
        if Security.objects.filter(symbol=new_symbol).exclude(pk=security.pk).exists():
            raise InvestmentError(f"{new_symbol} is already tracked in this workspace.")
        fields["symbol"] = new_symbol

    for key, value in fields.items():
        if value is not None:
            setattr(security, key, value)
    security.save()
    audit.record(
        action="security.updated",
        target=security,
        changes={k: [None, str(v)] for k, v in fields.items() if v is not None},
    )
    return security


@transaction.atomic
def delete_security(*, security: Security) -> None:
    """Soft-delete a security, provided nothing depends on it.

    Refused once the security has trades: deleting it would orphan holdings and
    silently change historical cost basis. A tracked-but-unused security — the
    typo case this exists for — deletes cleanly, and because the uniqueness
    constraint is scoped to live rows the correct symbol can then be created.
    """
    # Trades hang off a Holding, not off the Security directly, so the holding
    # is the thing to test. Either way the rule is the same: deleting a security
    # with history would orphan positions and silently rewrite cost basis.
    if Holding.objects.filter(security=security).exists():
        raise InvestmentError(
            "This security has holdings or trades recorded against it. It can be "
            "corrected, but not removed — the history refers to it."
        )
    audit.record(action="security.deleted", target=security, changes={"symbol": [security.symbol, None]})
    security.delete()
