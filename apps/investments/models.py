"""Investment tracking — holdings, lots, and market value.

The central design decision, and the one everything else follows from:

    **The ledger holds cost. Market value is derived and never posted.**

What you paid for a security is a fact: money moved, and a double-entry pair
records it. What it is *worth today* is an opinion that changes every second and
that you have not realised. Posting an unrealised gain would put a number in the
ledger that no transaction produced, and the ledger would stop reconciling to
anything real.

So:

* Buying posts DEBIT investment asset / CREDIT cash, at cost.
* Selling posts the disposal at **cost**, and books the difference between
  proceeds and cost to a realised gain/loss account — that difference is real
  income the moment it happens.
* Market value, unrealised gain, and allocation are *reads*. They are computed
  from `PriceQuote` on demand and never written to a journal.

Cost basis is tracked per **lot**, not as a running average on the holding. Two
purchases of the same stock at different prices are two different tax facts, and
collapsing them loses information that cannot be reconstructed. FIFO disposal is
the default because it is the most widely applicable; the lot model makes other
methods a selector change rather than a migration.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models

from apps.common.models import SoftDeletableModel, TenantOwnedModel


class AssetClass(models.TextChoices):
    """Top-level allocation buckets.

    Chosen to match how people actually think about a portfolio rather than any
    regulatory taxonomy — the goal is a pie chart someone recognises.
    """

    STOCK = "stock", "Stocks"
    ETF = "etf", "ETFs"
    MUTUAL_FUND = "mutual_fund", "Mutual funds"
    BOND = "bond", "Bonds"
    CRYPTO = "crypto", "Crypto"
    CASH_EQUIVALENT = "cash_equivalent", "Cash investments"
    REAL_ESTATE = "real_estate", "Real estate"
    COMMODITY = "commodity", "Commodities"
    OTHER = "other", "Other"


class Security(SoftDeletableModel):
    """A tradeable instrument.

    Tenant-scoped rather than global reference data, deliberately. A household
    may hold things no data provider lists — a private company stake, a friend's
    business, a physical asset — and forcing those through a shared registry
    would either pollute it or exclude them. The cost is some duplication of
    well-known tickers across tenants, which is cheap.

    `symbol` is uppercased on save so "aapl" and "AAPL" are one security.
    """

    symbol = models.CharField(max_length=32)
    name = models.CharField(max_length=160)
    asset_class = models.CharField(max_length=20, choices=AssetClass.choices)
    #: Free text rather than an enum: sector taxonomies differ by provider and
    #: by market, and an enum would be wrong somewhere immediately.
    sector = models.CharField(max_length=80, blank=True, default="")
    currency = models.CharField(max_length=3)
    exchange = models.CharField(max_length=32, blank=True, default="")
    #: Provider identifier, for a future broker or market-data integration.
    external_id = models.CharField(max_length=128, blank=True, default="")
    #: Crypto and some funds trade in fractions; equities usually don't. Stored
    #: per security so quantity precision is a property of the instrument.
    quantity_precision = models.PositiveSmallIntegerField(default=8)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "symbol"],
                name="uniq_security_symbol",
                condition=models.Q(deleted_at__isnull=True),
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "asset_class"], name="security_class_idx"),
        ]
        verbose_name_plural = "securities"

    def save(self, *args, **kwargs):
        self.symbol = self.symbol.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.symbol} ({self.name})"


class Holding(SoftDeletableModel):
    """A position: one security inside one investment account.

    Quantity is denormalised here because every read needs it and recomputing
    from lots on each request would be an N+1 across the portfolio. It is only
    ever written by the service layer alongside the lots it summarises, inside
    the same transaction, so the two cannot drift.

    Cost basis is *not* stored: it is the sum of open lots, and duplicating it
    would create a second source of truth for the number that matters most.
    """

    financial_account = models.ForeignKey(
        "finance.FinancialAccount", on_delete=models.PROTECT, related_name="holdings"
    )
    security = models.ForeignKey(Security, on_delete=models.PROTECT, related_name="holdings")
    #: Signed only in the sense that it is never negative — short positions are
    #: out of scope, and a negative quantity here would silently corrupt every
    #: allocation figure downstream.
    quantity = models.DecimalField(max_digits=28, decimal_places=8, default=Decimal("0"))
    notes = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "financial_account", "security"],
                name="uniq_holding_account_security",
                condition=models.Q(deleted_at__isnull=True),
            ),
            models.CheckConstraint(condition=models.Q(quantity__gte=0), name="holding_qty_non_negative"),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "financial_account"], name="holding_account_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.quantity} {self.security_id}"


class Lot(TenantOwnedModel):
    """One purchase, at one price, on one date.

    Append-mostly: a lot's `quantity_remaining` shrinks as it is disposed of,
    but its `quantity` and `cost_minor` never change. That keeps the original
    purchase a stable historical fact even after partial sales, which is what
    makes cost basis defensible.

    `cost_minor` is the **total** paid including fees, not a unit price.
    Deriving unit price from it loses nothing; storing a unit price would
    introduce a rounding error on every read.
    """

    holding = models.ForeignKey(Holding, on_delete=models.CASCADE, related_name="lots")
    acquired_on = models.DateField()
    quantity = models.DecimalField(max_digits=28, decimal_places=8)
    quantity_remaining = models.DecimalField(max_digits=28, decimal_places=8)
    #: Total consideration for this lot, in the security's currency.
    cost_minor = models.BigIntegerField()
    #: Links back to the ledger entry that recorded the purchase, so a position
    #: can always be traced to the money that bought it.
    journal_entry = models.ForeignKey(
        "ledger.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="lot_qty_positive"),
            models.CheckConstraint(condition=models.Q(cost_minor__gte=0), name="lot_cost_non_negative"),
            models.CheckConstraint(
                condition=models.Q(quantity_remaining__gte=0), name="lot_remaining_non_negative"
            ),
        ]
        indexes = [
            # The FIFO disposal query: open lots for a holding, oldest first.
            models.Index(fields=["tenant_id", "holding", "acquired_on"], name="lot_fifo_idx"),
        ]
        ordering = ["acquired_on", "id"]

    @property
    def is_open(self) -> bool:
        return self.quantity_remaining > 0

    @property
    def cost_remaining_minor(self) -> int:
        """Cost still attributable to this lot, pro-rated by what's left.

        Pro-rating rather than tracking a separate figure keeps the invariant
        that a fully-disposed lot has exactly zero cost remaining, with no
        accumulated rounding drift.
        """
        if self.quantity <= 0:
            return 0
        if self.quantity_remaining == self.quantity:
            return self.cost_minor
        return int(Decimal(self.cost_minor) * self.quantity_remaining / self.quantity)


class InvestmentTransactionType(models.TextChoices):
    BUY = "buy", "Buy"
    SELL = "sell", "Sell"
    DIVIDEND = "dividend", "Dividend"
    INTEREST = "interest", "Interest"
    FEE = "fee", "Fee"
    #: Quantity changes with no money movement — a split or a stock dividend.
    SPLIT = "split", "Split"


class InvestmentTransaction(TenantOwnedModel):
    """An investment event, and its link to the ledger entry that recorded it.

    Immutable once written, like the ledger it points at. A mistaken trade is
    corrected by a reversing transaction, never by editing history — the same
    discipline the double-entry core enforces.
    """

    holding = models.ForeignKey(Holding, on_delete=models.PROTECT, related_name="transactions")
    txn_type = models.CharField(max_length=12, choices=InvestmentTransactionType.choices)
    occurred_on = models.DateField()
    quantity = models.DecimalField(max_digits=28, decimal_places=8, default=Decimal("0"))
    #: Gross consideration: what left or arrived before fees.
    amount_minor = models.BigIntegerField(default=0)
    fee_minor = models.BigIntegerField(default=0)
    #: Only set on a disposal. Positive is a gain, negative a loss — this is the
    #: one place a signed money figure is correct here, because the sign is the
    #: information.
    realized_gain_minor = models.BigIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3)
    memo = models.CharField(max_length=255, blank=True, default="")
    journal_entry = models.ForeignKey(
        "ledger.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(fee_minor__gte=0), name="invtxn_fee_non_negative"),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "holding", "-occurred_on"], name="invtxn_holding_idx"),
            models.Index(fields=["tenant_id", "txn_type", "-occurred_on"], name="invtxn_type_idx"),
        ]
        ordering = ["-occurred_on", "-id"]

    def __str__(self) -> str:
        return f"{self.txn_type} {self.quantity} @ {self.occurred_on}"


class PriceQuote(TenantOwnedModel):
    """A market price for a security on a date.

    Deliberately not a ledger construct. A price is an observation about the
    world, not a transaction — nothing moved when it changed. Storing history
    lets the portfolio be valued at any past date, which is what makes a
    performance chart possible.

    Uniqueness is per (security, as_of) so re-fetching a day's close updates it
    rather than accumulating duplicates.
    """

    security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name="quotes")
    as_of = models.DateField()
    #: Price per unit in the security's currency, as minor units.
    price_minor = models.BigIntegerField()
    #: Where this came from — "manual", or a provider name once one is wired.
    source = models.CharField(max_length=40, default="manual")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "security", "as_of"], name="uniq_quote_security_date"
            ),
            models.CheckConstraint(condition=models.Q(price_minor__gte=0), name="quote_price_non_negative"),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "security", "-as_of"], name="quote_latest_idx"),
        ]
        ordering = ["-as_of"]

    def __str__(self) -> str:
        return f"{self.security_id} @ {self.as_of}: {self.price_minor}"
