"""Intelligence API — exposes the AI providers that were previously wired to
nothing (P0-4 in the review). Suggestions, health score, recommendations,
anomalies, and automation-rule CRUD. Every read composes provider output from
real engine data via the selectors; every write validates automation actions
against the allow-list before saving.
"""

from __future__ import annotations

from dataclasses import asdict

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api_base import TenantScopedAPIView, WriteRequiresMemberMixin
from apps.common.cache import cached_analytics
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import automation_services, coach, registry, selectors, services
from ..automation import AutomationError, validate_actions
from ..models import (
    AutomationRule,
    BriefingPeriod,
    CategorizationSuggestion,
    Insight,
    InsightStatus,
)
from .serializers import (
    AutomationRuleSerializer,
    AutomationRuleWriteSerializer,
    CategorizationSuggestionSerializer,
)


class HasAIInsights(BasePermission):
    """Allows access only when the tenant's plan includes AI insights. Raises
    PlanLimitExceeded (→ 402) rather than a bare 403 so the client can prompt an
    upgrade. Runs after IsTenantMember, so request.tenant_id is resolved."""

    def has_permission(self, request, view) -> bool:
        from apps.billing.entitlements import ensure_ai_insights

        tenant_id = getattr(request, "tenant_id", None)
        if tenant_id is not None:
            ensure_ai_insights(tenant_id=tenant_id)  # raises PlanLimitExceeded if not entitled
        return True


@cached_analytics("health_score", ttl=300)
def _compute_health_score() -> dict:
    result = registry.get_health_scorer().score(selectors.build_health_inputs())
    return {
        "score": result.score,
        "band": result.band,
        "components": [asdict(c) for c in result.components],
        "provider": result.provenance.provider,
        "version": result.provenance.version,
    }


@cached_analytics("recommendations", ttl=300)
def _compute_recommendations() -> list:
    recs = registry.get_recommender().recommend(selectors.build_recommendation_context())
    return [
        {"kind": r.kind.value, "title": r.title, "body": r.body, "severity": r.severity, "action": r.action}
        for r in recs
    ]


@cached_analytics("anomalies", ttl=600)
def _compute_anomalies() -> list:
    from .. import services as intel_services

    anomalies = registry.get_anomaly_detector().detect(selectors.build_amount_observations())
    out = [
        {
            "transaction_id": a.transaction_id,
            "kind": a.kind.value,
            "severity": a.severity,
            "explanation": a.explanation,
        }
        for a in anomalies
    ]
    # schedule-based detections (expected recurring charges that didn't arrive)
    # are merged in here — same response, distinct `kind`.
    for m in intel_services.detect_missed_recurring():
        out.append(
            {
                "transaction_id": None,
                "kind": m["kind"],
                "severity": 0.5,
                "explanation": m["explanation"],
            }
        )
    return out


@cached_analytics("forecast", ttl=600)
def _compute_forecast() -> dict:
    from .. import services as intel_services

    result = intel_services.forecast(months_history=6, periods_ahead=3)
    return {
        "points": [
            {
                "period_start": p.period_start.isoformat(),
                "projected_expense_minor": p.projected_expense_minor,
                "low_minor": p.low_minor,
                "high_minor": p.high_minor,
            }
            for p in result.points
        ],
        "provider": result.provenance.provider,
        "version": result.provenance.version,
    }


class _HealthScoreResponse(serializers.Serializer):
    score = serializers.IntegerField()
    band = serializers.CharField()
    components = serializers.ListField(child=serializers.DictField())
    provider = serializers.CharField()
    version = serializers.CharField()


class _RecommendationResponse(serializers.Serializer):
    kind = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField()
    severity = serializers.CharField()
    action = serializers.DictField()


class _AnomalyResponse(serializers.Serializer):
    transaction_id = serializers.CharField()
    kind = serializers.CharField()
    severity = serializers.FloatField()
    explanation = serializers.CharField()


class SuggestionListView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, HasAIInsights]
    required_role = Role.VIEWER

    @extend_schema(responses=CategorizationSuggestionSerializer(many=True))
    def get(self, request):
        qs = CategorizationSuggestion.objects.all().order_by("-created_at")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return Response(CategorizationSuggestionSerializer(qs[:200], many=True).data)


