"""Budgeting service layer. Budgets never touch the ledger — they're a
read-heavy overlay comparing budgeted limits to actual posted spending."""

from __future__ import annotations

from datetime import date

from django.db import transaction

from apps.finance.models import Category, CategoryKind

from .models import Budget, BudgetLine, BudgetPeriod


class BudgetError(Exception): ...


@transaction.atomic
def create_budget(*, name: str, currency: str, starts_on: date, period: str = BudgetPeriod.MONTHLY) -> Budget:
    return Budget.objects.create(name=name, currency=currency, starts_on=starts_on, period=period)


@transaction.atomic
def add_budget_line(
    *, budget: Budget, category: Category, limit_minor: int, rollover: bool = False
) -> BudgetLine:
    if limit_minor < 0:
        raise BudgetError("Budget limit cannot be negative.")
    if category.kind != CategoryKind.EXPENSE:
        raise BudgetError("Budgets track expense categories.")
    return BudgetLine.objects.create(
        budget=budget, category=category, limit_minor=limit_minor, rollover=rollover
    )


@transaction.atomic
def update_budget_line(
    *, line: BudgetLine, limit_minor: int | None = None, rollover: bool | None = None
) -> BudgetLine:
    """Edit a line's limit and/or rollover flag in place. Category is immutable —
    to move the budget to a different category, remove this line and add another,
    keeping the (budget, category) uniqueness clean."""
    fields: list[str] = []
    if limit_minor is not None:
        if limit_minor < 0:
            raise BudgetError("Budget limit cannot be negative.")
        line.limit_minor = limit_minor
        fields.append("limit_minor")
    if rollover is not None:
        line.rollover = rollover
        fields.append("rollover")
    if fields:
        line.save(update_fields=[*fields, "updated_at"])
    return line


@transaction.atomic
def remove_budget_line(*, line: BudgetLine) -> None:
    """Soft-delete a line. The (budget, category) unique constraint is scoped to
    live rows, so the same category can be budgeted again later."""
    line.delete()


@transaction.atomic
def archive_budget(*, budget: Budget) -> None:
    """Hide a budget from the active list without destroying its history."""
    budget.is_active = False
    budget.save(update_fields=["is_active", "updated_at"])
