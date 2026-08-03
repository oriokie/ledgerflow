"""Deterministic coach — the shipping implementation of `InsightProvider`.

Every insight here is derived from figures already computed by the engine, and
every one carries the numbers it was built from. Nothing is inferred, estimated
or phrased more confidently than the evidence supports.

Three rules govern the wording, and they matter as much as the detection:

1. **Say the number.** "You've spent £412 of your £350 grocery budget" is
   checkable; "you're overspending" is an accusation. A user who can verify one
   insight will trust the next.

2. **Never assert what was only observed.** Two identical charges on one day
   are a *candidate* duplicate, not an error — the copy says "worth checking",
   because telling someone they were double-charged when they bought two
   coffees costs more trust than the catch was worth.

3. **Don't manufacture urgency.** Severity is reserved: `CRITICAL` requires a
   deadline. A coach that shouts about everything gets muted.

This is a real, tested provider, not a placeholder. An LLM implementing the
same protocol is an upgrade path, not a dependency — and it inherits this as
its offline fallback.
"""

from __future__ import annotations

from datetime import timedelta

from ..models import InsightKind, InsightSeverity
from ..protocols import (
    BriefingDraft,
    CoachContext,
    InsightCandidate,
    Provenance,
    ProviderKind,
)

VERSION = "1.0"

#: Below this share of a budget line, an overspend isn't worth a notification.
OVERSPEND_TOLERANCE = 1.0

#: Category growth beyond this month-on-month is worth surfacing.
CATEGORY_SPIKE_THRESHOLD = 0.4

#: Savings rate below this suggests there's room to look at.
LOW_SAVINGS_RATE = 0.1

#: Annualised subscription cost worth a second look, as a share of monthly
#: outgoings. Relative so it means the same at any income.
SUBSCRIPTION_REVIEW_FRACTION = 0.5


def _money(minor: int, currency: str) -> str:
    """Plain-language amount. Whole units only — pennies in prose are noise."""
    return f"{currency} {abs(minor) / 100:,.0f}"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    """`3 accounts` / `1 account`.

    Insight copy is the most-read prose in the product and it is generated, so
    a hardcoded trailing "s" shows up as "across 1 accounts" the moment a user
    has exactly one of something — which is the common case for the very users
    these insights are trying to reassure.
    """
    return f"{count} {singular if abs(count) == 1 else (plural or singular + 's')}"