class SuggestionDecisionView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, HasAIInsights]

    @extend_schema(request=None, responses=CategorizationSuggestionSerializer)
    def post(self, request, suggestion_id, decision):
        suggestion = CategorizationSuggestion.objects.filter(id=suggestion_id).first()
        if suggestion is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if decision == "accept":
            try:
                services.accept_suggestion(suggestion)
            except services.finance_services.FinanceError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        elif decision == "reject":
            services.reject_suggestion(suggestion)
        else:
            return Response({"detail": "decision must be accept or reject"}, status=400)
        suggestion.refresh_from_db()
        return Response(CategorizationSuggestionSerializer(suggestion).data)


class HealthScoreView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, HasAIInsights]
    required_role = Role.VIEWER

    @extend_schema(responses=_HealthScoreResponse)
    def get(self, request):
        return Response(_compute_health_score())


class RecommendationsView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, HasAIInsights]
    required_role = Role.VIEWER

    @extend_schema(responses=_RecommendationResponse(many=True))
    def get(self, request):
        return Response(_compute_recommendations())


class AnomaliesView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, HasAIInsights]
    required_role = Role.VIEWER

    @extend_schema(responses=_AnomalyResponse(many=True))
    def get(self, request):
        return Response(_compute_anomalies())


class ForecastView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, HasAIInsights]
    required_role = Role.VIEWER
    serializer_class = None

    def get(self, request):
        return Response(_compute_forecast())


class NetWorthHistoryView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    def get(self, request):
        months = request.query_params.get("months")
        months = int(months) if (months and months.isdigit()) else 12
        months = max(1, min(months, 36))
        return Response(selectors.net_worth_history(months=months))


class MilestonesView(TenantScopedAPIView, APIView):
    """Financial milestones — dated facts, reconstructed from the ledger.

    Not a rewards feed. Nothing here is stored, nothing can be lost, and there
    is no next tier to chase; if the ledger says it happened it is reported,
    and if it does not the response is simply empty.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="intelligence_milestones")
    def get(self, request):
        from apps.finance.selectors import net_worth

        from ..milestones import milestones

        # 36 months: enough to date a milestone properly, and the same ceiling
        # the history endpoint enforces.
        history = selectors.net_worth_history(months=36)
        totals = net_worth()
        currency = totals[0].currency if totals else ""

        return Response(
            [
                {
                    "key": m.key,
                    "title": m.title,
                    "detail": m.detail,
                    "achieved_on": m.achieved_on,
                    "amount_minor": m.amount_minor,
                    "currency": m.currency,
                }
                for m in milestones(history=history, currency=currency)
            ]
        )


class AskView(TenantScopedAPIView, APIView):
    """Turn a natural-language question into an executable ledger filter.

    Returns a *query*, never an answer. The client applies it to the ordinary
    transactions endpoint, so the figures are computed by the same code path as
    every other view and the user can see — and edit — exactly what was
    searched. See `apps/intelligence/ask.py` for why that shape was chosen over
    a prose reply.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="intelligence_ask")
    def post(self, request):
        from apps.finance.models import Category

        from ..ask import interpret

        question = (request.data or {}).get("question", "")
        if not isinstance(question, str):
            return Response({"query": None, "explanation": ""})

        names = list(Category.objects.values_list("name", flat=True)[:200])
        result = interpret(question, categories=names)
        if result is None:
            return Response({"query": None, "explanation": ""})

        return Response(
            {
                "query": result.as_params(),
                "explanation": result.explanation,
                "from_rules": result.from_rules,
            }
        )


class SpendingTrendView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    def get(self, request):
        months = request.query_params.get("months")
        months = int(months) if (months and months.isdigit()) else 6
        months = max(1, min(months, 36))
        return Response(selectors.spending_trend(months=months))


