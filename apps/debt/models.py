"""Debt terms — the numbers a ledger doesn't hold.

A liability's *balance* is already in the ledger, posted by real transactions.
What the ledger has no opinion about is the **terms**: the interest rate, the
minimum payment, when it's due. Those aren't financial events, they're the
contract, and they're what a payoff plan is computed from.

So this app stores terms and nothing else. It never posts a journal entry, and
it never stores a balance — that would be a second source of truth for the one
number that must reconcile. Balances are read from the liability account, and
projections are derived on demand, exactly like the cash-flow calendar.

Why `debt_kind` rather than new `AccountType` values: `AccountType` drives the
ledger's asset/liability split, and adding five more liability types would
ripple through net worth, cash flow, and every selector that partitions
accounts. A mortgage and a BNPL plan are both liabilities to the ledger and
differ only in their terms — which is precisely what this model is for.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models

from apps.common.models import SoftDeletableModel


class DebtKind(models.TextChoices):
    """What sort of debt this is.

    Drives defaults and presentation, not accounting. A student loan and a
    vehicle loan post identically; they differ in how people think about them
    and in what a sensible payoff plan looks like.
    """

    CREDIT_CARD = "credit_card", "Credit card"
    MORTGAGE = "mortgage", "Mortgage"
    PERSONAL_LOAN = "personal_loan", "Personal loan"
    STUDENT_LOAN = "student_loan", "Student loan"
    VEHICLE_LOAN = "vehicle loan", "Vehicle loan"
    BNPL = "bnpl", "Buy now, pay later"
    OTHER = "other", "Other debt"


class PayoffStrategy(models.TextChoices):
    """How to order debts when there's spare money to throw at one.

    Both work; they optimise different things, and saying so plainly is more
    useful than picking a winner:

      * `AVALANCHE` — highest rate first. Mathematically optimal: it always
        costs the least in total interest.
      * `SNOWBALL` — smallest balance first. Costs more, but clears individual
        debts sooner, and the evidence that people actually stick with it is
        real. A plan abandoned in month four saves nothing.
      * `CUSTOM` — the user's own order, for when something outranks both (a
        debt to a family member, say).
    """

    AVALANCHE = "avalanche", "Highest rate first"
    SNOWBALL = "snowball", "Smallest balance first"
    CUSTOM = "custom", "Custom order"


class InterestMethod(models.TextChoices):
    """How the interest on a loan is worked out.

    The single most consequential field on a loan, and the one people are most
    often surprised by. On a **reducing balance** loan interest is charged on
    what is still owed, so it falls as the balance does — the arrangement most
    bank loans and every mortgage use. On a **flat rate** loan interest is
    charged on the *original* principal for the whole term, so the same rate
    costs roughly twice as much; it is common in informal and asset-finance
    lending and is usually quoted without saying so.

    Recording which one applies is what lets the payoff planner tell the truth.
    Assuming reducing balance for a flat-rate loan understates its cost for the
    entire term, and the error grows with the term.
    """

    REDUCING = "reducing", "Reducing balance"
    FLAT = "flat", "Flat rate"


class Compounding(models.TextChoices):
    """How often the lender adds interest to the balance.

    Mirrors `payoff.Compounding`. Duplicated deliberately rather than imported:
    the engine must stay free of Django, and this must stay a proper choices
    field. A test asserts the two lists agree, so they cannot drift.
    """

    MONTHLY = "monthly", "Monthly"
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    QUARTERLY = "quarterly", "Quarterly"
    ANNUAL = "annual", "Annual"
    CONTINUOUS = "continuous", "Continuous"


class DebtProfile(SoftDeletableModel):
    """Repayment terms attached to a liability account.

    One-to-one with the account: a debt is the account, and this adds what the
    ledger doesn't model. Deleting the profile leaves the account and its
    history untouched — you stop planning, you don't stop owing.
    """

    financial_account = models.OneToOneField(
        "finance.FinancialAccount", on_delete=models.CASCADE, related_name="debt_profile"
    )
    debt_kind = models.CharField(max_length=20, choices=DebtKind.choices, default=DebtKind.OTHER)

    #: Annual percentage rate, as a percentage (7.5 means 7.5%). Decimal rather
    #: than float: rates are compared and ordered, and float equality on
    #: something like 5.99 is a bug waiting to be filed.
    apr = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0"))

    #: What must be paid each month to stay current. The floor of any plan —
    #: a projection that pays less than this isn't a plan, it's a default.
    minimum_payment_minor = models.BigIntegerField(default=0)

    #: Day of month the payment is due, 1-28. Capped at 28 so it exists in
    #: February — the same reasoning as goal auto-contributions.
    payment_day = models.PositiveSmallIntegerField(null=True, blank=True)

    #: Original principal, where known. Used for progress ("62% paid off"),
    #: which is otherwise unanswerable: a balance alone can't say how far
    #: through you are.
    original_principal_minor = models.BigIntegerField(null=True, blank=True)
    opened_on = models.DateField(null=True, blank=True)

    # --- term ---------------------------------------------------------------
    #: How long the debt runs, in months. Optional, because a credit card has no
    #: term at all — it revolves — and demanding one would mean inventing a
    #: number for the commonest debt there is.
    #:
    #: Stored in months rather than years even though people say "a five-year
    #: loan": 18- and 30-month terms are ordinary, and a fractional year is a
    #: worse thing to store than a whole month. The form asks in years and
    #: multiplies.
    #:
    #: Where it is known it is worth a great deal — with a principal and a rate
    #: it determines the scheduled repayment, so the planner can state what the
    #: debt costs without waiting to observe a payment.
    term_months = models.PositiveSmallIntegerField(null=True, blank=True)

    #: Reducing balance or flat rate. Only meaningful for a term loan; a card
    #: charges on the balance by definition. Defaults to reducing, which is
    #: both the commoner arrangement and the more conservative assumption —
    #: mistaking a flat loan for reducing understates its cost, so the default
    #: errs toward the number the lender is more likely to have quoted.
    interest_method = models.CharField(
        max_length=10, choices=InterestMethod.choices, default=InterestMethod.REDUCING
    )

    # --- revolving credit ---------------------------------------------------
    #: The ceiling on a card or line of credit. Null where there is none, or
    #: none is known. Used for utilisation, which is a real signal about
    #: borrowing headroom that a balance alone cannot give.
    credit_limit_minor = models.BigIntegerField(null=True, blank=True)

    #: Day of the month the statement closes, 1-28. Distinct from
    #: `payment_day`: the statement date decides what lands on the bill, the
    #: due date decides when it must be paid, and they are typically three
    #: weeks apart.
    statement_day = models.PositiveSmallIntegerField(null=True, blank=True)

    #: Some debts are interest-free for a window — BNPL almost always, credit
    #: cards on a promotional rate. After this date `apr` applies.
    promotional_apr_until = models.DateField(null=True, blank=True)
    promotional_apr = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)

    #: Position in a CUSTOM payoff order. Lower is paid first.
    custom_priority = models.PositiveSmallIntegerField(default=100)

    #: How often interest is compounded. Monthly is the common case and the
    #: default, so existing rows keep behaving exactly as they did.
    compounding = models.CharField(max_length=12, choices=Compounding.choices, default=Compounding.MONTHLY)

    # --- fees ---------------------------------------------------------------
    # Charges that cost money without reducing the principal. Kept as separate
    # fields rather than a JSON blob so they can be summed, filtered and
    # reported on without deserialising every row.
    monthly_fee_minor = models.BigIntegerField(default=0)
    annual_fee_minor = models.BigIntegerField(default=0)
    #: Calendar month the annual fee falls in, 1-12.
    annual_fee_month = models.PositiveSmallIntegerField(null=True, blank=True)
    origination_fee_minor = models.BigIntegerField(default=0)

    #: Accounts whose balances reduce the interest-bearing amount without
    #: either balance moving — an offset mortgage arrangement. Many-to-many
    #: because lenders commonly allow several linked accounts.
    offset_accounts = models.ManyToManyField(
        "finance.FinancialAccount", blank=True, related_name="offsetting_debts"
    )

    #: Excluded from plans without being deleted — a mortgage someone has no
    #: intention of overpaying shouldn't distort a credit-card payoff plan.
    include_in_payoff = models.BooleanField(default=True)

    notes = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(apr__gte=0), name="debt_apr_non_negative"),
            models.CheckConstraint(
                condition=models.Q(minimum_payment_minor__gte=0), name="debt_min_non_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(term_months__isnull=True) | models.Q(term_months__gt=0),
                name="debt_term_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(credit_limit_minor__isnull=True) | models.Q(credit_limit_minor__gt=0),
                name="debt_credit_limit_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(statement_day__isnull=True)
                | models.Q(statement_day__gte=1, statement_day__lte=28),
                name="debt_statement_day_in_range",
            ),
            models.CheckConstraint(
                condition=models.Q(payment_day__isnull=True)
                | models.Q(payment_day__gte=1, payment_day__lte=28),
                name="debt_payment_day_range",
            ),
            models.CheckConstraint(
                condition=models.Q(monthly_fee_minor__gte=0)
                & models.Q(annual_fee_minor__gte=0)
                & models.Q(origination_fee_minor__gte=0),
                name="debt_fees_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(annual_fee_month__isnull=True)
                | models.Q(annual_fee_month__gte=1, annual_fee_month__lte=12),
                name="debt_annual_fee_month_range",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "include_in_payoff"], name="debt_payoff_idx"),
            models.Index(fields=["tenant_id", "debt_kind"], name="debt_kind_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.debt_kind} @ {self.apr}%"

    def effective_apr(self, on: object = None) -> Decimal:
        """The rate that actually applies on a date.

        Promotional periods are common enough — and consequential enough — that
        ignoring them would make BNPL and balance-transfer plans wrong by a
        wide margin in exactly the direction that matters.
        """
        from django.utils import timezone

        as_of = on or timezone.localdate()
        if (
            self.promotional_apr is not None
            and self.promotional_apr_until is not None
            and as_of <= self.promotional_apr_until
        ):
            return self.promotional_apr
        return self.apr


class RateSource(models.TextChoices):
    """Where a rate change came from, for auditability.

    A rate the user typed and a rate a lender notified are different kinds of
    fact, and a projection built on the second deserves more confidence than
    one built on the first.
    """

    MANUAL = "manual", "Entered manually"
    STATEMENT = "statement", "From a statement"
    LENDER = "lender", "Lender notification"
    PROMOTIONAL = "promotional", "Promotional period"
    INDEX = "index", "Tracked index change"


class DebtRateHistory(SoftDeletableModel):
    """One rate, effective from a date until the next entry supersedes it.

    Append-only in practice: entries are added as rates change, never edited to
    reflect a new rate. That is what keeps historical calculations stable — a
    projection run last March used the rate that was in force last March, and
    re-running it today must give the same answer.

    Future-dated entries are allowed and are the point of the model: a lender
    notifying a rise in three months lets the payoff plan account for it now
    rather than being surprised by it later.
    """

    profile = models.ForeignKey(DebtProfile, on_delete=models.CASCADE, related_name="rate_history")
    #: The rate applies from this date until the next entry begins.
    effective_from = models.DateField()
    apr = models.DecimalField(max_digits=6, decimal_places=3)
    source = models.CharField(max_length=16, choices=RateSource.choices, default=RateSource.MANUAL)
    notes = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(apr__gte=0), name="rate_history_apr_non_negative"),
            # One rate per debt per day: two rates starting the same morning
            # has no meaning, and picking between them would be arbitrary.
            models.UniqueConstraint(
                fields=["tenant_id", "profile", "effective_from"],
                name="uniq_rate_per_profile_date",
                condition=models.Q(deleted_at__isnull=True),
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "profile", "-effective_from"], name="rate_history_idx"),
        ]
        ordering = ["effective_from"]
        verbose_name_plural = "debt rate histories"

    def __str__(self) -> str:
        return f"{self.apr}% from {self.effective_from}"
