"""Budget calculations: budgeted vs actual, per line, for a period.

Actual spend is summed over the category's whole subtree using the
materialized `path` (a single `path LIKE 'food.%'` range, no recursive CTE).
Single-period rollover (carry the immediately-preceding period's unspent
amount forward) is supported; deeper multi-period carry is a documented
extension, kept out to bound the cost of a status read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from dateutil.relativedelta import relativedelta
from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.finance.models import Category, Transaction, TransactionStatus

from .models import Budget, BudgetLine, BudgetPeriod

_UNIT = {
    BudgetPeriod.WEEKLY: relativedelta(weeks=1),
    BudgetPeriod.MONTHLY: relativedelta(months=1),
    BudgetPeriod.QUARTERLY: relativedelta(months=3),
    BudgetPeriod.YEARLY: relativedelta(years=1),
}
_COUNTED = Q(status__in=[TransactionStatus.POSTED, TransactionStatus.RECONCILED])


def period_bounds(*, period: str, starts_on: date, as_of: date) -> tuple[date, date]:
    """[start, end) of the period containing `as_of`, aligned to `starts_on`."""
    unit = _UNIT[period]
    approx = {
        BudgetPeriod.WEEKLY: (as_of - starts_on).days // 7,
        BudgetPeriod.MONTHLY: (as_of - starts_on).days // 30,
        BudgetPeriod.QUARTERLY: (as_of - starts_on).days // 90,
        BudgetPeriod.YEARLY: (as_of - starts_on).days // 365,
    }[period]
    n = max(0, approx - 2)
    while starts_on + unit * (n + 1) <= as_of:
        n += 1
    while n > 0 and starts_on + unit * n > as_of:
        n -= 1
    start = starts_on + unit * n
    return start, start + unit


def _subtree_category_ids(category: Category) -> list:
    return list(
        Category.objects.filter(Q(id=category.id) | Q(path__startswith=f"{category.path}.")).values_list(
            "id", flat=True
        )
    )


def _actual_spend_minor(*, category: Category, start: date, end: date) -> int:
    ids = _subtree_category_ids(category)
    start_dt = timezone.make_aware(datetime.combine(start, time.min))
    end_dt = timezone.make_aware(datetime.combine(end, time.min))
    total = Transaction.objects.filter(
        _COUNTED,
        transfer_group__isnull=True,
        amount_minor__lt=0,
        category_id__in=ids,
        occurred_at__gte=start_dt,
        occurred_at__lt=end_dt,
    ).aggregate(s=Coalesce(Sum("amount_minor"), Value(0)))["s"]
    return -total  # magnitude spent


@dataclass(frozen=True, slots=True)
class BudgetLineStatus:
    line_id: str
    category_id: str
    category_name: str
    limit_minor: int
    carried_minor: int
    effective_limit_minor: int
    actual_minor: int

    @property
    def remaining_minor(self) -> int:
        return self.effective_limit_minor - self.actual_minor

    @property
    def percent_used(self) -> float:
        return (
            round(self.actual_minor / self.effective_limit_minor * 100, 1)
            if self.effective_limit_minor
            else 0.0
        )

    @property
    def over_budget(self) -> bool:
        return self.actual_minor > self.effective_limit_minor


def budget_line_status(line: BudgetLine, *, as_of: date) -> BudgetLineStatus:
    start, end = period_bounds(period=line.budget.period, starts_on=line.budget.starts_on, as_of=as_of)
    actual = _actual_spend_minor(category=line.category, start=start, end=end)

    carried = 0
    if line.rollover and start > line.budget.starts_on:
        prev_start = start - _UNIT[line.budget.period]
        prev_actual = _actual_spend_minor(category=line.category, start=prev_start, end=start)
        carried = max(0, line.limit_minor - prev_actual)

    return BudgetLineStatus(
        line_id=str(line.id),
        category_id=str(line.category_id),
        category_name=line.category.name,
        limit_minor=line.limit_minor,
        carried_minor=carried,
        effective_limit_minor=line.limit_minor + carried,
        actual_minor=actual,
    )


def budget_status(budget: Budget, *, as_of: date | None = None) -> list[BudgetLineStatus]:
    as_of = as_of or timezone.localdate()
    lines = budget.lines.select_related("category", "budget").all()
    return [budget_line_status(line, as_of=as_of) for line in lines]