class AutomationRuleListView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, HasAIInsights]

    @extend_schema(responses=AutomationRuleSerializer(many=True))
    def get(self, request):
        rules = AutomationRule.objects.filter(is_active=True).order_by("priority", "id")
        return Response(AutomationRuleSerializer(rules, many=True).data)

    @extend_schema(request=AutomationRuleWriteSerializer, responses=AutomationRuleSerializer)
    def post(self, request):
        s = AutomationRuleWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        # validate actions against the allow-list at save time (never let an
        # un-executable/unsafe rule persist)
        try:
            validate_actions(v["actions"])
        except AutomationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        rule = AutomationRule.objects.create(
            name=v["name"],
            conditions=v["conditions"],
            actions=v["actions"],
            priority=v["priority"],
            is_active=v["is_active"],
            stop_processing=v["stop_processing"],
        )
        return Response(AutomationRuleSerializer(rule).data, status=status.HTTP_201_CREATED)


class AutomationRuleDetailView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember, HasAIInsights]

    @extend_schema(responses={204: None})
    def delete(self, request, rule_id):
        rule = AutomationRule.objects.filter(id=rule_id).first()
        if rule is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        rule.is_active = False
        rule.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class CashRunwayView(TenantScopedAPIView, APIView):
    """Forward-looking liquidity: how long the cash lasts at the current pace."""

    permission_classes = [IsTenantMember, HasAIInsights]
    required_role = Role.VIEWER
    serializer_class = None

    def get(self, request):
        return Response(selectors.cash_runway())


# ------------------------------------------------------------------ AI coach
def _insight_out(insight) -> dict:
    return {
        "id": insight.id,
        "kind": insight.kind,
        "severity": insight.severity,
        "status": insight.status,
        "title": insight.title,
        "body": insight.body,
        # The WHY ships with every insight — an insight a user can't check is
        # one they can't trust.
        "rationale": insight.rationale,
        "evidence": insight.evidence,
        "action": insight.action,
        "priority_score": insight.priority_score,
        "period_start": insight.period_start,
        "period_end": insight.period_end,
        "expires_on": insight.expires_on,
        "provider": insight.provider,
        "provider_kind": insight.provider_kind,
        "provider_version": insight.provider_version,
        "related_transaction_id": insight.related_transaction_id,
        "related_category_id": insight.related_category_id,
        "related_account_id": insight.related_account_id,
        "created_at": insight.created_at,
    }


class InsightListView(TenantScopedAPIView, APIView):
    """The coach feed: live insights, most important first.

    `GET` reads what's stored. Generation is a separate `POST`, so opening the
    dashboard never blocks on a full recompute.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="insights_list")
    def get(self, request):
        status_filter = request.query_params.get("status")
        if status_filter == "bookmarked":
            qs = Insight.objects.filter(status=InsightStatus.BOOKMARKED)
        elif status_filter == "dismissed":
            qs = Insight.objects.filter(status=InsightStatus.DISMISSED)
        elif status_filter == "all":
            qs = Insight.objects.all()
        else:
            qs = coach.live_insights()
        return Response([_insight_out(i) for i in qs[:100]])


class InsightGenerateView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Re-runs the coach. Idempotent: existing conditions are refreshed, not
    duplicated, and dismissed insights stay dismissed."""

    permission_classes = [IsTenantMember]
    serializer_class = None

    @extend_schema(operation_id="insights_generate")
    def post(self, request):
        insights = coach.generate_insights()
        return Response([_insight_out(i) for i in insights], status=status.HTTP_201_CREATED)