class RuleBasedCoach:
    """Turns a `CoachContext` into candidate insights."""

    name = "RuleBasedCoach"
    kind = ProviderKind.RULE
    version = VERSION

    def _provenance(self, rationale: str) -> Provenance:
        return Provenance(
            provider=self.name, kind=self.kind, version=self.version, rationale=rationale
        )

    # ------------------------------------------------------------------ budget
    def _overspending(self, ctx: CoachContext) -> list[InsightCandidate]:
        out: list[InsightCandidate] = []
        for line in ctx.budget_lines:
            limit = line.get("limit_minor") or 0
            spent = line.get("spent_minor") or 0
            if limit <= 0 or spent <= limit * OVERSPEND_TOLERANCE:
                continue
            over = spent - limit
            name = line.get("category_name") or "a category"
            out.append(
                InsightCandidate(
                    kind=InsightKind.OVERSPENDING,
                    severity=InsightSeverity.WARNING,
                    title=f"Over budget on {name}",
                    body=(
                        f"You've spent {_money(spent, ctx.currency)} against a "
                        f"{_money(limit, ctx.currency)} limit — {_money(over, ctx.currency)} over."
                    ),
                    rationale=(
                        f"Your {name} budget line is set to {_money(limit, ctx.currency)} for this "
                        f"period, and transactions categorised to it total "
                        f"{_money(spent, ctx.currency)}."
                    ),
                    dedupe_key=f"overspending:{line.get('category_id')}:{line.get('period_end')}",
                    evidence={
                        "limit_minor": limit,
                        "spent_minor": spent,
                        "over_minor": over,
                        "percent": line.get("percent"),
                    },
                    action={"action": "review_category", "category_id": line.get("category_id")},
                    related_category_id=line.get("category_id"),
                    expires_on=line.get("period_end"),
                    provenance=self._provenance("budget line exceeded"),
                )
            )
        return out

    def _budget_recommendations(self, ctx: CoachContext) -> list[InsightCandidate]:
        """Suggest a budget where spending is concentrated but unbudgeted."""
        if ctx.budget_lines:
            return []
        top = sorted(ctx.category_trends, key=lambda t: -t["current_minor"])[:1]
        return [
            InsightCandidate(
                kind=InsightKind.BUDGET_RECOMMENDATION,
                severity=InsightSeverity.OPPORTUNITY,
                title="Set a budget to see where you stand",
                body=(
                    f"{t['category_name']} is your largest tracked category this month at "
                    f"{_money(t['current_minor'], ctx.currency)}. A limit there would give you "
                    "something to measure against."
                ),
                rationale=(
                    "You have no active budget, so nothing is being compared to a limit. "
                    f"{t['category_name']} is where most of your categorised spending goes."
                ),
                dedupe_key=f"budget_rec:{t['category_id']}:{ctx.as_of.strftime('%Y-%m')}",
                evidence={"category_id": t["category_id"], "spent_minor": t["current_minor"]},
                action={"action": "create_budget", "category_id": t["category_id"]},
                related_category_id=t["category_id"],
                provenance=self._provenance("no active budget"),
            )
            for t in top
        ]

    # ------------------------------------------------------------- anomalies
    def _spending_anomalies(self, ctx: CoachContext) -> list[InsightCandidate]:
        out: list[InsightCandidate] = []
        for trend in ctx.category_trends:
            if trend["delta_pct"] < CATEGORY_SPIKE_THRESHOLD:
                continue
            out.append(
                InsightCandidate(
                    kind=InsightKind.SPENDING_ANOMALY,
                    severity=InsightSeverity.WARNING,
                    title=f"{trend['category_name']} is up {trend['delta_pct'] * 100:.0f}%",
                    body=(
                        f"You've spent {_money(trend['current_minor'], ctx.currency)} on "
                        f"{trend['category_name']} this month, against "
                        f"{_money(trend['previous_minor'], ctx.currency)} last month."
                    ),
                    rationale=(
                        "This compares the total of transactions categorised to "
                        f"{trend['category_name']} this month against the same figure for last "
                        "month. A one-off purchase can explain it."
                    ),
                    dedupe_key=f"anomaly:{trend['category_id']}:{ctx.as_of.strftime('%Y-%m')}",
                    evidence=dict(trend),
                    related_category_id=trend["category_id"],
                    provenance=self._provenance("month-on-month category increase"),
                    confidence=0.8,
                )
            )
        return out

    def _duplicates(self, ctx: CoachContext) -> list[InsightCandidate]:
        return [
            InsightCandidate(
                kind=InsightKind.DUPLICATE_TRANSACTION,
                severity=InsightSeverity.INFO,
                title=f"Repeated charge from {d['payee']}",
                body=(
                    f"{d['count']} charges of {_money(d['amount_minor'], ctx.currency)} from "
                    f"{d['payee']} on {d['occurred_on']:%-d %b}. Worth checking whether that's right."
                ),
                # Observed, not asserted: two identical coffees in a day are normal.
                rationale=(
                    "Two or more transactions with the same payee and amount landed on the same "
                    "day. That's often legitimate, so this is a prompt to check rather than a "
                    "problem we've confirmed."
                ),
                dedupe_key=f"duplicate:{d['transaction_id']}",
                evidence=dict(d),
                action={"action": "review_transaction", "transaction_id": d["transaction_id"]},
                related_transaction_id=d["transaction_id"],
                provenance=self._provenance("same payee, amount and day"),
                confidence=0.5,
            )
            for d in ctx.possible_duplicates
        ]

    def _large_purchases(self, ctx: CoachContext) -> list[InsightCandidate]:
        return [
            InsightCandidate(
                kind=InsightKind.LARGE_PURCHASE,
                severity=InsightSeverity.INFO,
                title=f"Large purchase: {t['payee']}",
                body=(
                    f"{_money(t['amount_minor'], ctx.currency)} on {t['occurred_on']:%-d %b} — "
                    "one of your bigger transactions this period."
                ),
                rationale=(
                    "This transaction is large relative to your own typical monthly spending, "
                    "not against a fixed threshold."
                ),
                dedupe_key=f"large:{t['transaction_id']}",
                evidence=dict(t),
                related_transaction_id=t["transaction_id"],
                provenance=self._provenance("large relative to monthly baseline"),
                confidence=0.9,
            )
            for t in ctx.large_transactions[:3]
        ]

    def _merchant_changes(self, ctx: CoachContext) -> list[InsightCandidate]:
        """A recurring merchant's typical charge has moved.

        Reported in both directions. A price *drop* is genuinely useful — it
        confirms a renegotiation worked, or flags a service that quietly
        downgraded — and a coach that only ever delivers bad news is one people
        stop opening.
        """
        out: list[InsightCandidate] = []
        for change in ctx.merchant_changes:
            rose = change["delta_pct"] > 0
            pct = abs(change["delta_pct"]) * 100
            out.append(
                InsightCandidate(
                    kind=InsightKind.MERCHANT_CHANGE,
                    # Informational either way: a price change is worth knowing,
                    # not worth alarming about.
                    severity=InsightSeverity.INFO,
                    title=f"{change['payee']} is {'up' if rose else 'down'} {pct:.0f}%",
                    body=(
                        f"Your typical charge went from "
                        f"{_money(change['previous_minor'], ctx.currency)} to "
                        f"{_money(change['current_minor'], ctx.currency)}."
                    ),
                    rationale=(
                        "This compares the average amount you paid this merchant over the last 30 "
                        "days against the 30 days before that. Merchants with fewer than two "
                        "earlier charges are skipped, since there's no typical amount to compare to."
                    ),
                    dedupe_key=f"merchant:{change['payee']}:{ctx.as_of.strftime('%Y-%m')}",
                    evidence=dict(change),
                    provenance=self._provenance("merchant average charge moved"),
                    confidence=0.7,
                )
            )
        return out

    def _income_changes(self, ctx: CoachContext) -> list[InsightCandidate]:
        """Total income moved materially against last month."""
        out: list[InsightCandidate] = []
        for change in ctx.income_changes:
            rose = change["delta_pct"] > 0
            pct = abs(change["delta_pct"]) * 100
            out.append(
                InsightCandidate(
                    kind=InsightKind.SALARY_CHANGE,
                    # A drop is worth flagging; a rise is good news, not a warning.
                    severity=InsightSeverity.INFO if rose else InsightSeverity.WARNING,
                    title=f"Income is {'up' if rose else 'down'} {pct:.0f}% this month",
                    body=(
                        f"{_money(change['current_minor'], ctx.currency)} in so far, against "
                        f"{_money(change['previous_minor'], ctx.currency)} last month."
                        + ("" if rose else " Worth checking your budgets still fit.")
                    ),
                    rationale=(
                        "This totals money coming in this month against the same figure for last "
                        "month. Pay varies for ordinary reasons — overtime, a five-week month, a "
                        "bonus — so a single month's change isn't necessarily a trend."
                    ),
                    dedupe_key=f"income:{change['period_start']}",
                    evidence={k: v for k, v in change.items() if k != "period_start"},
                    action={} if rose else {"action": "review_category"},
                    provenance=self._provenance("month-on-month income change"),
                    confidence=0.7,
                )
            )
        return out

    def _debt_signals(self, ctx: CoachContext) -> list[InsightCandidate]:
        """Adapt the debt module's findings into insights.

        A pass-through by design: the debt app already computed these with the
        rate timelines, fees and offsets it owns, and each arrives with its own
        rationale and evidence. Re-deriving them here would be a second source
        of truth for the same claim.
        """
        severity_map = {
            "critical": InsightSeverity.CRITICAL,
            "warning": InsightSeverity.WARNING,
            "opportunity": InsightSeverity.OPPORTUNITY,
            "info": InsightSeverity.INFO,
        }
        out: list[InsightCandidate] = []
        for signal in ctx.debt_signals:
            kind = signal.get("kind")
            if kind not in InsightKind.values:
                continue
            out.append(
                InsightCandidate(
                    kind=kind,
                    severity=severity_map.get(signal.get("severity"), InsightSeverity.INFO),
                    title=signal["title"],
                    body=signal["body"],
                    rationale=signal["rationale"],
                    dedupe_key=signal["dedupe_key"],
                    evidence=signal.get("evidence", {}),
                    action=signal.get("action") or {},
                    related_account_id=signal.get("account_id"),
                    provenance=self._provenance("debt module analysis"),
                )
            )
        return out

    # ------------------------------------------------------------- cash flow
    def _cashflow_risk(self, ctx: CoachContext) -> list[InsightCandidate]:
        risk = ctx.cashflow_risk
        if not risk or not risk.get("first_negative_on"):
            return []
        when = risk["first_negative_on"]
        return [
            InsightCandidate(
                kind=InsightKind.CASHFLOW_RISK,
                # The only family that earns CRITICAL: it has a date attached.
                severity=InsightSeverity.CRITICAL,
                title=f"Balance projected to go negative on {when:%-d %b}",
                body=(
                    f"Based on your scheduled income and bills, your balance is projected to reach "
                    f"{_money(risk.get('lowest_balance_minor', 0), ctx.currency)} on "
                    f"{risk.get('lowest_balance_on', when):%-d %b}."
                ),
                rationale=(
                    "This projects forward from your current liquid balance, applying every "
                    "recurring transaction and unpaid bill scheduled between now and then."
                ),
                dedupe_key=f"cashflow_risk:{when.isoformat()}",
                evidence={k: v for k, v in risk.items()},
                action={"action": "open_cashflow_calendar"},
                expires_on=when,
                provenance=self._provenance("projected overdraft in the cash-flow calendar"),
            )
        ]

    # ----------------------------------------------------------- opportunities
    def _savings_opportunity(self, ctx: CoachContext) -> list[InsightCandidate]:
        # None means "not measured" — saying someone saves nothing when we
        # have no income history is a claim about data we don't hold.
        if ctx.savings_rate is None or ctx.savings_rate >= LOW_SAVINGS_RATE:
            return []
        return [
            InsightCandidate(
                kind=InsightKind.SAVINGS_OPPORTUNITY,
                severity=InsightSeverity.OPPORTUNITY,
                title="Very little is being set aside",
                body=(
                    f"Over the last three months you've kept about {ctx.savings_rate * 100:.0f}% of "
                    "what came in. Even a small automatic transfer on payday tends to stick better "
                    "than saving what's left at month end."
                ),
                rationale=(
                    "Savings rate is total inflow minus total outflow, divided by inflow, over "
                    "your last three months of activity."
                ),
                dedupe_key=f"savings_rate:{ctx.as_of.strftime('%Y-%m')}",
                evidence={"savings_rate": ctx.savings_rate},
                action={"action": "create_goal", "kind": "emergency_fund"},
                provenance=self._provenance("three-month savings rate"),
            )
        ]

    def _subscriptions(self, ctx: CoachContext) -> list[InsightCandidate]:
        if not ctx.subscriptions:
            return []
        total_annual = sum(s["annual_minor"] for s in ctx.subscriptions)
        top = ctx.subscriptions[0]
        return [
            InsightCandidate(
                kind=InsightKind.SUBSCRIPTION_REVIEW,
                severity=InsightSeverity.OPPORTUNITY,
                title=f"{len(ctx.subscriptions)} recurring charges, {_money(total_annual, ctx.currency)} a year",
                body=(
                    f"Your largest is {top['name']} at {_money(top['annual_minor'], ctx.currency)} "
                    "a year. Worth a look for anything you've stopped using."
                ),
                # Annualising is the whole point: £12/month doesn't feel like a
                # decision, £144/year does.
                rationale=(
                    "This annualises every active recurring expense by its frequency, so the "
                    "yearly cost of each is visible rather than the monthly one."
                ),
                dedupe_key=f"subscriptions:{ctx.as_of.strftime('%Y-%m')}",
                evidence={"count": len(ctx.subscriptions), "annual_total_minor": total_annual},
                action={"action": "open_recurring"},
                provenance=self._provenance("annualised recurring expenses"),
            )
        ]

    def _goals(self, ctx: CoachContext) -> list[InsightCandidate]:
        return [
            InsightCandidate(
                kind=InsightKind.GOAL_RECOMMENDATION,
                severity=InsightSeverity.OPPORTUNITY,
                title=g["title"],
                body=g["rationale"],
                rationale=(
                    "Suggested from your own figures — this target is derived from your measured "
                    "spending and balances, not a generic recommendation."
                ),
                dedupe_key=f"goal_rec:{g['kind']}",
                evidence={"suggested_target_minor": g["suggested_target_minor"]},
                action={"action": "create_goal", "kind": g["kind"]},
                provenance=self._provenance("goal recommendation engine"),
            )
            for g in ctx.goal_suggestions
        ]

    def _debt(self, ctx: CoachContext) -> list[InsightCandidate]:
        if not ctx.debts:
            return []
        largest = ctx.debts[0]
        total = sum(d["balance_minor"] for d in ctx.debts)
        return [
            InsightCandidate(
                kind=InsightKind.DEBT_RECOMMENDATION,
                severity=InsightSeverity.WARNING,
                title=f"{_money(total, ctx.currency)} outstanding across {_plural(len(ctx.debts), 'account')}",
                body=(
                    f"{largest['name']} is the one to target"
                    + (
                        f" at {largest['apr']:.1f}% — about "
                        f"{_money(largest['monthly_interest_minor'], ctx.currency)} a month in interest."
                        if largest.get("apr")
                        else f" at {_money(largest['balance_minor'], ctx.currency)}."
                    )
                ),
                rationale=(
                    "These are the current balances on your credit card and loan accounts, "
                    + (
                        "ordered by interest rate — clearing the most expensive first costs least overall."
                        if largest.get("apr")
                        else "ordered by size. Add interest rates to rank them by what they actually cost."
                    )
                ),
                action={"action": "open_debt_planner"},
                dedupe_key=f"debt:{ctx.as_of.strftime('%Y-%m')}",
                evidence={"total_minor": total, "accounts": len(ctx.debts)},
                related_account_id=largest["account_id"],
                provenance=self._provenance("outstanding liability balances"),
            )
        ]

    def _health(self, ctx: CoachContext) -> list[InsightCandidate]:
        health = ctx.health
        if not health or not health.get("components"):
            return []
        weakest = min(health["components"], key=lambda c: c.get("score", 100))
        return [
            InsightCandidate(
                kind=InsightKind.HEALTH_IMPROVEMENT,
                severity=InsightSeverity.INFO,
                title=f"Your weakest area is {weakest['name']}",
                body=weakest.get("detail", ""),
                rationale=(
                    f"Your overall financial health score is {health.get('score')} "
                    f"({health.get('band')}). {weakest['name']} scores lowest of its components, "
                    "so it's where an improvement moves the number most."
                ),
                dedupe_key=f"health:{weakest['name']}:{ctx.as_of.strftime('%Y-%m')}",
                evidence={"score": health.get("score"), "component": weakest},
                provenance=self._provenance("lowest-scoring health component"),
            )
        ]

    # ------------------------------------------------------------------ entry
    def generate(self, context: CoachContext) -> list[InsightCandidate]:
        detectors = (
            self._cashflow_risk,
            self._debt_signals,
            self._overspending,
            self._spending_anomalies,
            self._debt,
            self._duplicates,
            self._large_purchases,
            self._income_changes,
            self._savings_opportunity,
            self._merchant_changes,
            self._subscriptions,
            self._goals,
            self._budget_recommendations,
            self._health,
        )
        out: list[InsightCandidate] = []
        for detect in detectors:
            out.extend(detect(context))
        return out


