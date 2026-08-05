"""Assets — the things you own that you do not transact through.

A house, a car, a piece of land, a business stake. For most households these are
the two or three largest numbers on the balance sheet, and until now there was
nowhere to put them: a net worth that omits the house is not net worth.

Why this is its own app, and not either of the two places it looks like it fits
--------------------------------------------------------------------------------
**Not a `FinancialAccount`.** Adding a `PROPERTY` account type would make a
house a transactable account — it would appear in transfer pickers, the
transaction list, reconciliation, budgets and the overdraft guard, and every one
of those would then need an exclusion. Worse, there would be no way to revalue
it: changing the figure would mean posting a journal entry, and the other side
of that entry does not exist. A gain in value is not an owner contribution, so
opening-balance equity would be a lie.

**Not an `investments.Security`.** The asset class already has `REAL_ESTATE`,
and `PriceQuote` is genuinely the right shape for "what it is worth now". But a
security requires a unique uppercase symbol, carries lots and FIFO disposal that
mean nothing for a house, and `buy()` posts against a funding cash account —
wrong for something bought a decade ago on a mortgage. The module is also
plan-gated, and a customer should be able to record the largest thing they own
without paying more.

How the value stays honest
--------------------------
**Nothing here is ever posted to the ledger.** An asset's worth changes because
somebody re-estimated it, not because money moved, and the ledger's whole claim
is that every figure in it traces to a posting. So assets follow the pattern
already proven for unrealised investment gains: an *overlay* on net worth, kept
deliberately outside the double-entry truth.

An asset with no valuation contributes nothing. Never its purchase price, never
a guess — the same refusal the health score makes about data it does not have.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import SoftDeletableModel


class AssetKind(models.TextChoices):
    """What sort of thing this is.

    Drives presentation and the questions worth asking, not arithmetic. A house
    and a car are both worth what someone would pay for them; they differ in
    that one tends to appreciate and the other certainly does not, which is a
    fact about how often you should revalue rather than about how to store it.
    """

    PROPERTY = "property", "Property"
    LAND = "land", "Land"
    VEHICLE = "vehicle", "Vehicle"
    VALUABLE = "valuable", "Valuables"
    BUSINESS = "business", "Business stake"
    OTHER = "other", "Something else"


class ValuationSource(models.TextChoices):
    """Where a figure came from, which is a statement about how much to trust it.

    Recorded because these are not equivalent. A bank's valuation for a mortgage
    and an owner's guess are both numbers, and a product that shows them
    identically is inviting the reader to treat the second as the first.
    """

    PURCHASE = "purchase", "What it cost"
    OWNER = "owner", "My own estimate"
    PROFESSIONAL = "professional", "Professional valuation"
    MARKET = "market", "Market listing or index"


class Asset(SoftDeletableModel):
    """One thing owned."""

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=AssetKind.choices, default=AssetKind.OTHER)
    currency = models.CharField(max_length=3)
    description = models.CharField(max_length=255, blank=True, default="")

    acquired_on = models.DateField(null=True, blank=True)
    #: What it cost. Optional and *not* a valuation: plenty of people know what
    #: they paid and have no idea what it is worth now, and the two questions
    #: deserve different answers. Where both a cost and a later valuation exist,
    #: the history between them is interpolated — see `selectors.value_at`.
    acquisition_cost_minor = models.BigIntegerField(null=True, blank=True)

    #: The liability this asset secures — a mortgage against a house, a loan
    #: against a car.
    #:
    #: This link is what lets the product say something better than two
    #: unrelated figures: worth 8m, owing 5m, *your equity is 3m*. Loan-to-value
    #: is a real signal and is unanswerable without it. Optional, because plenty
    #: of things are owned outright.
    secured_by_debt = models.ForeignKey(
        "finance.FinancialAccount",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="secured_assets",
        help_text="The loan or mortgage secured on this asset.",
    )

    #: Some assets shouldn't count toward the household's own position — a car
    #: held for a relative, a property owned with others. Mirrors
    #: `FinancialAccount.include_in_net_worth`, and is a reporting choice only.
    include_in_net_worth = models.BooleanField(default=True)
    notes = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(acquisition_cost_minor__isnull=True)
                | models.Q(acquisition_cost_minor__gte=0),
                name="asset_cost_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "kind"], name="asset_kind_idx"),
            models.Index(fields=["tenant_id", "include_in_net_worth"], name="asset_networth_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} ({self.kind})"


class Valuation(SoftDeletableModel):
    """What an asset was judged to be worth, on a date.

    Rows rather than a single mutable figure on the asset, for the same reason
    the ledger is made of entries: one number cannot say when it was true, and
    correcting it would destroy the history that produced it. A house valued
    three times in eight years has a shape, and that shape is what the net-worth
    chart draws.

    Structurally this is `investments.PriceQuote` — deliberately. That model
    already solved "what is this worth now" without pretending money moved, and
    a second, different answer to the same question would be the drift worth
    avoiding.
    """

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="valuations")
    as_of = models.DateField()
    value_minor = models.BigIntegerField()
    source = models.CharField(max_length=16, choices=ValuationSource.choices, default=ValuationSource.OWNER)
    notes = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(value_minor__gte=0), name="valuation_non_negative"),
            # One judgement per asset per day. A second on the same date is a
            # correction of the first, not an additional data point.
            models.UniqueConstraint(
                fields=["asset", "as_of"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_valuation_per_day",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "asset", "-as_of"], name="valuation_hist_idx"),
        ]
        ordering = ["-as_of"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.value_minor} on {self.as_of}"