class InsightDecisionView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Dismiss, bookmark, or mark an insight acted on."""

    permission_classes = [IsTenantMember]
    serializer_class = None

    _ALLOWED = {"dismiss", "bookmark", "seen", "acted"}
    _MAP = {
        "dismiss": InsightStatus.DISMISSED,
        "bookmark": InsightStatus.BOOKMARKED,
        "seen": InsightStatus.SEEN,
        "acted": InsightStatus.ACTED,
    }

    @extend_schema(operation_id="insight_decision")
    def post(self, request, insight_id, decision):
        if decision not in self._ALLOWED:
            return Response({"detail": f"Unknown decision {decision!r}."}, status=status.HTTP_400_BAD_REQUEST)
        insight = Insight.objects.filter(id=insight_id).first()
        if insight is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        coach.set_insight_status(insight=insight, status=self._MAP[decision])
        return Response(_insight_out(insight))


class BriefingView(TenantScopedAPIView, APIView):
    """The daily / weekly / monthly narrative review.

    Generates on demand and stores the result, so repeat opens return the same
    briefing rather than re-narrating.
    """

    permission_classes = [IsTenantMember]
    serializer_class = None

    @extend_schema(operation_id="briefing_retrieve")
    def get(self, request, period):
        if period not in BriefingPeriod.values:
            return Response({"detail": f"Unknown period {period!r}."}, status=status.HTTP_400_BAD_REQUEST)
        briefing = coach.generate_briefing(period=period)
        return Response(
            {
                "id": briefing.id,
                "period": briefing.period,
                "period_start": briefing.period_start,
                "period_end": briefing.period_end,
                "headline": briefing.headline,
                "summary": briefing.summary,
                # The figures the prose was written from, so the narrative can
                # always be checked against the numbers.
                "metrics": briefing.metrics,
                "provider": briefing.provider,
                "insights": [_insight_out(i) for i in briefing.insights.all()],
            }
        )


class LLMSettingsView(TenantScopedAPIView, APIView):
    """What AI provider is configured, and whether it can actually be used.

    Read-only and credential-free: the API key is never returned, only whether
    one is present. LLM configuration is deployment-level (environment
    variables), not per-workspace — a tenant cannot point the coach at their own
    endpoint, which would make the data-sharing decision theirs to make on
    everyone else's behalf.

    The `available` / `reason` pair exists because the most common failure here
    is silent: an operator switches the feature on, nothing changes, and there
    is nothing to look at. This says exactly what is missing.
    """

    permission_classes = [IsTenantMember]
    serializer_class = None

    @property
    def required_role(self):
        # GET is informational (any member can see what's configured); PATCH
        # changes a whole-workspace setting, so it needs the same bar as
        # every other workspace-level write in this app (see billing's
        # `required_role = Role.ADMIN` for the same pattern).
        return Role.VIEWER if self.request.method == "GET" else Role.ADMIN

    @extend_schema(operation_id="llm_settings")
    def get(self, request):
        from apps.tenancy.models import Tenant

        from ..llm import PROVIDER_PRESETS, get_llm_config, llm_available

        config = get_llm_config()
        available, reason = llm_available()
        configured = getattr(settings, "INTELLIGENCE_PROVIDERS", {}) or {}
        tenant = Tenant.objects.filter(id=request.tenant_id).first()

        return Response(
            {
                "enabled": config.enabled,
                # The one field on this endpoint that IS workspace-controlled —
                # everything else here is deployment-level and read-only. See
                # the docstring above and PATCH below.
                "tenant_ai_enabled": tenant.ai_enabled if tenant else True,
                "available": available,
                "reason": reason,
                "provider": config.provider,
                "provider_label": config.label,
                "model": config.model,
                "base_url": config.base_url,
                # Presence only — the key itself never crosses this boundary.
                "api_key_present": bool(config.api_key),
                "is_local": config.is_local,
                "share_financial_context": config.share_financial_context,
                "insight_provider": configured.get(
                    "insight", "apps.intelligence.providers.coach.RuleBasedCoach"
                ),
                "narrative_provider": configured.get(
                    "narrative", "apps.intelligence.providers.coach.TemplateNarrator"
                ),
                "presets": [
                    {
                        "id": key,
                        "label": preset.label,
                        "default_model": preset.default_model,
                        "requires_key": preset.requires_key,
                        "free_tier": preset.free_tier,
                        "is_local": "localhost" in preset.base_url,
                        "docs_url": preset.docs_url,
                    }
                    for key, preset in PROVIDER_PRESETS.items()
                ],
            }
        )

    def patch(self, request):
        """Toggle this workspace's AI opt-out.

        The only writable field on an otherwise read-only endpoint. Access is
        enforced by `required_role` above (Admin+) before this method ever
        runs — no manual role check needed here.
        """
        from apps.tenancy.models import Tenant

        if "tenant_ai_enabled" not in request.data:
            return Response({"detail": "tenant_ai_enabled is required."}, status=400)

        tenant = Tenant.objects.filter(id=request.tenant_id).first()
        if tenant is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        tenant.ai_enabled = bool(request.data["tenant_ai_enabled"])
        tenant.save(update_fields=["ai_enabled"])
        return Response({"tenant_ai_enabled": tenant.ai_enabled})


# ------------------------------------------------------- automation review
def _suggestion_out(s) -> dict:
    return {
        "id": s.id,
        "kind": s.kind,
        "status": s.status,
        "confidence": s.confidence,
        # Mandatory by contract — a suggestion nobody can check is one nobody
        # should act on.
        "reason": s.reason,
        "payload": s.payload,
        "merchant_key": s.merchant_key,
        "primary_transaction_id": s.primary_transaction_id,
        "transaction_ids": [str(t.id) for t in s.transactions.all()],
        "created_at": s.created_at,
        "decided_at": s.decided_at,
    }


class AutomationScanView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Run the detectors over recent transactions.

    Idempotent: a finding already decided is left alone, so rescanning never
    resurrects something the user dismissed.
    """

    permission_classes = [IsTenantMember]
    serializer_class = None

    @extend_schema(operation_id="automation_scan")
    def post(self, request):
        days = min(int(request.data.get("days", 120) or 120), 730)
        result = automation_services.scan(days=days)
        return Response(
            {
                "created": result.created,
                "refreshed": result.refreshed,
                "auto_applied": result.auto_applied,
                "total_suggestions": result.total_suggestions,
            },
            status=status.HTTP_200_OK,
        )