class TemplateNarrator:
    """Assembles briefing prose from scored insights.

    Templated rather than generated: the copy is predictable, checkable, and
    costs nothing to run. An LLM narrator implementing `NarrativeProvider`
    would write over exactly these inputs — the split between *detecting* a
    condition and *describing* it is what makes that swap possible without
    touching detection.
    """

    name = "TemplateNarrator"
    kind = ProviderKind.RULE
    version = VERSION

    _PERIOD_LABEL = {"daily": "today", "weekly": "this week", "monthly": "this month"}

    def write_briefing(
        self, *, period: str, context: CoachContext, insights: list[InsightCandidate]
    ) -> BriefingDraft:
        label = self._PERIOD_LABEL.get(period, "recently")
        currency = context.currency

        critical = [i for i in insights if i.severity == InsightSeverity.CRITICAL]
        warnings = [i for i in insights if i.severity == InsightSeverity.WARNING]
        opportunities = [i for i in insights if i.severity == InsightSeverity.OPPORTUNITY]

        # The headline is promoted from the insights, so whichever one it came
        # from must not be repeated in the body. It was: the headline, the
        # first clause of the summary, and the first insight card all carried
        # the same sentence verbatim, three times within one screen. The body's
        # job is what the headline did *not* already say.
        lead = (critical or warnings or opportunities or [None])[0]
        headline = lead.title if lead else f"Nothing needs your attention {label}"

        def clause(group: list, phrase: str) -> str | None:
            """Count the whole group, but only name the ones not already read."""
            rest = [i for i in group if i is not lead]
            if not rest:
                # The count still reaches the reader — it is a metric on the
                # card. Restating the headline to fill a sentence is not a
                # summary, it is an echo.
                return None
            return f"{len(group)} {phrase}: " + "; ".join(i.title for i in rest[:3]) + "."

        parts: list[str] = []
        if critical:
            need = clause(critical, f"thing{'s' if len(critical) > 1 else ''} need attention now")
            if need:
                parts.append(need)
        if warnings:
            worth = clause(warnings, "worth a look")
            if worth:
                parts.append(worth)
        if opportunities:
            opp = clause(opportunities, f"opportunit{'ies' if len(opportunities) > 1 else 'y'}")
            if opp:
                parts.append(opp)
        if not parts and not lead:
            parts.append(
                f"Nothing unusual {label}. Your spending is tracking against its recent pattern."
            )

        if context.savings_rate is not None:
            parts.append(f"You're keeping about {context.savings_rate * 100:.0f}% of what comes in.")

        return BriefingDraft(
            headline=headline,
            summary=" ".join(parts),
            metrics={
                "currency": currency,
                "savings_rate": context.savings_rate,
                "insight_count": len(insights),
                "critical_count": len(critical),
                "warning_count": len(warnings),
                "opportunity_count": len(opportunities),
            },
            provenance=Provenance(
                provider=self.name,
                kind=self.kind,
                version=self.version,
                rationale="assembled from scored insights",
            ),
        )


__all__ = ["RuleBasedCoach", "TemplateNarrator", "VERSION", "timedelta"]
