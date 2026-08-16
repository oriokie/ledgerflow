"""Income — where money comes from, how much of it, and how reliably.

Why this exists
---------------
The product modelled every way money *leaves* — bills, recurring expenses,
budgets, debt minimums, categories — and had no model at all of how it
*arrives*. Income existed only as ``RecurringType.INCOME`` on a schedule
template, and which of those templates was a *salary* was decided by searching
a free-text memo for the English words "salary", "payroll", "wage" or
"paycheck".

That is the one place in this product where a figure was derived from a name.
It fails quietly and it fails hardest for the users the demo data describes: a
household paid in KES whose memo reads "Mshahara" got no payday marker at all,
and the cash-flow calendar is built around "can I make it to payday?".

The deeper cost was not the marker. Without a model of income the product
cannot answer the questions personal financial management exists to answer:
what is my actual take-home rate, how much of it is committed before I choose
anything, is my income trending down, and what happens if one stream stops.

The three models
----------------
``IncomeSource`` is the *plan*: who pays you, how much, on what cadence, and
how much faith to put in it. ``IncomeDeduction`` is the gross→net breakdown —
the difference between what you earn and what you can spend, which is
invisible to a ledger that only ever sees the net deposit. ``IncomeReceipt``
is the *record*: what actually arrived, so expectation can be checked against
reality rather than trusted.

Plan and record are deliberately separate, for the same reason
``RecurringTransaction`` is separate from ``Transaction``: editing what you
expect to earn must not rewrite what you were actually paid.

Reliability is a certainty axis
-------------------------------
``Reliability`` is not a label, it is the input to how a figure may be drawn.
A ``FIXED`` salary is *projected* — known amount, known date. A ``VARIABLE``
retainer is projected with a band. An ``IRREGULAR`` freelance stream is
*speculative*: it may not be rendered as a bare numeral, and any figure derived
from it has to carry its confidence statement. This is the same rule the ledger
applies to a forecast, applied to the other half of the balance sheet.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import SoftDeletableModel


class IncomeKind(models.TextChoices):
    """What sort of arrangement pays this money.

    Kind is not cosmetic. It carries the default reliability, decides whether a
    gross figure is even meaningful (an employer withholds tax; a tenant does
    not), and is what lets the calendar mark a payday without reading a memo.
    """

    EMPLOYMENT = "employment", "Employment"
    SELF_EMPLOYMENT = "self_employment", "Self-employment"
    BUSINESS = "business", "Business"
    RENTAL = "rental", "Rental"
    PENSION = "pension", "Pension"
    BENEFITS = "benefits", "Benefits or grant"
    INVESTMENT = "investment", "Investment income"
    OTHER = "other", "Other"


class Reliability(models.TextChoices):
    """How much of a promise the expected amount is.

    Ordered from most to least certain, and the ordering is load-bearing: the
    UI renders each one differently and the projection widens its band as it
    goes down the list.
    """

    #: Same amount, same day. A salaried paycheque.
    FIXED = "fixed", "Fixed"
    #: Reliable arrival, varying amount. A retainer with overtime, commission.
    VARIABLE = "variable", "Varies"
    #: Neither amount nor date is promised. Freelance, gig, seasonal trade.
    IRREGULAR = "irregular", "Irregular"


#: Reliability to assume when the user has not said. Employment and pensions
#: are contractual; the rest are not, and defaulting them to `FIXED` would let
#: the projection draw a confident line through money nobody promised.
DEFAULT_RELIABILITY_BY_KIND: dict[str, str] = {
    IncomeKind.EMPLOYMENT: Reliability.FIXED,
    IncomeKind.PENSION: Reliability.FIXED,
    IncomeKind.BENEFITS: Reliability.FIXED,
    IncomeKind.RENTAL: Reliability.VARIABLE,
    IncomeKind.BUSINESS: Reliability.VARIABLE,
    IncomeKind.INVESTMENT: Reliability.VARIABLE,
    IncomeKind.SELF_EMPLOYMENT: Reliability.IRREGULAR,
    IncomeKind.OTHER: Reliability.IRREGULAR,
}

#: Kinds where a gross figure and statutory deductions are a normal part of the
#: arrangement. Used only to decide what the UI offers, never to reject input —
#: a self-employed user who wants to track gross and set aside tax is doing
#: something sensible, not something wrong.
KINDS_WITH_GROSS: frozenset[str] = frozenset(
    {IncomeKind.EMPLOYMENT, IncomeKind.PENSION, IncomeKind.BUSINESS, IncomeKind.SELF_EMPLOYMENT}
)


class IncomeFrequency(models.TextChoices):
    """Pay cadence.

    Deliberately its own enum rather than reusing ``finance.Frequency``.
    Fortnightly and semi-monthly are *different* schedules that people are paid
    on — 26 payments a year against 24 — and collapsing them costs two
    paycheques a year in any annualised figure. The finance enum has no need of
    that distinction; this one cannot work without it.
    """

    #: Casual labour and market trade are paid daily and are a real
    #: arrangement, not a rounding of "weekly". Flattening them to ad-hoc would
    #: strip a cadence the projection can actually use.
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    FORTNIGHTLY = "fortnightly", "Every two weeks"
    SEMI_MONTHLY = "semi_monthly", "Twice a month"
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    ANNUAL = "annual", "Annually"
    #: No cadence at all — payment arrives when it arrives. The projection
    #: cannot place these on a date and must not pretend to.
    AD_HOC = "ad_hoc", "Whenever it comes"


#: Payments per year, for annualising. `AD_HOC` is absent on purpose: there is
#: no honest number, and a caller must handle its absence rather than receive a
#: plausible-looking default.
PAYMENTS_PER_YEAR: dict[str, int] = {
    IncomeFrequency.DAILY: 365,
    IncomeFrequency.WEEKLY: 52,
    IncomeFrequency.FORTNIGHTLY: 26,
    IncomeFrequency.SEMI_MONTHLY: 24,
    IncomeFrequency.MONTHLY: 12,
    IncomeFrequency.QUARTERLY: 4,
    IncomeFrequency.ANNUAL: 1,
}


#: Finance schedule unit × interval for each income cadence. Used to place a
#: source on a calendar day. ``AD_HOC`` is absent: there is no date to name.
INCOME_SCHEDULE_UNIT: dict[str, tuple[str, int]] = {
    IncomeFrequency.DAILY: ("daily", 1),
    IncomeFrequency.WEEKLY: ("weekly", 1),
    IncomeFrequency.FORTNIGHTLY: ("weekly", 2),
    IncomeFrequency.MONTHLY: ("monthly", 1),
    IncomeFrequency.QUARTERLY: ("monthly", 3),
    IncomeFrequency.ANNUAL: ("yearly", 1),
}

#: Cadences that land on a numbered day of the month rather than an interval
#: counted from an anchor date. Semi-monthly is handled as two monthly series.
INCOME_DAY_OF_MONTH_CADENCES = frozenset(
    {
        IncomeFrequency.SEMI_MONTHLY,
        IncomeFrequency.MONTHLY,
        IncomeFrequency.QUARTERLY,
        IncomeFrequency.ANNUAL,
    }
)


class IncomeSource(SoftDeletableModel):
    """One arrangement that pays money in.

    ``net_minor`` is required and ``gross_minor`` is optional, which is the
    opposite of how payroll software models it and is the right way round here.
    Most people know exactly what lands in their account and have to go looking
    for the gross. Requiring the figure the user does not have is how a form
    goes unfilled.
    """

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=20, choices=IncomeKind.choices, default=IncomeKind.EMPLOYMENT)
    #: Who pays it. Distinct from `name` so "Monthly salary" can be told apart
    #: from the employer, which matters the moment there are two jobs.
    payer = models.CharField(max_length=120, blank=True, default="")
    currency = models.CharField(max_length=3)

    #: What actually arrives. Always positive.
    net_minor = models.BigIntegerField()
    #: What was earned before deductions. Null when unknown, never zero — zero
    #: would assert the user earns nothing before tax.
    gross_minor = models.BigIntegerField(null=True, blank=True)

    reliability = models.CharField(max_length=12, choices=Reliability.choices, default=Reliability.FIXED)
    frequency = models.CharField(
        max_length=14, choices=IncomeFrequency.choices, default=IncomeFrequency.MONTHLY
    )
    #: Day of the month the money lands, for monthly and semi-monthly cadences.
    #: Capped at 28 for the same reason the goals module caps auto-contribution
    #: day: the 31st silently skipping February is a real bug, not a rare one.
    pay_day = models.PositiveSmallIntegerField(null=True, blank=True)
    #: Second pay day, semi-monthly only.
    second_pay_day = models.PositiveSmallIntegerField(null=True, blank=True)
    #: Anchor for cadences counted from a date rather than a day number.
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)

    #: Where it lands. Optional: a user can describe income before they have
    #: modelled the account it arrives in.
    deposit_account = models.ForeignKey(
        "finance.FinancialAccount",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="income_sources",
    )

    #: The schedule template that auto-posts this income, when the user wants
    #: transactions materialised. Optional and advisory in both directions: an
    #: income source is a description, and describing your salary must not
    #: start writing ledger entries you did not ask for.
    recurring_transaction = models.OneToOneField(
        "finance.RecurringTransaction",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="income_source",
    )

    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(net_minor__gt=0), name="income_net_positive"),
            models.CheckConstraint(
                condition=models.Q(gross_minor__isnull=True) | models.Q(gross_minor__gt=0),
                name="income_gross_positive",
            ),
            # Gross is what you earned; net is what arrived. Net exceeding gross
            # is not a rounding artefact, it is a data-entry error, and letting
            # it in makes every deduction figure derived from the pair a lie.
            models.CheckConstraint(
                condition=models.Q(gross_minor__isnull=True)
                | models.Q(net_minor__lte=models.F("gross_minor")),
                name="income_net_not_above_gross",
            ),
            models.CheckConstraint(
                condition=models.Q(pay_day__isnull=True) | models.Q(pay_day__gte=1, pay_day__lte=28),
                name="income_pay_day_in_range",
            ),
            models.CheckConstraint(
                condition=models.Q(second_pay_day__isnull=True)
                | models.Q(second_pay_day__gte=1, second_pay_day__lte=28),
                name="income_second_pay_day_in_range",
            ),
            models.CheckConstraint(
                condition=models.Q(ends_on__isnull=True) | models.Q(ends_on__gte=models.F("starts_on")),
                name="income_ends_after_start",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "is_active"], name="income_active_idx"),
            models.Index(fields=["tenant_id", "kind"], name="income_kind_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} ({self.net_minor} {self.currency} {self.frequency})"


class DeductionKind(models.TextChoices):
    TAX = "tax", "Income tax"
    SOCIAL_SECURITY = "social_security", "Social security"
    PENSION = "pension", "Pension"
    HEALTH = "health", "Health insurance"
    LOAN = "loan", "Loan repayment"
    UNION = "union", "Union or association"
    OTHER = "other", "Other"


class IncomeDeduction(SoftDeletableModel):
    """One line of the gap between gross and net.

    Every deduction is a share of **gross**, not of the running remainder. Real
    payroll is not always that simple — some jurisdictions assess one levy on
    the balance after another — but modelling a cascade requires an ordering
    the user would have to get right, and a wrong cascade produces a confident
    figure that is wrong. A flat share of gross is a stated simplification the
    user can verify against their own payslip; that is the better failure.

    Exactly one of ``amount_minor`` or ``percent_bp`` is set, enforced in the
    database. Both would be two sources of truth for one number.
    """

    source = models.ForeignKey(IncomeSource, on_delete=models.CASCADE, related_name="deductions")
    kind = models.CharField(max_length=20, choices=DeductionKind.choices, default=DeductionKind.OTHER)
    label = models.CharField(max_length=120, blank=True, default="")

    #: A flat amount per payment.
    amount_minor = models.BigIntegerField(null=True, blank=True)
    #: A share of gross, in basis points — 2000 is 20%. Integer basis points
    #: rather than a decimal percent so a rate is exact rather than a float
    #: that has to be rounded before it can be compared.
    percent_bp = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_minor__isnull=False, percent_bp__isnull=True)
                | models.Q(amount_minor__isnull=True, percent_bp__isnull=False),
                name="deduction_exactly_one_basis",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_minor__isnull=True) | models.Q(amount_minor__gt=0),
                name="deduction_amount_positive",
            ),
            # 10000bp is 100%. A deduction above it takes more than was earned.
            models.CheckConstraint(
                condition=models.Q(percent_bp__isnull=True)
                | models.Q(percent_bp__gt=0, percent_bp__lte=10000),
                name="deduction_percent_in_range",
            ),
        ]
        indexes = [models.Index(fields=["tenant_id", "source"], name="income_deduction_src_idx")]

    def __str__(self) -> str:  # pragma: no cover - trivial
        basis = f"{self.percent_bp}bp" if self.percent_bp is not None else str(self.amount_minor)
        return f"{self.label or self.kind}: {basis}"


class IncomeReceipt(SoftDeletableModel):
    """Money that actually arrived from a source.

    This is what makes the whole model checkable rather than aspirational. An
    expected amount nobody ever compares against reality is a wish; receipts
    are what turn it into a measurement, and they are the only honest input for
    a variable or irregular source's expected figure.

    Soft-deletable so a mis-keyed receipt can be reversed without punching a
    hole in the history the variance is computed from.
    """

    source = models.ForeignKey(IncomeSource, on_delete=models.CASCADE, related_name="receipts")
    occurred_on = models.DateField()
    net_minor = models.BigIntegerField()
    gross_minor = models.BigIntegerField(null=True, blank=True)
    #: Provenance link to the real ledger movement, when one is known.
    #: Advisory: a receipt is a record of fact whether or not it was matched.
    transaction = models.ForeignKey(
        "finance.Transaction",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="income_receipts",
    )
    memo = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(net_minor__gt=0), name="receipt_net_positive"),
            models.CheckConstraint(
                condition=models.Q(gross_minor__isnull=True) | models.Q(gross_minor__gt=0),
                name="receipt_gross_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(gross_minor__isnull=True)
                | models.Q(net_minor__lte=models.F("gross_minor")),
                name="receipt_net_not_above_gross",
            ),
        ]
        indexes = [
            # The hot query: this source's history, newest first.
            models.Index(fields=["tenant_id", "source", "-occurred_on"], name="income_receipt_hist_idx"),
            models.Index(fields=["tenant_id", "-occurred_on"], name="income_receipt_recent_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.net_minor} on {self.occurred_on}"
