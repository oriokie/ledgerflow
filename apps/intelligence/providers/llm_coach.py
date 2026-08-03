"""LLM-backed coach providers.

These implement exactly the same protocols as the rule-based providers, so
selecting them is a settings change and no caller is touched:

    INTELLIGENCE_PROVIDERS = {
        "insight":   "apps.intelligence.providers.llm_coach.LLMCoach",
        "narrative": "apps.intelligence.providers.llm_coach.LLMNarrator",
    }

Three properties make this safe to switch on in a financial product:

**The deterministic provider is always the floor, never a stub.** Every path —
LLM disabled, unreachable, timing out, rate-limited, returning garbage — falls
back to `RuleBasedCoach`. A user with a misconfigured API key gets the full
product, not an empty screen.

**The model's output is validated, not trusted.** A candidate without a
rationale, or with a kind outside the taxonomy, is dropped. The model cannot
invent an insight type, cannot skip the explanation, and cannot reach the
database or the ledger.

**Evidence comes from the engine, not the model.** The LLM is given figures and
asked to *phrase* them. It never supplies the numbers that appear in the
evidence panel, because a number a model produced is a number nobody computed.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from ..llm import LLMError, complete_json, get_llm_config, llm_available
from ..models import InsightKind, InsightSeverity
from ..protocols import (
    BriefingDraft,
    CoachContext,
    InsightCandidate,
    Provenance,
    ProviderKind,
)
from .coach import RuleBasedCoach, TemplateNarrator

logger = logging.getLogger("ledgerflow.intelligence")

VERSION = "1.0"

#: Hard ceiling on how many candidates a model may contribute. A model asked
#: for "insights" will happily produce thirty; the feed is ranked, not
#: exhaustive, and a wall of model-written cards is the failure mode here.
MAX_LLM_CANDIDATES = 6

_SYSTEM = """You are a careful financial assistant inside a personal finance app.

You will be given a JSON summary of one household's finances. Return insights as
a JSON array. Each object must have exactly these keys:

  "kind"      one of: {kinds}
  "severity"  one of: critical, warning, opportunity, info
  "title"     under 70 characters, specific, no exclamation marks
  "body"      one or two sentences, plain language, cite the actual figures
  "rationale" one sentence explaining which figures led to this and how

