"""Scenarios, their events, and the economic assumptions they run under.

Three models, and the split between them is the important part:

``AssumptionSet``
    The economic backdrop — inflation, salary growth, returns, tax. Separate
    from the scenario because it is the thing a household argues about *once*
    and then reuses. When someone changes their inflation view from 5% to 8%,
    every scenario should move; if the numbers were copied onto each scenario
    they would not, and half the saved scenarios would quietly be answering a
    question nobody is asking any more.

``Scenario``
    A named what-if. Owns nothing financial itself — it points at an assumption
    set and holds a list of events. Deliberately cheap to create, duplicate and
    throw away, because the product's promise is that modelling a decision
    costs nothing and touches no real data.

``ScenarioEvent``
    One life event, as a kind plus a JSON parameter bag. The parameters are
    validated against `events.EVENT_PARAMS` on save rather than being trusted,
    so a scenario cannot persist in a state the engine will refuse to run.

**Nothing here writes to the ledger, ever.** A scenario is a lens, not a
transaction. That is what makes it safe to let people model losing their job
without it touching the record of what actually happened.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import SoftDeletableModel

from .calculators import MAX_HORIZON_MONTHS
from .events import EVENT_LABELS, EventKind, EventParamError, validate_params


class ScenarioStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class ScenarioVisibility(models.TextChoices):
    """Who in the workspace can see a scenario.

    `PRIVATE` is the default on purpose. People model things they are not ready
    to discuss — leaving a job, a divorce, whether they can afford to help a
    parent — and a planner that shares those by default is one people will not
    tell the truth to. Phase 3 extends this into full household permissions;
    the two values here are what Phase 1 needs to not paint itself into a
    corner.
    """

    PRIVATE = "private", "Only me"
    HOUSEHOLD = "household", "Shared with the household"


#: Mirrored from `events.EventKind`, which is deliberately Django-free so the
#: compiler stays importable without the app registry. A test pins the two
#: together so they cannot drift.
EVENT_KIND_CHOICES = [(kind, EVENT_LABELS[kind]) for kind in EventKind.all()]


class AssumptionSet(SoftDeletableModel):
    """A reusable economic backdrop.

    Rates are stored as fractions (0.05 for 5%) in a Decimal, not a float:
    these are user-facing settings that get displayed, edited and compared, and
    float round-tripping turns 0.07 into 0.06999999999999999 in a form field.
    The engine takes floats, so conversion happens at the boundary.
    """

    name = models.CharField(max_length=120)
    is_default = models.BooleanField(default=False)

    annual_inflation = models.DecimalField(max_digits=6, decimal_places=4, default="0.0500")
    annual_salary_growth = models.DecimalField(max_digits=6, decimal_places=4, default="0.0300")
    annual_investment_return = models.DecimalField(max_digits=6, decimal_places=4, default="0.0700")
    annual_cash_return = models.DecimalField(max_digits=6, decimal_places=4, default="0.0000")
    effective_tax_rate = models.DecimalField(max_digits=6, decimal_places=4, default="0.0000")
    annual_property_growth = models.DecimalField(max_digits=6, decimal_places=4, default="0.0400")

    #: Why these numbers. An assumption without a rationale is a number nobody
    #: can revisit six months later.
    notes = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "name"],
                name="uniq_assumption_set_name",
                condition=models.Q(deleted_at__isnull=True),
            ),
            # One default per tenant, enforced in the database rather than by
            # convention — two defaults means the engine picks arbitrarily and
            # projections change between requests.
            models.UniqueConstraint(
                fields=["tenant_id"],
                name="uniq_default_assumption_set",
                condition=models.Q(is_default=True, deleted_at__isnull=True),
            ),
        ]
        indexes = [models.Index(fields=["tenant_id", "is_default"], name="assumption_default_idx")]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name


class Scenario(SoftDeletableModel):
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True, default="")
    status = models.CharField(max_length=12, choices=ScenarioStatus.choices, default=ScenarioStatus.DRAFT)
    visibility = models.CharField(
        max_length=12, choices=ScenarioVisibility.choices, default=ScenarioVisibility.PRIVATE
    )
    horizon_months = models.PositiveSmallIntegerField(default=120)
    assumption_set = models.ForeignKey(
        AssumptionSet, null=True, blank=True, on_delete=models.SET_NULL, related_name="scenarios"
    )
    #: Lineage for duplicates. Kept so "compare against the one I copied this
    #: from" is answerable without the user remembering which that was.
    duplicated_from = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="duplicates"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "name"],
                name="uniq_scenario_name",
                condition=models.Q(deleted_at__isnull=True),
            ),
            models.CheckConstraint(
                condition=models.Q(horizon_months__gte=1, horizon_months__lte=MAX_HORIZON_MONTHS),
                name="scenario_horizon_in_range",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "status"], name="scenario_status_idx"),
            models.Index(fields=["tenant_id", "visibility"], name="scenario_visibility_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name


class ScenarioEvent(SoftDeletableModel):
    """One life event inside a scenario.

    `params` is a JSON bag rather than fifty nullable columns because the
    fifteen kinds genuinely have little in common — a child has a support
    duration, a mortgage has a rate, a relocation has neither. The schema lives
    in `events.EVENT_PARAMS` and is enforced in `clean()`, so the flexibility
    does not cost validation.
    """

    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=32, choices=EVENT_KIND_CHOICES)
    label = models.CharField(max_length=120, blank=True, default="")
    #: 1-based month within the projection window at which the event begins.
    start_month = models.PositiveSmallIntegerField(default=1)
    params = models.JSONField(default=dict, blank=True)
    #: Lets a user mute one leg of a scenario without deleting it — the "what
    #: if we skipped the car" question, asked without losing the car.
    is_enabled = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_month__gte=1, start_month__lte=MAX_HORIZON_MONTHS),
                name="scenario_event_start_in_range",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "scenario"], name="scenario_event_idx"),
        ]
        ordering = ["sort_order", "start_month"]

    def clean(self) -> None:
        """Reject parameters the engine would refuse, at the point of save.

        A scenario that cannot be projected is worse than one that cannot be
        saved: the user finds out later, from a dashboard that renders an
        error where a number should be.
        """
        super().clean()
        try:
            validate_params(self.kind, self.params or {})
        except EventParamError as exc:
            raise ValidationError({"params": str(exc)}) from exc

    def save(self, *args, **kwargs):
        self.full_clean(exclude=[f.name for f in self._meta.fields if f.name != "params"])
        return super().save(*args, **kwargs)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.label or EVENT_LABELS.get(self.kind, self.kind)
