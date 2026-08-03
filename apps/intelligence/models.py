"""Intelligence persistence.

All models are tenant-scoped (RLS) and reuse the common base:

* `CategorizationSuggestion` — an AI output is *stored as a suggestion*, never
  applied silently. It records what was suggested, by which provider/version,
  with what confidence, and whether a human (or a rule) accepted it. This is
  what keeps the immutable ledger safe from model error: the model proposes,
  a confirmation step disposes, and the whole chain is auditable.

* `AutomationRule` — user-defined "if this, then that" over transactions. Pure,
  deterministic, inspectable — the trustworthy backbone that an LLM can later
  help *author* (natural language -> rule) without ever being in the
  execution path.

* `Insight` — a stored, dedupable observation about the user's finances, with
  the evidence behind it and a human-readable reason. Persisting insights is
  what makes them dismissable, bookmarkable, and comparable over time; a
  recomputed-every-request insight can't be any of those things.

* `Briefing` — a periodic (daily/weekly/monthly) narrative summary that
  references the insights it was built from.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import SoftDeletableModel, TenantOwnedModel


class SuggestionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    SUPERSEDED = "superseded", "Superseded"


class CategorizationSuggestion(TenantOwnedModel):
    """Advisory category suggestion for a transaction. Applying it is a
    separate, explicit step (human tap or an auto-accept rule above a
    confidence threshold) so provenance and consent are always recorded."""

    transaction = models.ForeignKey(
        "finance.Transaction", on_delete=models.CASCADE, related_name="category_suggestions"
    )
    suggested_category = models.ForeignKey(
        "finance.Category", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    confidence = models.FloatField(default=0.0)
    status = models.CharField(
        max_length=12, choices=SuggestionStatus.choices, default=SuggestionStatus.PENDING
    )
    # provenance — which provider produced this and why
    provider = models.CharField(max_length=64)
    provider_kind = models.CharField(max_length=16)
    provider_version = models.CharField(max_length=16)
    rationale = models.CharField(max_length=255, blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "status"]),
            models.Index(fields=["tenant_id", "transaction"]),
        ]

    def __str__(self) -> str:
        return f"suggest {self.suggested_category_id} @ {self.confidence:.2f} ({self.status})"


class AutomationRule(SoftDeletableModel):
    """If-this-then-that over transactions. Evaluated deterministically by the
    automation engine on new/imported transactions.

    Conditions and actions are JSON so the rule vocabulary can grow without a
    migration, but every action is validated against a known allow-list at
    execution time — an automation can only invoke real, safe engine
    capabilities (categorize, tag, flag), never arbitrary writes.
    """

    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=100)  # lower runs first; first match can stop

    # e.g. {"all": [{"field": "payee_normalized", "op": "contains", "value": "netflix"}]}
    conditions = models.JSONField(default=dict)
    # e.g. [{"type": "set_category", "slug": "subscriptions"}, {"type": "add_tag", "name": "recurring"}]
    actions = models.JSONField(default=list)
    stop_processing = models.BooleanField(default=False)  # if matched, skip lower-priority rules

    # bookkeeping
    match_count = models.PositiveIntegerField(default=0)
    last_matched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "is_active", "priority"])]
        ordering = ["priority", "id"]

    def __str__(self) -> str:
        return f"{self.name} (priority {self.priority})"


# --------------------------------------------------------------------------- insights
class InsightKind(models.TextChoices):
    """The coach's vocabulary.

    Stored rather than derived so an insight stays interpretable after the
    detector that produced it has changed — a value that disappears from the
    code shouldn't make historical rows unreadable.
    """

    SPENDING_ANOMALY = "spending_anomaly", "Spending anomaly"
    OVERSPENDING = "overspending", "Overspending warning"
    BUDGET_RECOMMENDATION = "budget_recommendation", "Budget recommendation"
    SAVINGS_OPPORTUNITY = "savings_opportunity", "Savings opportunity"
    DUPLICATE_TRANSACTION = "duplicate_transaction", "Possible duplicate"
    LARGE_PURCHASE = "large_purchase", "Large purchase"
    MERCHANT_CHANGE = "merchant_change", "Merchant price change"
    SALARY_CHANGE = "salary_change", "Income change"
    CASHFLOW_RISK = "cashflow_risk", "Cash flow risk"
    SUBSCRIPTION_REVIEW = "subscription_review", "Subscription review"
    GOAL_RECOMMENDATION = "goal_recommendation", "Goal recommendation"
    DEBT_RECOMMENDATION = "debt_recommendation", "Debt recommendation"
    HEALTH_IMPROVEMENT = "health_improvement", "Financial health"
    PROMO_EXPIRY = "promo_expiry", "Promotional rate ending"
    RATE_INCREASE = "rate_increase", "Rate increase"
    REFINANCE_OPPORTUNITY = "refinance_opportunity", "Refinancing opportunity"
    HIGH_FEES = "high_fees", "High fees"
    OFFSET_OPPORTUNITY = "offset_opportunity", "Offset opportunity"
    DEBT_MILESTONE = "debt_milestone", "Debt milestone"


class InsightSeverity(models.TextChoices):
    """How much attention this deserves.

    Ordered by urgency, not by sentiment: `CRITICAL` is reserved for things
    with a deadline (a predicted overdraft), because a product that shouts
    about everything is one users learn to ignore.
    """

    CRITICAL = "critical", "Critical"
    WARNING = "warning", "Warning"
    OPPORTUNITY = "opportunity", "Opportunity"
    INFO = "info", "Informational"


class InsightStatus(models.TextChoices):
    NEW = "new", "New"
    SEEN = "seen", "Seen"
    BOOKMARKED = "bookmarked", "Bookmarked"
    DISMISSED = "dismissed", "Dismissed"
    ACTED = "acted", "Acted on"


class Insight(TenantOwnedModel):
    """One observation about the user's finances, with its evidence and reason.

    Two design decisions carry most of the weight here:

    **`dedupe_key` is unique per tenant.** The coach runs on a schedule, so the
    same condition is detected every day. Without a stable key the user would
    accumulate one identical "you're over budget on groceries" every morning,
    and dismissing it would achieve nothing. The key encodes the *condition*,
    not the run — so a re-detection updates the existing row instead of adding
    to a pile.

    **`rationale` and `evidence` are mandatory, not decoration.** An insight a
    user can't check is one they can't trust. `rationale` says why in a
    sentence; `evidence` carries the figures it was computed from, so the claim
    is auditable rather than oracular. This also future-proofs the LLM seam: a
    model-authored insight must supply the same two things, which is what stops
    it from being able to assert something it cannot support.
    """

    kind = models.CharField(max_length=32, choices=InsightKind.choices)
    severity = models.CharField(max_length=12, choices=InsightSeverity.choices)
    status = models.CharField(max_length=12, choices=InsightStatus.choices, default=InsightStatus.NEW)

    title = models.CharField(max_length=160)
    body = models.TextField()
    #: The WHY, in one sentence. Never blank — see the class docstring.
    rationale = models.TextField()
    #: The figures behind the claim, e.g. {"spent_minor": 42000, "limit_minor": 30000}.
    evidence = models.JSONField(default=dict, blank=True)
    #: Machine-actionable follow-up mapping to a real engine capability.
    action = models.JSONField(default=dict, blank=True)

    #: 0-100. Computed at generation time; see `scoring.py`.
    priority_score = models.PositiveSmallIntegerField(default=0)

    #: Stable identity of the *condition*, not the run.
    dedupe_key = models.CharField(max_length=200)

    #: The window this insight describes, for period-scoped reviews.
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    #: After this date the insight is stale and hidden. An insight about last
    #: month's groceries stops being actionable once the month turns.
    expires_on = models.DateField(null=True, blank=True)

    # provenance — which provider produced this, and at what version
    provider = models.CharField(max_length=64)
    provider_kind = models.CharField(max_length=16)
    provider_version = models.CharField(max_length=16)

    #: Optional links back to the records the insight is about.
    related_transaction = models.ForeignKey(
        "finance.Transaction", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    related_category = models.ForeignKey(
        "finance.Category", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    related_account = models.ForeignKey(
        "finance.FinancialAccount", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    last_detected_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "dedupe_key"], name="uniq_insight_dedupe"
            ),
            models.CheckConstraint(
                condition=models.Q(priority_score__lte=100), name="insight_score_max"
            ),
        ]
        indexes = [
            # The feed query: live insights, most important first.
            models.Index(
                fields=["tenant_id", "status", "-priority_score"], name="insight_feed_idx"
            ),
            models.Index(fields=["tenant_id", "kind"], name="insight_kind_idx"),
            models.Index(fields=["tenant_id", "expires_on"], name="insight_expiry_idx"),
        ]
        ordering = ["-priority_score", "-created_at"]

    def __str__(self) -> str:
        return f"{self.kind}: {self.title} ({self.severity})"

    @property
    def is_dismissed(self) -> bool:
        return self.status == InsightStatus.DISMISSED

    @property
    def is_bookmarked(self) -> bool:
        return self.status == InsightStatus.BOOKMARKED


class BriefingPeriod(models.TextChoices):
    DAILY = "daily", "Daily briefing"
    WEEKLY = "weekly", "Weekly review"
    MONTHLY = "monthly", "Monthly review"


class Briefing(TenantOwnedModel):
    """A periodic narrative summary over a window of insights.

    Unique per (tenant, period, period_start) so a scheduled regeneration
    refreshes the existing briefing rather than producing duplicates — the same
    idempotency discipline as `Insight.dedupe_key`.

    The `summary` is prose assembled from the insights, and `headline` is the
    single most important thing. Both are produced by a provider, so an LLM can
    later write genuinely fluent copy over exactly the same structured inputs
    without any caller changing.
    """

    period = models.CharField(max_length=10, choices=BriefingPeriod.choices)
    period_start = models.DateField()
    period_end = models.DateField()

    headline = models.CharField(max_length=200)
    summary = models.TextField()
    #: Structured figures the summary was written from, so the prose can always
    #: be checked against the numbers.
    metrics = models.JSONField(default=dict, blank=True)
    insights = models.ManyToManyField(Insight, related_name="briefings", blank=True)

    provider = models.CharField(max_length=64)
    provider_kind = models.CharField(max_length=16)
    provider_version = models.CharField(max_length=16)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "period", "period_start"], name="uniq_briefing_period"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "period", "-period_start"], name="briefing_period_idx"),
        ]
        ordering = ["-period_start"]

    def __str__(self) -> str:
        return f"{self.period} briefing {self.period_start}"


# --------------------------------------------------------------------- automation
class SuggestionKind(models.TextChoices):
    """What a suggestion proposes.

    Mirrors `detect.SuggestionKind`. Duplicated because the detection engine
    must stay free of Django and this must be a proper choices field; a test
    asserts the two agree so they cannot drift.
    """

    CATEGORY = "category", "Category"
    TRANSFER = "transfer", "Transfer"
    DUPLICATE = "duplicate", "Possible duplicate"
    REFUND = "refund", "Refund"
    RECURRING = "recurring", "Recurring charge"
    SPLIT = "split", "Worth splitting"
    INCOME = "income", "Income"


class ReviewStatus(models.TextChoices):
    PENDING = "pending", "Awaiting review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    #: Applied automatically because confidence cleared the bar. Still recorded
    #: and still reversible — an unreviewable action is not automation, it is
    #: something happening to you.
    AUTO_APPLIED = "auto_applied", "Applied automatically"


class AutomationSuggestion(TenantOwnedModel):
    """One proposal from the detection engine, awaiting a decision.

    Persisted rather than recomputed so a decision can be recorded against it,
    and so the review queue is stable while someone works through it — a list
    that reshuffles under the user as they tap is unusable.

    `dedupe_key` identifies the *finding*, not the run. The scanner is expected
    to run repeatedly over overlapping windows, and without a stable identity
    every scan would re-propose everything the user already dismissed.
    """

    kind = models.CharField(max_length=16, choices=SuggestionKind.choices)
    status = models.CharField(
        max_length=14, choices=ReviewStatus.choices, default=ReviewStatus.PENDING
    )
    #: 0–1, from the detector. Never rounded up for presentation.
    confidence = models.FloatField(default=0.0)
    #: Why, in the user's own figures. Mandatory by contract — a suggestion
    #: nobody can check is one nobody should act on.
    reason = models.CharField(max_length=400)
    #: Detector-specific detail: the proposed category, the split parts, the
    #: cadence, the matched amounts.
    payload = models.JSONField(default=dict, blank=True)

    transactions = models.ManyToManyField(
        "finance.Transaction", related_name="automation_suggestions", blank=True
    )
    #: Denormalised so the review queue can be listed and grouped without
    #: touching the join table for every row.
    primary_transaction = models.ForeignKey(
        "finance.Transaction",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
    )
    merchant_key = models.CharField(max_length=120, blank=True, default="")

    dedupe_key = models.CharField(max_length=200)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by_id = models.UUIDField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "dedupe_key"], name="uniq_automation_suggestion"
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__gte=0) & models.Q(confidence__lte=1),
                name="automation_confidence_range",
            ),
        ]
        indexes = [
            # The review queue: pending work, most confident first.
            models.Index(
                fields=["tenant_id", "status", "-confidence"], name="autosug_queue_idx"
            ),
            models.Index(fields=["tenant_id", "kind"], name="autosug_kind_idx"),
        ]
        ordering = ["-confidence", "-created_at"]

    def __str__(self) -> str:
        return f"{self.kind} ({self.confidence:.0%})"


class MerchantProfile(TenantOwnedModel):
    """What this workspace has learned about one merchant.

    The learning store. Category counts accumulate from decisions the user
    actually made, so suggestions are grounded in their own behaviour rather
    than a shared model — two households categorise the same supermarket
    differently and both are right.

    Kept per tenant for the same reason. A global model would be confidently
    wrong for whichever household disagrees with the majority.
    """

    #: Canonical grouping key from `detect.merchant_key`.
    key = models.CharField(max_length=120)
    #: Best display name seen so far, after normalisation.
    display_name = models.CharField(max_length=160)
    #: {category_id: times chosen}. A dict rather than rows because it is
    #: always read and written whole.
    category_counts = models.JSONField(default=dict, blank=True)
    #: Raw descriptors that normalised to this key, for auditability when a
    #: user asks why two things were grouped.
    seen_descriptors = models.JSONField(default=list, blank=True)

    transaction_count = models.PositiveIntegerField(default=0)
    total_amount_minor = models.BigIntegerField(default=0)
    first_seen_on = models.DateField(null=True, blank=True)
    last_seen_on = models.DateField(null=True, blank=True)

    #: Set when the engine has concluded this merchant bills on a cadence.
    is_recurring = models.BooleanField(default=False)
    recurring_cadence = models.CharField(max_length=16, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "key"], name="uniq_merchant_profile_key"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "-transaction_count"], name="merchant_freq_idx"),
        ]

    def __str__(self) -> str:
        return self.display_name or self.key

    @property
    def dominant_category_id(self) -> str | None:
        """The category this merchant usually gets, or `None` when genuinely
        split — a coin toss presented as a recommendation is worse than
        silence."""
        if not self.category_counts:
            return None
        category_id, count = max(self.category_counts.items(), key=lambda kv: kv[1])
        total = sum(self.category_counts.values())
        return category_id if total and count / total >= 0.6 else None
