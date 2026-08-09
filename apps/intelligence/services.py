"""Intelligence application services — where providers meet the domain.

These orchestrate: pull features from real transactions, call the registry's
provider (rules today, LLM tomorrow — this layer doesn't know which), persist
the output as an advisory suggestion, and apply it only through the existing
finance service layer (never a raw ledger write). Automation runs the same
way: match deterministic rules, then apply their allow-listed effects through
finance services.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.finance import services as finance_services
from apps.finance import tagging
from apps.finance.models import Category, Tag, Transaction, TransactionStatus
from apps.finance.payees import normalize_payee_name

from . import automation, registry
from .models import AutomationRule, CategorizationSuggestion, SuggestionStatus
from .protocols import TransactionFeatures

#: Both `import_csv.py` and `import_mpesa_service.py` need *some* real
#: category to post a valid ledger entry against, so a row that couldn't be
#: classified never actually lands with `category=None` — it lands against
#: one of these two lazily-created placeholders. Treated as equivalent to
#: "uncategorized" everywhere a rule decides whether it's still free to set
#: a category, since no human chose either of these on purpose.
_PLACEHOLDER_CATEGORY_NAMES = ["Uncategorized", "Uncategorized Income"]


# --------------------------------------------------------------- feature extraction
def features_for(txn: Transaction) -> TransactionFeatures:
    """Build the model-free feature DTO from a real transaction. This is the
    ONLY place that reads Django models for categorization, so providers stay
    pure and testable."""
    payee_name = txn.payee.normalized_name if txn.payee_id else normalize_payee_name(txn.memo or "")

    recent = ()
    if txn.payee_id:
        recent = tuple(
            str(cid)
            for cid in Transaction.objects.filter(payee_id=txn.payee_id, category__isnull=False)
            .exclude(id=txn.id)
            .order_by("-occurred_at")
            .values_list("category_id", flat=True)[:5]
        )

    return TransactionFeatures(
        payee_normalized=payee_name,
        memo=txn.memo or "",
        amount_minor=txn.amount_minor,
        currency=txn.currency,
        occurred_at=txn.occurred_at,
        account_type=txn.financial_account.account_type,
        recent_category_ids_for_payee=recent,
    )


# --------------------------------------------------------------- categorization
@transaction.atomic
def suggest_category(txn: Transaction) -> CategorizationSuggestion:
    """Run the configured categorizer and STORE the result as a pending
    suggestion (advisory — not applied). Returns the suggestion row."""
    provider = registry.get_categorizer()
    result = provider.suggest_category(features_for(txn))

    category_id = None
    if result.category_id:
        # provider may return a slug or a real id; only persist a real category
        category = Category.objects.filter(id=result.category_id).first()
        category_id = category.id if category else None

    return CategorizationSuggestion.objects.create(
        transaction=txn,
        suggested_category_id=category_id,
        confidence=result.confidence,
        status=SuggestionStatus.PENDING,
        provider=result.provenance.provider,
        provider_kind=str(result.provenance.kind),
        provider_version=result.provenance.version,
        rationale=result.provenance.rationale[:255],
    )


@transaction.atomic
def accept_suggestion(suggestion: CategorizationSuggestion) -> Transaction:
    """Apply a suggestion through the finance service layer (not a raw write),
    and record the decision. Idempotent on already-decided suggestions."""
    if suggestion.status != SuggestionStatus.PENDING:
        return suggestion.transaction
    if suggestion.suggested_category_id is None:
        raise finance_services.FinanceError("Suggestion has no category to apply.")

    category = Category.objects.get(id=suggestion.suggested_category_id)
    txn = finance_services.update_transaction(txn=suggestion.transaction, category=category)

    suggestion.status = SuggestionStatus.ACCEPTED
    suggestion.decided_at = timezone.now()
    suggestion.save(update_fields=["status", "decided_at", "updated_at"])
    return txn


@transaction.atomic
def reject_suggestion(suggestion: CategorizationSuggestion) -> None:
    if suggestion.status != SuggestionStatus.PENDING:
        return
    suggestion.status = SuggestionStatus.REJECTED
    suggestion.decided_at = timezone.now()
    suggestion.save(update_fields=["status", "decided_at", "updated_at"])


def auto_accept_threshold() -> float:
    from django.conf import settings

    return getattr(settings, "INTELLIGENCE_AUTO_ACCEPT_CONFIDENCE", 0.9)


@transaction.atomic
def suggest_and_maybe_apply(txn: Transaction) -> CategorizationSuggestion:
    """Suggest, and if confidence clears the configured threshold AND the
    transaction is still uncategorized, apply automatically. High-confidence
    merchant-memory matches flow straight through; everything else waits for a
    human. The threshold is the single dial between 'assistive' and
    'autonomous'."""
    suggestion = suggest_category(txn)
    if (
        suggestion.suggested_category_id
        and suggestion.confidence >= auto_accept_threshold()
        and txn.category_id is None
    ):
        accept_suggestion(suggestion)
    return suggestion


# --------------------------------------------------------------- automation
@transaction.atomic
def run_automation(txn: Transaction) -> list[str]:
    """Evaluate active automation rules against a transaction and apply matched
    actions through finance services. Returns human-readable effect strings.
    Rule effects are limited to the allow-list (category, tag, flag)."""
    rules = list(AutomationRule.objects.filter(is_active=True).order_by("priority", "id"))
    if not rules:
        return []

    feats = features_for(txn)
    feature_dict = {
        "payee_normalized": feats.payee_normalized,
        "memo": feats.memo,
        "amount_minor": feats.amount_minor,
        "currency": feats.currency,
        "account_type": feats.account_type,
        "category_id": str(txn.category_id) if txn.category_id else None,
    }

    matches = automation.evaluate_rules(rules, feature_dict)
    effects: list[str] = []
    matched_rule_ids: list[str] = []

    for match in matches:
        matched_rule_ids.append(match.rule_id)
        for action in match.actions:
            effects.append(_apply_action(txn, action))

    if matched_rule_ids:
        AutomationRule.objects.filter(id__in=matched_rule_ids).update(
            match_count=F("match_count") + 1, last_matched_at=timezone.now()
        )
    return effects


def _is_uncategorized(txn: Transaction) -> bool:
    """True category-less, or holding one of the ledger-required import
    placeholders nobody actually chose (see `_PLACEHOLDER_CATEGORY_NAMES`)."""
    if txn.category_id is None:
        return True
    return txn.category.name in _PLACEHOLDER_CATEGORY_NAMES


def _apply_action(txn: Transaction, action: dict) -> str:
    kind = action.get("type")
    if kind == "set_category":
        category = None
        if action.get("slug"):
            category = Category.objects.filter(slug=action["slug"]).first()
        if category is None and action.get("category_id"):
            category = Category.objects.filter(id=action["category_id"]).first()
        if category and _is_uncategorized(txn):
            finance_services.update_transaction(txn=txn, category=category)
            return f"set category to {category.name}"
        return "category unchanged (already set or not found)"
    if kind == "add_tag":
        tag, _ = Tag.objects.get_or_create(name=action["name"], defaults={"tenant_id": txn.tenant_id})
        existing = [link.tag for link in txn.tag_links.select_related("tag")]
        tagging.set_transaction_tags(txn=txn, tags=[*existing, tag])
        return f"added tag {tag.name}"
    if kind == "flag_review":
        finance_services.flag_transaction_for_review(
            txn=txn, reason=action.get("reason", "Flagged by automation rule")
        )
        return "flagged for review"
    return "no-op"


@transaction.atomic
def update_automation_rule(
    *,
    rule: AutomationRule,
    name: str | None = None,
    conditions: dict | None = None,
    actions: list | None = None,
    priority: int | None = None,
    is_active: bool | None = None,
    stop_processing: bool | None = None,
) -> AutomationRule:
    """Edit an existing rule in place, instead of soft-deleting and
    recreating. `conditions`/`actions` are re-validated against the same
    engine that will evaluate them (regex clauses compile, action types are
    on the allow-list) before anything is written — a save-time check must
    apply on every path that can change a rule's body, not just creation.

    Plain `None` defaults (not a sentinel) are correct here: unlike a field
    such as a category's `parent`, none of a rule's editable fields has a
    meaningful "explicitly clear it" case distinct from "leave it alone."
    """
    fields: list[str] = []
    if name is not None:
        rule.name = name
        fields.append("name")
    if conditions is not None:
        automation.validate_conditions(conditions)
        rule.conditions = conditions
        fields.append("conditions")
    if actions is not None:
        automation.validate_actions(actions)
        rule.actions = actions
        fields.append("actions")
    if priority is not None:
        rule.priority = priority
        fields.append("priority")
    if is_active is not None:
        rule.is_active = is_active
        fields.append("is_active")
    if stop_processing is not None:
        rule.stop_processing = stop_processing
        fields.append("stop_processing")
    if fields:
        rule.save(update_fields=[*fields, "updated_at"])
    return rule


@dataclass(frozen=True, slots=True)
class RetroactiveApplyResult:
    scanned: int
    matched: int
    effects: int
    errors: list[dict] = field(default_factory=list)


def apply_rules_to_uncategorized(
    *, scope: str = "uncategorized", limit: int = 5000
) -> RetroactiveApplyResult:
    """Retroactively run active rules over existing transactions.

    A rule only ever applies going forward, at the moment a transaction is
    created (see `signals.py`'s post_save hook) — so a rule authored today has
    no way to reach a transaction imported yesterday. This is the other half:
    an explicit, on-demand sweep.

    `scope="uncategorized"` (default) targets true-null categories AND the
    "Uncategorized"/"Uncategorized Income" placeholders every importer falls
    back to — see `_PLACEHOLDER_CATEGORY_NAMES`. `_apply_action`'s
    `set_category` uses the same `_is_uncategorized` check before writing, so
    a placeholder-categorized row is genuinely eligible to be recategorized,
    not just matched-and-skipped. `scope="all"` widens the sweep further for
    tag/flag-only rules, where "already categorized" isn't the right skip
    condition; it still excludes transfers (no category slot to touch) and
    voided rows. Bounded by `limit`, most-recent-first, so one call can't hold
    a lock over the whole table — callers re-invoke to walk further back.
    """
    if not AutomationRule.objects.filter(is_active=True).exists():
        return RetroactiveApplyResult(0, 0, 0, [])

    qs = (
        Transaction.objects.filter(transfer_group__isnull=True)
        .exclude(status=TransactionStatus.VOID)
        .order_by("-occurred_at")
    )
    if scope == "uncategorized":
        qs = qs.filter(Q(category__isnull=True) | Q(category__name__in=_PLACEHOLDER_CATEGORY_NAMES))

    scanned = matched = effects = 0
    errors: list[dict] = []
    for txn in qs[:limit]:
        scanned += 1
        try:
            applied = run_automation(txn)
        except Exception as exc:  # noqa: BLE001 - report and continue, mirrors import_csv's per-row contract
            errors.append({"transaction_id": str(txn.id), "error": str(exc)})
            continue
        if applied:
            matched += 1
            effects += len(applied)
    return RetroactiveApplyResult(scanned, matched, effects, errors)


# --------------------------------------------------------------- forecasting
def forecast(*, months_history: int = 6, periods_ahead: int = 1):
    """Project upcoming expense from trailing cash-flow history.

    Ties the built-but-previously-unwired `ForecastProvider` to real data: the
    composing selector builds the `CashflowPoint` history, the registry's
    forecaster (moving-average today, swappable) turns it into a `Forecast`.
    Advisory only — nothing here writes to the ledger.
    """
    from . import selectors

    history = selectors.build_cashflow_history(months=months_history)
    return registry.get_forecaster().forecast_expense(history, periods_ahead)


# --------------------------------------------------------------- missed-recurring
def detect_missed_recurring(*, grace_days: int = 3):
    """Surface expected-but-absent recurring charges (the RECURRING_MISSED
    anomaly kind, previously declared with no detector behind it).

    Schedule-based, not amount-based, so it lives here rather than in the pure
    amount detector: for each active recurring template whose `next_run_on` is
    now overdue by more than `grace_days` with no matching posted transaction,
    emit a lightweight advisory dict. Kept dependency-light (plain dicts) so it
    can feed a notification or an anomalies response without new DTO coupling.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.finance.models import RecurringTransaction, Transaction

    today = timezone.localdate()
    cutoff = today - timedelta(days=grace_days)
    missed = []
    templates = RecurringTransaction.objects.filter(is_active=True, next_run_on__lt=cutoff)
    for tmpl in templates:
        # did a transaction for this template's account+amount post recently?
        window_start = tmpl.next_run_on - timedelta(days=grace_days)
        exists = (
            Transaction.objects.filter(
                financial_account_id=tmpl.financial_account_id,
                occurred_at__date__gte=window_start,
                transfer_group__isnull=True,
            )
            .filter(amount_minor__in=[tmpl.amount_minor, -tmpl.amount_minor])
            .exists()
        )
        if not exists:
            missed.append(
                {
                    "recurring_id": str(tmpl.id),
                    "kind": "recurring_missed",
                    "expected_on": tmpl.next_run_on.isoformat(),
                    "amount_minor": tmpl.amount_minor,
                    "currency": tmpl.currency,
                    "explanation": (
                        f"Expected recurring charge of {tmpl.amount_minor / 100:.2f} "
                        f"{tmpl.currency} was not seen around {tmpl.next_run_on:%b %d}."
                    ),
                }
            )
    return missed
