"""Intelligence application services — where providers meet the domain.

These orchestrate: pull features from real transactions, call the registry's
provider (rules today, LLM tomorrow — this layer doesn't know which), persist
the output as an advisory suggestion, and apply it only through the existing
finance service layer (never a raw ledger write). Automation runs the same
way: match deterministic rules, then apply their allow-listed effects through
finance services.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.finance import services as finance_services
from apps.finance import tagging
from apps.finance.models import Category, Tag, Transaction
from apps.finance.payees import normalize_payee_name

from . import automation, registry
from .models import AutomationRule, CategorizationSuggestion, SuggestionStatus
from .protocols import TransactionFeatures


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


def _apply_action(txn: Transaction, action: dict) -> str:
    kind = action.get("type")
    if kind == "set_category":
        category = None
        if action.get("slug"):
            category = Category.objects.filter(slug=action["slug"]).first()
        if category is None and action.get("category_id"):
            category = Category.objects.filter(id=action["category_id"]).first()
        if category and txn.category_id is None:
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
