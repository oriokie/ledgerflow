"""Propose a monthly budget from what the workspace already knows.

Writing a first budget from a blank grid is the single hardest task this
product asks of anyone: it demands numbers most people have never measured
("what do I actually spend on groceries?") at the exact moment they have the
least data in front of them. Meanwhile the workspace usually *has* the answer —
months of categorised transactions, recurring bills and templates, expected
income, and savings goals with dates on them. This module assembles those into
a budget a person edits, instead of a grid they must invent.

The arithmetic, in the order it is applied:

1. **History.** Median monthly spend per expense category over the trailing
   complete months (six, so a quarterly bill is not mistaken for a one-off).
   Median, not mean: one car repair must not become a permanent budget line.
   Voided transactions are ignored. A category with no recurring commitment is
   kept only when it landed last month *and* at least once before — the signal
   it is highly likely next month, not a wedding gift.
2. **Floors.** Recurring bills and active expense templates that fall due
   in the budget month are recognized at the full block amount. A quarterly
   premium is $300 that month, not $100 every month — spreading it would
   hide the cash hit. Templates past their end date are skipped.
   A line never proposes less than its floor — trimming a category below its
   own contractual commitments is not a budget, it is a plan to fail.
3. **The envelope.** Expected monthly income, minus debt minimums, minus what
   the household's goals need each month. What is left is what the budget may
   spend in total.
4. **The trim.** If history exceeds the envelope, the *flexible* part of each
   line (above its floor) is scaled down proportionally. Savings goals are
   funded before discretionary history on purpose — that is the entire point
   of a budget that "helps the user stay afloat and meet their goals" rather
   than one that documents drift. If floors alone exceed the envelope, no
   scaling can help; the proposal says so plainly instead of pretending.

Every line carries its rationale, because a suggested number a person cannot
interrogate is a number they will not trust — and rightly so.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.finance.models import (
    Bill,
    BillStatus,
    Category,
    CategoryKind,
    RecurringTransaction,
    RecurringType,
    Transaction,
    TransactionStatus,
)
from apps.finance.schedule import amount_in_month
from apps.goals.models import GoalStatus, SavingsGoal

#: Trailing complete months of history consulted. Six catches quarterly
#: habits (insurance, school fees) that a three-month window sees once and
#: discards as a one-off — those are exactly the non-recurring costs that
#: are highly likely to land again next month.
DEFAULT_MONTHS = 6


def _round_major(minor: int) -> int:
    """Round to a whole major unit. 4_213 -> 4_200 reads as a budget; 4_213
    reads as an accusation."""
    return int(round(minor / 100.0)) * 100


@dataclass(frozen=True)
class ProposedLine:
    category_id: str
    category_name: str
    limit_minor: int
    #: Recurring bills/templates due in the budget month, at the full block
    #: amount. The untrimmable part of the line.
    floor_minor: int
    #: Median monthly history before any trim. 0 when the line exists only
    #: because a commitment vouches for it.
    history_minor: int
    #: The monthly totals the median came from, oldest first.
    observed_months: list[int] = field(default_factory=list)
    rationale: str = ""


@dataclass(frozen=True)
class BudgetProposal:
    currency: str
    as_of: date
    months_considered: int
    #: Expected monthly net income; 0 when the workspace has never told us.
    income_minor: int
    income_known: bool
    debt_minimums_minor: int
    #: What the active goals need per month to stay on schedule.
    savings_target_minor: int
    #: income − debt minimums − savings. What the budget may spend in total.
    envelope_minor: int
    lines: list[ProposedLine] = field(default_factory=list)
    #: 1.0 when history fit the envelope; < 1.0 when flexible spending was
    #: scaled down to make room for the savings target.
    trim_factor: float = 1.0
    #: True when even the floors exceed the envelope — no trim can fix that,
    #: and the proposal must say so rather than paper over it.
    deficit: bool = False

    @property
    def total_minor(self) -> int:
        return sum(line.limit_minor for line in self.lines)

    @property
    def left_over_minor(self) -> int:
        """Unallocated envelope. Positive slack is deliberate — a budget with
        zero headroom is abandoned the first time life happens."""
        return self.envelope_minor - self.total_minor


class NothingToProposeError(Exception):
    """No expense history and no commitments — there is nothing to build from."""


def _dominant_expense_currency(since: date) -> str | None:
    row = (
        Transaction.objects.filter(
            occurred_at__date__gte=since,
            amount_minor__lt=0,
            status__in=[TransactionStatus.POSTED, TransactionStatus.RECONCILED],
        )
        .values("currency")
        .annotate(total=Sum("amount_minor"))
        .order_by("total")  # most negative first = most spent
        .first()
    )
    return row["currency"] if row else None


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _months_back(day: date, n: int) -> date:
    month = day.month - n
    year = day.year
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def propose_budget(*, as_of: date | None = None, months: int = DEFAULT_MONTHS) -> BudgetProposal:
    as_of = as_of or timezone.localdate()
    window_start = _months_back(_month_start(as_of), months)
    window_end = _month_start(as_of)  # exclusive: the current partial month lies

    from apps.income.selectors import committed_income, income_summary

    summary = income_summary(as_of=as_of)
    currency = summary.currency if summary else _dominant_expense_currency(window_start)
    if currency is None:
        raise NothingToProposeError(
            "No income sources and no categorised spending yet — add a few "
            "transactions or an income source first."
        )

    income_minor = summary.monthly_net_minor if summary else 0
    income_known = income_minor > 0

    committed = committed_income(as_of=as_of, currency=currency)
    debt_minimums = committed.debt_minimums_minor if committed else 0

    # ---- what the goals need each month
    from apps.goals import forecasting

    savings_target = 0
    for goal in SavingsGoal.objects.filter(status=GoalStatus.ACTIVE, currency=currency):
        need = goal.planned_monthly_minor or forecasting.required_monthly_minor(goal, as_of=as_of) or 0
        savings_target += max(0, need)

    # ---- median history per category over the trailing complete months
    rows = (
        Transaction.objects.filter(
            occurred_at__date__gte=window_start,
            occurred_at__date__lt=window_end,
            amount_minor__lt=0,
            currency=currency,
            category__kind=CategoryKind.EXPENSE,
            status__in=[TransactionStatus.POSTED, TransactionStatus.RECONCILED],
        )
        .annotate(month=TruncMonth("occurred_at"))
        .values("category_id", "category__name", "month")
        .annotate(total=Sum("amount_minor"))
    )
    by_category: dict[str, dict] = {}
    for row in rows:
        month = row["month"]
        month_start = (
            month.date().replace(day=1) if hasattr(month, "date") else date(month.year, month.month, 1)
        )
        entry = by_category.setdefault(
            str(row["category_id"]), {"name": row["category__name"], "months": [], "month_starts": []}
        )
        entry["months"].append(-row["total"])  # store as positive spend
        entry["month_starts"].append(month_start)

    # ---- commitment floors per category
    floors: dict[str, int] = {}
    floor_names: dict[str, str] = {}
    for bill in Bill.objects.filter(currency=currency, status=BillStatus.UPCOMING).exclude(
        recurrence_frequency=""
    ):
        if bill.category_id is None:
            continue
        key = str(bill.category_id)
        floors[key] = floors.get(key, 0) + amount_in_month(
            amount_minor=bill.amount_minor,
            frequency=bill.recurrence_frequency,
            interval=bill.recurrence_interval,
            anchor=bill.due_on,
            as_of=as_of,
        )
    for template in RecurringTransaction.objects.filter(
        is_active=True, currency=currency, txn_type=RecurringType.EXPENSE
    ):
        if template.ends_on is not None and template.ends_on < as_of:
            continue
        if template.category_id is None:
            continue
        key = str(template.category_id)
        floors[key] = floors.get(key, 0) + amount_in_month(
            amount_minor=template.amount_minor,
            frequency=template.frequency,
            interval=template.interval,
            anchor=template.next_run_on,
            as_of=as_of,
            ends_on=template.ends_on,
        )
    if floors:
        for category in Category.objects.filter(id__in=floors.keys()):
            floor_names[str(category.id)] = category.name

    most_recent_month = _months_back(_month_start(as_of), 1)
    raw: list[dict] = []
    seen = set()
    for key, entry in by_category.items():
        observed = sorted(entry["months"])
        appeared_last_month = most_recent_month in entry["month_starts"]
        # One appearance is an event, not a habit — unless a commitment
        # independently vouches for the category. Non-recurring spend is kept
        # when it landed last month *and* at least once before: that is the
        # signal it is highly likely next month (quarterly insurance, termly
        # fees), not a wedding gift.
        if key not in floors and (len(observed) < 2 or not appeared_last_month):
            continue
        median = int(statistics.median(observed)) if observed else 0
        raw.append(
            {
                "id": key,
                "name": entry["name"],
                "history": median,
                "observed": entry["months"],
                "floor": floors.get(key, 0),
            }
        )
        seen.add(key)
    for key, floor in floors.items():
        if key in seen:
            continue
        raw.append(
            {
                "id": key,
                "name": floor_names.get(key, "Committed"),
                "history": 0,
                "observed": [],
                "floor": floor,
            }
        )

    if not raw:
        raise NothingToProposeError(
            "Not enough categorised spending yet — categorise a month or two of "
            "transactions and try again."
        )

    envelope = income_minor - debt_minimums - savings_target

    floors_total = sum(max(item["floor"], 0) for item in raw)
    desired_total = sum(max(item["history"], item["floor"]) for item in raw)
    flexible_total = desired_total - floors_total

    trim = 1.0
    deficit = False
    if income_known and desired_total > envelope:
        if floors_total >= envelope:
            deficit = True
        elif flexible_total > 0:
            trim = max(0.0, (envelope - floors_total) / flexible_total)

    lines: list[ProposedLine] = []
    for item in sorted(raw, key=lambda entry: -max(entry["history"], entry["floor"])):
        floor = item["floor"]
        desired = max(item["history"], floor)
        flexible = desired - floor
        limit = _round_major(floor + int(flexible * trim)) if not deficit else _round_major(floor)
        limit = max(limit, floor)  # rounding must never dip under a commitment
        if limit <= 0:
            continue

        parts = []
        if item["observed"]:
            monthly = ", ".join(f"{value / 100:,.0f}" for value in item["observed"])
            parts.append(f"median of your last {len(item['observed'])} months ({monthly})")
        if floor:
            parts.append(f"includes {floor / 100:,.0f}/mo of recurring bills")
        if trim < 1.0 and flexible > 0:
            parts.append(f"trimmed {round((1 - trim) * 100)}% to fund your savings goals")
        if deficit and floor:
            parts.append("held at the committed amount")

        lines.append(
            ProposedLine(
                category_id=item["id"],
                category_name=item["name"],
                limit_minor=limit,
                floor_minor=floor,
                history_minor=item["history"],
                observed_months=item["observed"],
                rationale="; ".join(parts).capitalize() if parts else "",
            )
        )

    return BudgetProposal(
        currency=currency,
        as_of=as_of,
        months_considered=months,
        income_minor=income_minor,
        income_known=income_known,
        debt_minimums_minor=debt_minimums,
        savings_target_minor=savings_target,
        envelope_minor=envelope,
        lines=lines,
        trim_factor=round(trim, 4),
        deficit=deficit,
    )


def apply_proposal(proposal: BudgetProposal, *, starts_on: date | None = None, name: str = ""):
    """Create a real budget from a proposal. The person edits it from there —
    this is a first draft they own, not a rule they obey."""
    from . import services

    starts_on = starts_on or _month_start(proposal.as_of)
    budget = services.create_budget(
        name=name or f"Suggested budget — {starts_on:%B %Y}",
        currency=proposal.currency,
        starts_on=starts_on,
    )
    categories = {
        str(c.id): c for c in Category.objects.filter(id__in=[line.category_id for line in proposal.lines])
    }
    for line in proposal.lines:
        category = categories.get(line.category_id)
        if category is None:  # deleted between propose and apply
            continue
        services.add_budget_line(budget=budget, category=category, limit_minor=line.limit_minor)
    return budget