class AutomationQueueView(TenantScopedAPIView, APIView):
    """The review queue, most confident first."""

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="automation_queue")
    def get(self, request):
        kind = request.query_params.get("kind") or None
        queue = automation_services.pending_suggestions(kind=kind, limit=100)
        summary = automation_services.queue_summary()
        return Response(
            {
                "pending": summary.pending,
                "by_kind": summary.by_kind,
                "auto_applied": summary.auto_applied,
                # Null until something has been decided — an accuracy figure
                # from no data is not an accuracy figure.
                "approval_rate": summary.approval_rate,
                "suggestions": [_suggestion_out(s) for s in queue],
            }
        )


class AutomationDecisionView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Approve or reject one suggestion."""

    permission_classes = [IsTenantMember]
    serializer_class = None

    @extend_schema(operation_id="automation_decide")
    def post(self, request, suggestion_id, decision):
        from ..models import AutomationSuggestion

        if decision not in ("approve", "reject"):
            return Response({"detail": f"Unknown decision {decision!r}."}, status=status.HTTP_400_BAD_REQUEST)
        suggestion = AutomationSuggestion.objects.filter(id=suggestion_id).first()
        if suggestion is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        handler = automation_services.approve if decision == "approve" else automation_services.reject
        try:
            handler(suggestion=suggestion, actor_id=getattr(request.user, "id", None))
        except automation_services.AutomationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_suggestion_out(suggestion))


class AutomationBulkDecisionView(WriteRequiresMemberMixin, TenantScopedAPIView, APIView):
    """Decide many at once — a hundred suggestions one tap at a time is a queue
    nobody finishes."""

    permission_classes = [IsTenantMember]
    serializer_class = None

    @extend_schema(operation_id="automation_bulk_decide")
    def post(self, request):
        ids = request.data.get("suggestion_ids") or []
        decision = request.data.get("decision")
        try:
            decided = automation_services.bulk_decide(
                suggestion_ids=ids,
                decision=decision,
                actor_id=getattr(request.user, "id", None),
            )
        except automation_services.AutomationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"decided": decided, "requested": len(ids)})


class MerchantProfileView(TenantScopedAPIView, APIView):
    """What the engine has learned about each merchant.

    Exposed so the learning is inspectable: a user who asks why a category keeps
    being suggested deserves to see the counts it came from.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    @extend_schema(operation_id="merchant_profiles")
    def get(self, request):
        from ..models import MerchantProfile

        profiles = MerchantProfile.objects.order_by("-transaction_count")[:100]
        return Response(
            [
                {
                    "key": p.key,
                    "display_name": p.display_name,
                    "transaction_count": p.transaction_count,
                    "total_amount_minor": p.total_amount_minor,
                    "category_counts": p.category_counts,
                    "dominant_category_id": p.dominant_category_id,
                    "is_recurring": p.is_recurring,
                    "recurring_cadence": p.recurring_cadence,
                    # The raw descriptors, so "why were these grouped?" has an
                    # answer.
                    "seen_descriptors": p.seen_descriptors,
                    "last_seen_on": p.last_seen_on,
                }
                for p in profiles
            ]
        )
