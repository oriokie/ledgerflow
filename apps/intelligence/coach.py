"""Coach service layer — generating, storing, and acting on insights.

The single most important property here is **idempotent generation**. The coach
runs on a schedule, so the same condition is detected every morning. Without a
stable identity per condition the user would wake to a fresh copy of
"you're over budget on groceries" each day, and dismissing one would achieve
nothing at all.

`InsightCandidate.dedupe_key` encodes the condition, not the run. Re-detection
refreshes the existing row — and deliberately does **not** resurrect a
dismissed one. Overriding a user's dismissal is how a product teaches people to
stop reading it.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.common.outbox import OutboxEvent

from . import coach_context, scoring
from .models import Briefing, BriefingPeriod, Insight, InsightStatus
from .protocols import CoachContext, InsightCandidate
from .registry import get_insight_provider, get_narrative_provider
from .providers.coach import RuleBasedCoach, TemplateNarrator


def _tenant_ai_enabled() -> bool:
    """Whether the current tenant has opted in to AI-touched insights and
    narration. `True` when there's no bound tenant (a script, a management
    command) so nothing outside a request context silently downgrades."""
    from apps.common.tenant_context import get_current_tenant_id
    from apps.tenancy.models import Tenant

    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        return True
    value = Tenant.objects.filter(id=tenant_id).values_list("ai_enabled", flat=True).first()
    # `None` means no tenant row was found at all (shouldn't happen with a
    # bound id, but the safe default is "on" — matching every existing
    # workspace's behaviour before this flag existed — not a silent downgrade).
    return True if value is None else value


class CoachError(Exception): ...


#: Statuses that mean "the user has already decided about this". A re-detection
#: refreshes the evidence but never drags the insight back into the feed.
_USER_DECIDED = {InsightStatus.DISMISSED, InsightStatus.ACTED}


def _jsonable(value):
    """Make a value safe for a JSONField.

    Evidence dicts are assembled from engine reads, which legitimately contain
    `date` objects — a projected overdraft date, a bill due date. JSONField
    can't serialise those, and the failure surfaces at save time rather than at
    the point the value was added, so it's converted centrally here.
    """
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _amount_from_evidence(candidate: InsightCandidate) -> int | None:
    """Best available "how much is at stake" figure, for scoring.

    Reads a small set of known evidence keys rather than guessing at any
    numeric field: scoring off an arbitrary number in an opaque dict is how a
    percentage ends up being treated as an amount.
    """
    for key in ("over_minor", "amount_minor", "total_minor", "annual_total_minor", "spent_minor"):
        value = candidate.evidence.get(key)
        if isinstance(value, int):
            return value
    return None


def _due_from_candidate(candidate: InsightCandidate) -> date | None:
    if candidate.expires_on:
        return candidate.expires_on
    first_negative = candidate.evidence.get("first_negative_on")
    return first_negative if isinstance(first_negative, date) else None


@transaction.atomic
def generate_insights(*, as_of: date | None = None, context: CoachContext | None = None) -> list[Insight]:
    """Run the configured provider and persist the results.

    Returns every live insight touched by this run — created or refreshed —
    so a caller can build a briefing from exactly what was just detected.
    """
    as_of = as_of or timezone.localdate()
    context = context or coach_context.build_context(as_of=as_of)
    # A tenant that has opted out of AI gets the deterministic provider
    # directly, regardless of what the deployment has configured — provider
    # selection in the registry is a settings-only, deployment-wide seam (see
    # registry.py), so a per-tenant override has to happen here, at the one
    # call site that actually knows which tenant this run is for.
    provider = get_insight_provider() if _tenant_ai_enabled() else RuleBasedCoach()
    baseline = coach_context.monthly_baseline_minor(context.currency)

    touched: list[Insight] = []
    for candidate in provider.generate(context):
        score = scoring.score_insight(
            severity=candidate.severity,
            as_of=as_of,
            amount_minor=_amount_from_evidence(candidate),
            monthly_baseline_minor=baseline,
            due_on=_due_from_candidate(candidate),
            confidence=candidate.confidence,
        )
        prov = candidate.provenance

        existing = Insight.objects.filter(dedupe_key=candidate.dedupe_key).first()
        if existing is not None:
            # Refresh the evidence — the figures move even when the condition
            # doesn't — but leave a decided insight decided.
            existing.title = candidate.title
            existing.body = candidate.body
            existing.rationale = candidate.rationale
            existing.evidence = _jsonable(candidate.evidence)
            existing.action = _jsonable(candidate.action)
            existing.priority_score = score
            existing.expires_on = candidate.expires_on
            existing.last_detected_at = timezone.now()
            existing.save(
                update_fields=[
                    "title",
                    "body",
                    "rationale",
                    "evidence",
                    "action",
                    "priority_score",
                    "expires_on",
                    "last_detected_at",
                    "updated_at",
                ]
            )
            if existing.status not in _USER_DECIDED:
                touched.append(existing)
            continue

        insight = Insight.objects.create(
            kind=candidate.kind,
            severity=candidate.severity,
            title=candidate.title,
            body=candidate.body,
            rationale=candidate.rationale,
            evidence=_jsonable(candidate.evidence),
            action=_jsonable(candidate.action),
            priority_score=score,
            dedupe_key=candidate.dedupe_key,
            period_start=candidate.period_start,
            period_end=candidate.period_end,
            expires_on=candidate.expires_on,
            provider=getattr(prov, "provider", "unknown"),
            provider_kind=getattr(prov, "kind", "rule"),
            provider_version=getattr(prov, "version", "0"),
            related_transaction_id=candidate.related_transaction_id,
            related_category_id=candidate.related_category_id,
            related_account_id=candidate.related_account_id,
            last_detected_at=timezone.now(),
        )
        OutboxEvent.objects.create(
            tenant_id=insight.tenant_id,
            aggregate_type="intelligence.Insight",
            aggregate_id=insight.id,
            event_type="intelligence.insight.created",
            payload={"kind": insight.kind, "severity": insight.severity, "score": score},
        )
        touched.append(insight)

    return sorted(touched, key=lambda i: -i.priority_score)


def live_insights(*, as_of: date | None = None, limit: int | None = None):
    """The feed: undecided, unexpired insights, most important first.

    Bookmarked insights are included deliberately — a bookmark means "keep this
    in front of me", which is the opposite of a dismissal.
    """
    as_of = as_of or timezone.localdate()
    qs = (
        Insight.objects.exclude(status__in=_USER_DECIDED)
        .filter(models_expired_filter(as_of))
        .order_by("-priority_score", "-created_at")
    )
    return qs[:limit] if limit else qs


def models_expired_filter(as_of: date):
    """`expires_on` is null (evergreen) or still in the future."""
    from django.db.models import Q

    return Q(expires_on__isnull=True) | Q(expires_on__gte=as_of)


@transaction.atomic
def set_insight_status(*, insight: Insight, status: str) -> Insight:
    """Record the user's decision about an insight."""
    if status not in InsightStatus.values:
        raise CoachError(f"Unknown insight status {status!r}.")
    insight.status = status
    insight.decided_at = timezone.now()
    insight.save(update_fields=["status", "decided_at", "updated_at"])
    return insight