Rules you must follow:
- Only state things the provided data supports. Never estimate or assume.
- Use "critical" only when there is a dated deadline in the data.
- Say numbers plainly. "You spent 412 of your 350 limit" not "you overspent".
- If something is merely possible, say so ("worth checking"), do not assert it.
- Return at most {limit} objects, most important first.
- If the data supports nothing worth saying, return an empty array.
- Return only the JSON array. No prose, no markdown fences."""


def _severity_of(value: str) -> str | None:
    value = (value or "").strip().lower()
    return value if value in InsightSeverity.values else None


def _kind_of(value: str) -> str | None:
    value = (value or "").strip().lower()
    return value if value in InsightKind.values else None


class LLMCoach:
    """Generates insights with a configured model, falling back to rules.

    The rule-based candidates are always produced and always kept: the model
    *adds* to a deterministic baseline rather than replacing it. That way a
    predicted overdraft is never missed because a model was having an off day,
    and the LLM's contribution is judged on what it adds.
    """

    name = "LLMCoach"
    kind = ProviderKind.LLM
    version = VERSION

    def __init__(self) -> None:
        self._fallback = RuleBasedCoach()

    def generate(self, context: CoachContext) -> list[InsightCandidate]:
        baseline = self._fallback.generate(context)

        ok, reason = llm_available()
        if not ok:
            logger.debug("coach: LLM unavailable (%s); using rules only", reason)
            return baseline

        try:
            extra = self._generate_llm(context, baseline)
        except LLMError as exc:
            logger.warning("coach: LLM generation failed (%s); using rules only", exc)
            return baseline
        except Exception:  # pragma: no cover - defensive
            logger.exception("coach: unexpected LLM failure; using rules only")
            return baseline

        return [*baseline, *extra]

    def _generate_llm(
        self, context: CoachContext, baseline: list[InsightCandidate]
    ) -> list[InsightCandidate]:
        config = get_llm_config()
        # Don't ask the model to repeat what the rules already found.
        covered = sorted({c.kind for c in baseline})

        payload = {
            "as_of": context.as_of.isoformat(),
            "currency": context.currency,
            "already_reported": covered,
            "budget_lines": list(context.budget_lines)[:10],
            "category_trends": list(context.category_trends)[:10],
            "subscriptions": list(context.subscriptions)[:10],
            "debts": list(context.debts)[:5],
            "cashflow_risk": context.cashflow_risk,
            "savings_rate": context.savings_rate,
            "health": context.health,
        }

        system = _SYSTEM.format(kinds=", ".join(InsightKind.values), limit=MAX_LLM_CANDIDATES)
        raw = complete_json(
            system=system,
            user=_to_json_text(payload),
            config=config,
        )
        if not isinstance(raw, list):
            raise LLMError("expected a JSON array of insights")

        provenance = Provenance(
            provider=self.name,
            kind=self.kind,
            version=self.version,
            rationale=f"{config.label} · {config.model}",
        )

        out: list[InsightCandidate] = []
        seen = {c.dedupe_key for c in baseline}
        for index, item in enumerate(raw[:MAX_LLM_CANDIDATES]):
            candidate = self._validate(item, context, provenance, index)
            if candidate is None or candidate.dedupe_key in seen:
                continue
            seen.add(candidate.dedupe_key)
            out.append(candidate)
        return out

    def _validate(
        self, item: object, context: CoachContext, provenance: Provenance, index: int
    ) -> InsightCandidate | None:
        """Turn one model object into a candidate, or drop it.

        Silence is the correct outcome for anything malformed. A partially
        valid insight — a title with no rationale, say — is exactly the kind of
        unsupported claim the contract exists to prevent.
        """
        if not isinstance(item, dict):
            return None

        kind = _kind_of(str(item.get("kind", "")))
        severity = _severity_of(str(item.get("severity", "")))
        title = str(item.get("title", "")).strip()
        body = str(item.get("body", "")).strip()
        rationale = str(item.get("rationale", "")).strip()

        if not (kind and severity and title and body and rationale):
            logger.debug("coach: dropped malformed LLM candidate %r", item)
            return None

        return InsightCandidate(
            kind=kind,
            severity=severity,
            title=title[:160],
            body=body,
            rationale=rationale,
            # Namespaced and period-scoped so a model rerun refreshes rather
            # than duplicating, exactly like a rule-based candidate.
            dedupe_key=f"llm:{kind}:{context.as_of.strftime('%Y-%m-%d')}:{index}",
            # Deliberately no evidence: the model phrases figures, it does not
            # produce them. A number a model invented is a number nobody
            # computed.
            evidence={},
            provenance=provenance,
            # Discounted against rule-based candidates, which are derived
            # rather than described.
            confidence=0.6,
        )


class LLMNarrator:
    """Writes briefing prose with a model, falling back to the template.

    Narration is the safer half of the split: rewording figures that have
    already been computed and validated carries far less risk than deciding
    what is true. This is the configuration most deployments should start with.
    """

    name = "LLMNarrator"
    kind = ProviderKind.LLM
    version = VERSION

    _SYSTEM = """You write a short financial briefing for one household.

You will be given a JSON summary and a list of insights already produced by a
deterministic engine. Write a JSON object with exactly these keys:

  "headline"  under 80 characters, the single most important thing
  "summary"   two to four sentences of plain, calm prose

Rules:
- Use only the figures provided. Never estimate, never add numbers.
- Lead with anything marked critical.
- If nothing needs attention, say so plainly. That is a useful answer.
- No exclamation marks, no motivational language, no emoji.
- Return only the JSON object."""

    def __init__(self) -> None:
        self._fallback = TemplateNarrator()

    def write_briefing(
        self, *, period: str, context: CoachContext, insights: list[InsightCandidate]
    ) -> BriefingDraft:
        template = self._fallback.write_briefing(period=period, context=context, insights=insights)

        ok, reason = llm_available()
        if not ok:
            logger.debug("coach: LLM unavailable (%s); using template narrator", reason)
            return template

        try:
            config = get_llm_config()
            payload = {
                "period": period,
                "currency": context.currency,
                "savings_rate": context.savings_rate,
                "insights": [
                    {"severity": i.severity, "title": i.title, "body": i.body} for i in insights[:12]
                ],
            }
            raw = complete_json(system=self._SYSTEM, user=_to_json_text(payload), config=config)
            if not isinstance(raw, dict):
                raise LLMError("expected a JSON object")

            headline = str(raw.get("headline", "")).strip()
            summary = str(raw.get("summary", "")).strip()
            if not headline or not summary:
                raise LLMError("missing headline or summary")

            # The metrics keep coming from the engine: the model rewrote the
            # prose, it did not recount anything.
            return replace(
                template,
                headline=headline[:200],
                summary=summary,
                provenance=Provenance(
                    provider=self.name,
                    kind=self.kind,
                    version=self.version,
                    rationale=f"{config.label} · {config.model}",
                ),
            )
        except LLMError as exc:
            logger.warning("coach: LLM narration failed (%s); using template", exc)
            return template
        except Exception:  # pragma: no cover - defensive
            logger.exception("coach: unexpected narration failure; using template")
            return template


def _to_json_text(payload: dict) -> str:
    import json

    return json.dumps(payload, default=str, ensure_ascii=False)
