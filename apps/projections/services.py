"""Scenario management, and the binding of a saved scenario to the engine.

The write side of Phase 1. Everything here is a service function taking plain
arguments and returning models or dataclasses — no request objects, no
serialisers — so the API layer stays a thin translation and the same operations
are callable from a management command, a Celery task, or Phase 2's reasoning
layer without pretending to be HTTP.

**Running a scenario is a read.** `run` writes nothing: no cached result, no
snapshot row, no ledger entry. That is a deliberate cost. Caching a projection
would be easy and would make the dashboard faster, but a stale forecast is
worse than a slow one — the whole value of the thing is that it reflects the
position *now*, and a user who changes a debt and sees the old answer has been
lied to. The same reasoning `cashflow_calendar` gives for not caching applies
here with more force, because these numbers reach further out.

**Comparison is symmetric.** `compare` runs both scenarios through the same
code path with the same position and the same assumptions where they are
shared. Neither leg is ever derived from the other by adjustment. This is the
discipline the existing `analytics.scenarios` module already holds itself to,
and it matters more here because the differences are larger and less obviously
wrong when they are wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.utils import timezone

from . import adapters
from .engine import CompiledEvent, EconomicAssumptions, FinancialPosition, ProjectionResult, project
from .events import EventParamError, compile_event
from .models import AssumptionSet, Scenario, ScenarioEvent, ScenarioStatus, ScenarioVisibility


class ScenarioError(Exception):
    """A scenario operation that cannot be completed as asked."""


# ---------------------------------------------------------------------------
# assumption sets
# ---------------------------------------------------------------------------
#: The backdrop a workspace gets before anyone has an opinion. Chosen to be
#: unremarkable and slightly pessimistic: salary growth below inflation, a
#: return assumption at the conservative end of the long-run equity range.
DEFAULT_ASSUMPTIONS = {
    "annual_inflation": "0.0500",
    "annual_salary_growth": "0.0300",
    "annual_investment_return": "0.0700",
    "annual_cash_return": "0.0000",
    "effective_tax_rate": "0.0000",
    "annual_property_growth": "0.0400",
}


def ensure_default_assumption_set() -> AssumptionSet:
    """The workspace's default backdrop, created on first use.

    Created lazily rather than by a data migration because a migration would
    have to run per tenant and tenants arrive continuously.
    """
    existing = AssumptionSet.objects.filter(is_default=True).first()
    if existing is not None:
        return existing
    return AssumptionSet.objects.create(
        name="Default assumptions",
        is_default=True,
        notes="Starting assumptions. Change these once and every scenario follows.",
        **DEFAULT_ASSUMPTIONS,
    )


def to_engine_assumptions(assumption_set: AssumptionSet | None) -> EconomicAssumptions:
    """Decimal settings to engine floats, at the boundary and nowhere else."""
    if assumption_set is None:
        return EconomicAssumptions()
    return EconomicAssumptions(
        annual_inflation=float(assumption_set.annual_inflation),
        annual_salary_growth=float(assumption_set.annual_salary_growth),
        annual_investment_return=float(assumption_set.annual_investment_return),
        annual_cash_return=float(assumption_set.annual_cash_return),
        effective_tax_rate=float(assumption_set.effective_tax_rate),
        annual_property_growth=float(assumption_set.annual_property_growth),
    )


@transaction.atomic
def update_assumption_set(assumption_set: AssumptionSet, **fields) -> AssumptionSet:
    allowed = set(DEFAULT_ASSUMPTIONS) | {"name", "notes"}
    unknown = set(fields) - allowed
    if unknown:
        raise ScenarioError(f"unknown assumption field(s): {sorted(unknown)}")
    for key, value in fields.items():
        setattr(assumption_set, key, value)
    assumption_set.full_clean(exclude=["tenant_id", "created_by", "updated_by"])
    assumption_set.save()
    return assumption_set


# ---------------------------------------------------------------------------
# scenario CRUD
# ---------------------------------------------------------------------------
@transaction.atomic
def create_scenario(
    *,
    name: str,
    description: str = "",
    horizon_months: int = 120,
    assumption_set: AssumptionSet | None = None,
    visibility: str = ScenarioVisibility.PRIVATE,
    status: str = ScenarioStatus.DRAFT,
) -> Scenario:
    scenario = Scenario(
        name=name,
        description=description,
        horizon_months=horizon_months,
        assumption_set=assumption_set or ensure_default_assumption_set(),
        visibility=visibility,
        status=status,
    )
    scenario.full_clean(exclude=["tenant_id", "created_by", "updated_by"])
    scenario.save()
    return scenario


@transaction.atomic
def add_event(
    *,
    scenario: Scenario,
    kind: str,
    params: dict | None = None,
    start_month: int = 1,
    label: str = "",
    sort_order: int | None = None,
) -> ScenarioEvent:
    """Attach a life event. Parameters are validated by the model's `clean()`,
    so an event that the engine would refuse never reaches the database."""
    if start_month > scenario.horizon_months:
        raise ScenarioError(
            f"an event in month {start_month} falls outside this scenario's "
            f"{scenario.horizon_months}-month window"
        )
    if sort_order is None:
        sort_order = ScenarioEvent.objects.filter(scenario=scenario).count()
    event = ScenarioEvent(
        scenario=scenario,
        kind=kind,
        params=params or {},
        start_month=start_month,
        label=label,
        sort_order=sort_order,
    )
    event.save()  # full_clean runs inside save(); see models.ScenarioEvent
    return event


@transaction.atomic
def duplicate_scenario(scenario: Scenario, *, name: str | None = None) -> Scenario:
    """Copy a scenario and its events.

    The copy starts as a draft regardless of the original's status: a duplicate
    is by definition something being worked on, and inheriting `ACTIVE` would
    quietly add a second "current plan" to the workspace.
    """
    copy = Scenario(
        name=name or _unique_name(f"{scenario.name} (copy)"),
        description=scenario.description,
        horizon_months=scenario.horizon_months,
        assumption_set=scenario.assumption_set,
        visibility=scenario.visibility,
        status=ScenarioStatus.DRAFT,
        duplicated_from=scenario,
    )
    copy.full_clean(exclude=["tenant_id", "created_by", "updated_by"])
    copy.save()

    for event in scenario.events.all():
        ScenarioEvent(
            scenario=copy,
            kind=event.kind,
            label=event.label,
            start_month=event.start_month,
            params=dict(event.params),
            is_enabled=event.is_enabled,
            sort_order=event.sort_order,
        ).save()
    return copy


def _unique_name(candidate: str) -> str:
    """Names are unique per tenant, and "(copy)" collides on the second copy."""
    name = candidate
    suffix = 2
    while Scenario.objects.filter(name=name).exists():
        name = f"{candidate} {suffix}"
        suffix += 1
    return name


@transaction.atomic
def archive_scenario(scenario: Scenario) -> Scenario:
    scenario.status = ScenarioStatus.ARCHIVED
    scenario.save(update_fields=["status", "updated_at"])
    return scenario


@transaction.atomic
def set_visibility(scenario: Scenario, visibility: str) -> Scenario:
    if visibility not in ScenarioVisibility.values:
        raise ScenarioError(f"unknown visibility: {visibility!r}")
    scenario.visibility = visibility
    scenario.save(update_fields=["visibility", "updated_at"])
    return scenario


# ---------------------------------------------------------------------------
# running a scenario
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ScenarioRun:
    scenario_id: str
    scenario_name: str
    baseline: ProjectionResult
    scenario: ProjectionResult
    #: Plain-language notes about what the comparison does and does not say.
    notes: list[str]

    @property
    def net_worth_delta_minor(self) -> int:
        return self.scenario.closing_net_worth_minor - self.baseline.closing_net_worth_minor

    @property
    def trough_delta_minor(self) -> int:
        return self.scenario.lowest_liquid_minor - self.baseline.lowest_liquid_minor


def compile_scenario_events(
    scenario: Scenario, position: FinancialPosition, assumptions: EconomicAssumptions
) -> list[CompiledEvent]:
    compiled: list[CompiledEvent] = []
    for event in scenario.events.filter(is_enabled=True):
        try:
            compiled.extend(
                compile_event(
                    kind=event.kind,
                    start_month=event.start_month,
                    params=event.params or {},
                    position=position,
                    assumptions=assumptions,
                    label=event.label,
                )
            )
        except EventParamError as exc:
            raise ScenarioError(f"{scenario.name}: {exc}") from exc
    return compiled


def run(
    scenario: Scenario, *, as_of: date | None = None, position: FinancialPosition | None = None
) -> ScenarioRun:
    """Project the scenario, and the same position with no events, side by side.

    Both legs go through `engine.project` with identical inputs bar the events.
    That is the whole design: the difference between the two lines is caused by
    the scenario and by nothing else.
    """
    as_of = as_of or timezone.localdate()
    position = position or adapters.current_position(as_of=as_of)
    assumptions = to_engine_assumptions(scenario.assumption_set)
    months = scenario.horizon_months

    baseline = project(position=position, assumptions=assumptions, events=[], months=months)
    events = compile_scenario_events(scenario, position, assumptions)
    projected = project(position=position, assumptions=assumptions, events=events, months=months)

    notes = [
        "The baseline is this same position with the scenario's events removed — "
        "both lines run through the same arithmetic.",
        "Balances are nominal; recurring amounts are entered in today's money and grown.",
    ]
    if not events:
        notes.append("This scenario has no enabled events, so both lines are identical.")

    return ScenarioRun(
        scenario_id=str(scenario.id),
        scenario_name=scenario.name,
        baseline=baseline,
        scenario=projected,
        notes=notes,
    )


@dataclass(frozen=True)
class ScenarioComparison:
    as_of: date
    currency: str
    runs: list[ScenarioRun]
    notes: list[str]


def compare(scenarios: list[Scenario], *, as_of: date | None = None) -> ScenarioComparison:
    """Run several scenarios against one shared snapshot of the position.

    The snapshot is taken *once* and handed to every leg. Re-reading it per
    scenario would let a balance change mid-comparison and produce a ranking
    that reflects timing rather than the decisions being compared.
    """
    if not scenarios:
        raise ScenarioError("nothing to compare")
    as_of = as_of or timezone.localdate()
    position = adapters.current_position(as_of=as_of)

    runs = [run(scenario, as_of=as_of, position=position) for scenario in scenarios]
    notes = [
        "Every scenario is measured against the same snapshot of your position, "
        "taken once so the ranking reflects the decisions and not the clock.",
    ]
    distinct_assumptions = {s.assumption_set_id for s in scenarios if s.assumption_set_id is not None}
    if len(distinct_assumptions) > 1:
        notes.append(
            "These scenarios do not share an assumption set, so part of the difference "
            "between them is a difference of opinion about inflation and returns, not of plan."
        )
    return ScenarioComparison(as_of=as_of, currency=position.currency, runs=runs, notes=notes)