def dismiss_insight(*, insight: Insight) -> Insight:
    return set_insight_status(insight=insight, status=InsightStatus.DISMISSED)


def bookmark_insight(*, insight: Insight) -> Insight:
    return set_insight_status(insight=insight, status=InsightStatus.BOOKMARKED)


#: Window covered by each briefing period.
_PERIOD_DAYS = {BriefingPeriod.DAILY: 1, BriefingPeriod.WEEKLY: 7, BriefingPeriod.MONTHLY: 30}


@transaction.atomic
def generate_briefing(*, period: str, as_of: date | None = None) -> Briefing:
    """Produce (or refresh) the narrative review for a period.

    Unique per (tenant, period, period_start), so a re-run updates rather than
    duplicates — the same discipline as insight dedupe. A user who opens their
    daily briefing twice should see one briefing.
    """
    if period not in BriefingPeriod.values:
        raise CoachError(f"Unknown briefing period {period!r}.")

    as_of = as_of or timezone.localdate()
    span = _PERIOD_DAYS[period]
    period_start = as_of - timedelta(days=span - 1)

    context = coach_context.build_context(as_of=as_of)
    insights = generate_insights(as_of=as_of, context=context)

    # The narrator writes from candidates, so it sees the same shape whether
    # the insights came from this run or a stored feed.
    candidates = [
        InsightCandidate(
            kind=i.kind,
            severity=i.severity,
            title=i.title,
            body=i.body,
            rationale=i.rationale,
            dedupe_key=i.dedupe_key,
            evidence=i.evidence,
        )
        for i in insights
    ]
    narrator = get_narrative_provider() if _tenant_ai_enabled() else TemplateNarrator()
    draft = narrator.write_briefing(
        period=period, context=context, insights=candidates
    )

    briefing, _ = Briefing.objects.update_or_create(
        period=period,
        period_start=period_start,
        defaults={
            "period_end": as_of,
            "headline": draft.headline,
            "summary": draft.summary,
            "metrics": _jsonable(draft.metrics),
            "provider": getattr(draft.provenance, "provider", "unknown"),
            "provider_kind": getattr(draft.provenance, "kind", "rule"),
            "provider_version": getattr(draft.provenance, "version", "0"),
        },
    )
    briefing.insights.set(insights)
    return briefing


def purge_expired_insights(*, as_of: date | None = None) -> int:
    """Remove insights whose window has closed.

    Hard delete rather than soft: an expired insight is noise, not history, and
    the briefings that referenced it keep their own prose and metrics.
    """
    as_of = as_of or timezone.localdate()
    deleted, _ = Insight.objects.filter(expires_on__lt=as_of).delete()
    return deleted
