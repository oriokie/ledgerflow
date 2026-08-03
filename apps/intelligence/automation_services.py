"""Automation services — scanning, review, and the learning loop.

Three responsibilities, deliberately separated:

**Scan** turns transactions into persisted suggestions. Idempotent per finding,
because the scanner runs repeatedly over overlapping windows and without stable
identity every run would re-propose what the user already dismissed.

**Review** records decisions. Approving a suggestion applies it; rejecting it
records that too, because a rejection is the most informative signal the system
receives and throwing it away is how automation stays bad forever.

**Learn** updates merchant profiles from those decisions, so the next scan is
grounded in what this household actually does.

The governing rule: **automation proposes, a person disposes.** Nothing here
posts to the ledger. The only action applied without a tap is a category on a
high-confidence suggestion, and even that is recorded as `auto_applied` and is
reversible — an action nobody can review isn't automation, it's something
happening to you.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.finance.models import Transaction

from . import detect
from .models import (
    AutomationSuggestion,
    MerchantProfile,
    ReviewStatus,
    SuggestionKind,
)


class AutomationError(Exception): ...


#: Above this, a category suggestion is applied without asking. Set high
#: deliberately: the cost of a wrong auto-categorisation is a user who stops
#: trusting the feature, which is far worse than one extra tap.
AUTO_APPLY_THRESHOLD = 0.92

#: How far back a scan looks by default. Long enough to catch a quarterly
#: subscription's third occurrence, short enough to stay quick.
DEFAULT_SCAN_DAYS = 120


#: Names the importer gives its lazily-created fallback categories. A
#: transaction sitting in one of these is *effectively* uncategorised — the
#: ledger needs a category for a valid posting, so "no category" isn't a state
#: the product can represent.
_PLACEHOLDER_CATEGORY_NAMES = {"uncategorized", "uncategorised", "uncategorized income"}


def is_placeholder_category(category) -> bool:
    """Whether a category is the importer's stand-in rather than a real choice.

    Matters twice over. Without it the category detector never fires for
    imported rows — the exact case it exists to serve — and the learning engine
    accumulates votes for "Uncategorized" itself, growing steadily more
    confident in a category that means "we don't know".
    """
    if category is None:
        return True
    return (category.name or "").strip().lower() in _PLACEHOLDER_CATEGORY_NAMES


def _merchant_name(txn: Transaction) -> str:
    payee = getattr(txn, "payee", None)
    return (getattr(payee, "name", "") or txn.memo or "").strip()


def _to_detect_txn(txn: Transaction) -> detect.Txn:
    return detect.Txn(
        txn_id=str(txn.id),
        account_id=str(txn.financial_account_id),
        occurred_on=txn.occurred_at.date(),
        amount_minor=txn.amount_minor,
        merchant=_merchant_name(txn),
        # A placeholder reads as no category, so the engine's existing contract
        # — "no category means suggest one" — covers the imported case without
        # the pure module needing to know product-specific names.
        category_id=(
            None if is_placeholder_category(txn.category) else str(txn.category_id)
        ),
        memo=txn.memo or "",
    )


def merchant_stats() -> dict[str, dict[str, int]]:
    """Learned category counts, keyed by merchant.

    Read once per scan rather than per transaction: the whole point of the
    profile table is that this is a single cheap query instead of a scan over
    history for every row.
    """
    return {
        profile.key: dict(profile.category_counts or {})
        for profile in MerchantProfile.objects.all()
    }


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------
@transaction.atomic
def learn_from_transaction(txn: Transaction) -> MerchantProfile | None:
    """Fold one transaction into its merchant's profile.

    Called when a transaction is categorised — by the user, by a rule, or by an
    approved suggestion. Every one of those is a signal about how this
    household thinks, and they are treated identically because they are equally
    true.
    """
    raw = _merchant_name(txn)
    if not raw:
        return None

    key = detect.merchant_key(raw)
    if not key:
        return None

    profile, _ = MerchantProfile.objects.get_or_create(
        key=key, defaults={"display_name": detect.normalize_merchant(raw)}
    )
    # Re-read under a row lock before touching the counters. Everything below is
    # read-modify-write, including `category_counts`, which is pulled into a
    # Python dict and written back whole — so a concurrent update did not merely
    # lose an increment, it lost an entire category key. `bulk_decide` walks a
    # list of suggestions calling straight into here, so the collision is
    # ordinary use rather than a thought experiment.
    profile = MerchantProfile.objects.select_for_update().get(pk=profile.pk)

    occurred = txn.occurred_at.date()
    profile.transaction_count += 1
    profile.total_amount_minor += abs(txn.amount_minor)
    profile.last_seen_on = max(profile.last_seen_on or occurred, occurred)
    profile.first_seen_on = min(profile.first_seen_on or occurred, occurred)

    # Never learn the placeholder: it means "we don't know", and voting for it
    # would make the engine confident in its own ignorance.
    if txn.category_id and not is_placeholder_category(txn.category):
        counts = dict(profile.category_counts or {})
        category_id = str(txn.category_id)
        counts[category_id] = counts.get(category_id, 0) + 1
        profile.category_counts = counts

    # Keep a bounded audit trail of raw descriptors, so "why were these
    # grouped?" has an answer without storing every row forever.
    descriptors = list(profile.seen_descriptors or [])
    if raw not in descriptors:
        descriptors.append(raw)
        profile.seen_descriptors = descriptors[-10:]

    profile.save()
    return profile


@transaction.atomic
def unlearn_category(*, merchant_key_value: str, category_id: str) -> None:
    """Withdraw one vote for a category.

    Used when a user corrects a categorisation. Without this, a mistake the
    engine made and the user fixed would keep voting for itself — the system
    would learn from its own errors and become more confident in them.
    """
    profile = MerchantProfile.objects.filter(key=merchant_key_value).first()
    if profile is None:
        return
    counts = dict(profile.category_counts or {})
    if category_id in counts:
        counts[category_id] = max(0, counts[category_id] - 1)
        if counts[category_id] == 0:
            del counts[category_id]
        profile.category_counts = counts
        profile.save(update_fields=["category_counts", "updated_at"])


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ScanResult:
    created: int
    refreshed: int
    auto_applied: int
    total_suggestions: int


@transaction.atomic
def scan(*, days: int = DEFAULT_SCAN_DAYS, as_of: date | None = None) -> ScanResult:
    """Run every detector over recent transactions and persist the findings.

    Idempotent by `dedupe_key`: a finding already decided is left alone, so
    rescanning never resurrects something the user dismissed. Re-detecting an
    undecided finding refreshes its confidence and reasoning, because the
    evidence can strengthen as more data arrives.
    """
    as_of = as_of or timezone.localdate()
    since = as_of - timedelta(days=days)

    rows = list(
        Transaction.objects.filter(occurred_at__date__gte=since)
        .select_related("payee", "category")
        .order_by("occurred_at")
    )
    if not rows:
        return ScanResult(0, 0, 0, 0)

    by_id = {str(t.id): t for t in rows}
    findings = detect.detect_all(
        [_to_detect_txn(t) for t in rows], merchant_stats=merchant_stats()
    )

    created = refreshed = auto_applied = 0

    for finding in findings:
        key = _dedupe_key(finding)
        existing = AutomationSuggestion.objects.filter(dedupe_key=key).first()

        if existing is not None:
            if existing.status != ReviewStatus.PENDING:
                # Already decided. Re-proposing it would make dismissal
                # meaningless.
                continue
            existing.confidence = finding.confidence
            existing.reason = finding.reason
            existing.payload = finding.payload
            existing.save(update_fields=["confidence", "reason", "payload", "updated_at"])
            refreshed += 1
            continue

        primary = by_id.get(finding.txn_ids[0])
        suggestion = AutomationSuggestion.objects.create(
            kind=finding.kind,
            confidence=finding.confidence,
            reason=finding.reason,
            payload=finding.payload,
            dedupe_key=key,
            primary_transaction=primary,
            merchant_key=(
                detect.merchant_key(_merchant_name(primary)) if primary else ""
            ),
        )
        suggestion.transactions.set([by_id[t] for t in finding.txn_ids if t in by_id])
        created += 1

        # High-confidence categorisation is the one thing applied unasked, and
        # even that is recorded and reversible.
        if (
            finding.kind == detect.SuggestionKind.CATEGORY
            and finding.confidence >= AUTO_APPLY_THRESHOLD
        ):
            _apply(suggestion)
            suggestion.status = ReviewStatus.AUTO_APPLIED
            suggestion.decided_at = timezone.now()
            suggestion.save(update_fields=["status", "decided_at", "updated_at"])
            auto_applied += 1

    return ScanResult(
        created=created,
        refreshed=refreshed,
        auto_applied=auto_applied,
        total_suggestions=len(findings),
    )


def _dedupe_key(finding: detect.Suggestion) -> str:
    """Stable identity for a *finding*, not a run.

    Built from the kind and the transactions involved, sorted so the same pair
    produces the same key regardless of which detector saw it first.
    """
    return f"{finding.kind}:" + ",".join(sorted(finding.txn_ids))


# ---------------------------------------------------------------------------
# Review workflow
# ---------------------------------------------------------------------------
def pending_suggestions(*, kind: str | None = None, limit: int | None = None):
    """The review queue: undecided findings, most confident first."""
    qs = AutomationSuggestion.objects.filter(status=ReviewStatus.PENDING).select_related(
        "primary_transaction"
    )
    if kind:
        qs = qs.filter(kind=kind)
    return qs[:limit] if limit else qs


@transaction.atomic
def approve(*, suggestion: AutomationSuggestion, actor_id=None) -> AutomationSuggestion:
    """Accept a suggestion and apply it."""
    if suggestion.status not in (ReviewStatus.PENDING, ReviewStatus.AUTO_APPLIED):
        raise AutomationError("That suggestion has already been decided.")

    _apply(suggestion)
    suggestion.status = ReviewStatus.APPROVED
    suggestion.decided_at = timezone.now()
    suggestion.decided_by_id = actor_id
    suggestion.save(update_fields=["status", "decided_at", "decided_by_id", "updated_at"])
    return suggestion


@transaction.atomic
def reject(*, suggestion: AutomationSuggestion, actor_id=None) -> AutomationSuggestion:
    """Decline a suggestion, and learn from the refusal.

    A rejection is the most informative signal the system gets: it says the
    engine was wrong in a specific, correctable way. Discarding it is how
    automation stays bad forever, so a rejected category withdraws its vote.
    """
    if suggestion.status == ReviewStatus.REJECTED:
        return suggestion

    if suggestion.kind == SuggestionKind.CATEGORY and suggestion.merchant_key:
        category_id = suggestion.payload.get("category_id")
        if category_id:
            unlearn_category(
                merchant_key_value=suggestion.merchant_key, category_id=str(category_id)
            )

    suggestion.status = ReviewStatus.REJECTED
    suggestion.decided_at = timezone.now()
    suggestion.decided_by_id = actor_id
    suggestion.save(update_fields=["status", "decided_at", "decided_by_id", "updated_at"])
    return suggestion


@transaction.atomic
def bulk_decide(*, suggestion_ids: list, decision: str, actor_id=None) -> int:
    """Approve or reject many at once.

    Bulk review is what makes a backlog tractable — a hundred suggestions one
    tap at a time is a queue nobody finishes. Each is still applied
    individually so a single failure can't silently take the batch with it.
    """
    if decision not in ("approve", "reject"):
        raise AutomationError(f"Unknown decision {decision!r}.")

    handler = approve if decision == "approve" else reject
    decided = 0
    for suggestion in AutomationSuggestion.objects.filter(id__in=suggestion_ids):
        try:
            handler(suggestion=suggestion, actor_id=actor_id)
            decided += 1
        except AutomationError:
            # Already decided by someone else in a concurrent session. Skipping
            # is right: the batch shouldn't fail because one row moved on.
            continue
    return decided


def _apply(suggestion: AutomationSuggestion) -> None:
    """Carry out what a suggestion proposes.

    Only two kinds change anything, and both are metadata:

      * `category` sets a category and teaches the merchant profile;
      * `recurring` marks the merchant as billing on a cadence.

    Transfers, duplicates, refunds, splits and income are **advisory only**.
    Acting on them would mean creating, deleting or re-posting ledger entries
    on the strength of a guess, and the ledger is the one thing in this product
    that must never be written speculatively. Approving them records the user's
    judgement for the learning engine and marks the queue item done.
    """
    from apps.finance.models import Category

    if suggestion.kind == SuggestionKind.CATEGORY:
        category_id = suggestion.payload.get("category_id")
        txn = suggestion.primary_transaction
        if not (category_id and txn):
            return
        category = Category.objects.filter(id=category_id).first()
        if category is None:
            return
        txn.category = category
        txn.save(update_fields=["category", "updated_at"])
        learn_from_transaction(txn)

    elif suggestion.kind == SuggestionKind.RECURRING:
        profile = MerchantProfile.objects.filter(key=suggestion.merchant_key).first()
        if profile is not None:
            profile.is_recurring = True
            profile.recurring_cadence = suggestion.payload.get("cadence", "")
            profile.save(update_fields=["is_recurring", "recurring_cadence", "updated_at"])
        _forecast_next_occurrence(suggestion)


def _forecast_next_occurrence(suggestion: AutomationSuggestion) -> None:
    """Put an approved recurring charge into the cash-flow forecast.

    Marking the merchant profile — all this used to do — teaches the categoriser
    and nothing else. The projection reads `RecurringTransaction` and `Bill`, so
    a detected subscription was invisible to the one screen it most belonged on:
    the user approved "yes, this recurs" and their forecast stayed flat.

    **A `Bill`, deliberately, and never a `RecurringTransaction`.** An active
    recurring template is executed by a beat task that posts real ledger
    entries — creating one from a *guess* would write transactions the user
    never made, which is the single thing this codebase refuses to do. A bill is
    an expectation: it shapes the forecast, and it posts nothing until somebody
    marks it paid.

    Only the next occurrence, not a series. If the prediction is wrong the user
    is one dismissal away from it being over, rather than owning a schedule they
    have to go and dismantle.
    """
    from apps.finance.bills import create_bill
    from apps.finance.models import Bill, BillStatus

    payload = suggestion.payload or {}
    amount = payload.get("typical_amount_minor")
    gap = payload.get("expected_gap_days")
    last_seen = payload.get("last_seen")
    if not (amount and gap and last_seen):
        return

    try:
        due_on = date.fromisoformat(last_seen) + timedelta(days=int(gap))
    except (TypeError, ValueError):
        return

    # A charge whose next date has already passed tells us nothing about the
    # future — the detector was working on stale history.
    if due_on < timezone.localdate():
        return

    name = (payload.get("merchant") or suggestion.merchant_key or "Recurring charge").strip()
    currency = _suggestion_currency(suggestion)
    if currency is None:
        return

    # Idempotent on re-approval and on the detector re-firing: same payee, same
    # date, already expected.
    if Bill.objects.filter(name=name, due_on=due_on, status=BillStatus.UPCOMING).exists():
        return

    create_bill(
        name=name,
        amount_minor=int(amount),
        currency=currency,
        due_on=due_on,
        notes="Predicted from your history. Edit or cancel it if that's wrong.",
    )


def _suggestion_currency(suggestion: AutomationSuggestion) -> str | None:
    """The currency of the charges this was detected from — never a default.

    Guessing here would put a bill denominated in the wrong currency into a
    projection that refuses to sum across currencies, where it would simply be
    dropped without explanation.
    """
    txn = suggestion.primary_transaction
    return txn.currency if txn is not None else None


@dataclass(frozen=True, slots=True)
class QueueSummary:
    pending: int
    by_kind: dict
    auto_applied: int
    #: Share of decided suggestions that were approved. The engine's own
    #: accuracy, measured against the only judge that matters.
    approval_rate: float | None


def queue_summary() -> QueueSummary:
    """How the automation is doing, by its users' own reckoning."""
    from django.db.models import Count

    pending = AutomationSuggestion.objects.filter(status=ReviewStatus.PENDING)
    by_kind = {
        row["kind"]: row["n"]
        for row in pending.order_by().values("kind").annotate(n=Count("id"))
    }

    approved = AutomationSuggestion.objects.filter(status=ReviewStatus.APPROVED).count()
    rejected = AutomationSuggestion.objects.filter(status=ReviewStatus.REJECTED).count()
    decided = approved + rejected

    return QueueSummary(
        pending=pending.count(),
        by_kind=by_kind,
        auto_applied=AutomationSuggestion.objects.filter(
            status=ReviewStatus.AUTO_APPLIED
        ).count(),
        # `None` rather than a flattering 0 or 100 when nothing has been
        # decided — an accuracy figure from no data is not an accuracy figure.
        approval_rate=round(approved / decided, 2) if decided else None,
    )
