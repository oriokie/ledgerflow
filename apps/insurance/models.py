"""Insurance — the contracts that sit between a household and a loss.

A policy is not a ledger construct. Recording that a house is insured for eight
million does not move money, and posting a premium here would invent a second
source of truth next to the bill or standing order that actually pays it.

So this module stores the *agreement* — cover, deductible, premium, what it
protects — and never writes a journal entry. Premiums already on a bill or a
recurring template are linked, not duplicated. Unlinked premiums can be shown
on the cash-flow stack; linked ones must not, or rent-and-insurance counted
twice invents an overdraft.

Cover versus the latest valuation of a linked asset is computed on read. That
is the figure that was missing: worth 8m, insured for 4m, *the gap is 4m*.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import SoftDeletableModel


class PolicyKind(models.TextChoices):
    """What the policy is for.

    Drives the questions worth asking (does it cover the house? the car? a
    life?) rather than the arithmetic. Cover is cover; kinds differ in what
    they are allowed to point at.
    """

    LIFE = "life", "Life"
    HEALTH = "health", "Health"
    MOTOR = "motor", "Motor"
    HOME = "home", "Home"
    LIABILITY = "liability", "Liability"
    OTHER = "other", "Something else"


class PremiumFrequency(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    ANNUAL = "annual", "Annually"


#: How many premiums fall in a year. Used to annualise, and to turn an annual
#: figure back into a monthly run-rate for the cash-flow stack.
PAYMENTS_PER_YEAR: dict[str, int] = {
    PremiumFrequency.MONTHLY: 12,
    PremiumFrequency.QUARTERLY: 4,
    PremiumFrequency.ANNUAL: 1,
}


class InsurancePolicy(SoftDeletableModel):
    """One contract."""

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=PolicyKind.choices, default=PolicyKind.OTHER)
    insurer = models.CharField(max_length=120, blank=True, default="")
    currency = models.CharField(max_length=3)

    #: Sum insured. Null when the user knows they pay a premium and has not
    #: yet looked up the cover — a common state, and not the same as cover of
    #: zero, which would claim the policy pays nothing.
    coverage_minor = models.BigIntegerField(null=True, blank=True)
    deductible_minor = models.BigIntegerField(null=True, blank=True)

    premium_minor = models.BigIntegerField()
    premium_frequency = models.CharField(
        max_length=12, choices=PremiumFrequency.choices, default=PremiumFrequency.ANNUAL
    )

    renews_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)

    covers_asset = models.ForeignKey(
        "assets.Asset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="insurance_policies",
        help_text="The house, car or other asset this policy covers.",
    )
    covers_account = models.ForeignKey(
        "finance.FinancialAccount",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="insurance_policies",
        help_text="A loan this policy is written against — a motor policy on a car loan.",
    )

    #: When set, the premium already moves as this bill. The cash-flow stack
    #: must not also inject the policy's premium, or the same outflow is
    #: counted twice.
    bill = models.OneToOneField(
        "finance.Bill",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="insurance_policy",
    )
    recurring_transaction = models.OneToOneField(
        "finance.RecurringTransaction",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="insurance_policy",
    )

    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(premium_minor__gt=0), name="insurance_premium_positive"),
            models.CheckConstraint(
                condition=models.Q(coverage_minor__isnull=True) | models.Q(coverage_minor__gte=0),
                name="insurance_coverage_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(deductible_minor__isnull=True) | models.Q(deductible_minor__gte=0),
                name="insurance_deductible_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(ends_on__isnull=True)
                | models.Q(renews_on__isnull=True)
                | models.Q(ends_on__gte=models.F("renews_on")),
                name="insurance_ends_after_renewal",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "is_active"], name="insurance_active_idx"),
            models.Index(fields=["tenant_id", "kind"], name="insurance_kind_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} ({self.kind})"
