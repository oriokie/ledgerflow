"""Budgeting context — read-heavy, built on top of transactions/categories.
Actual-vs-budget is computed by aggregating Transactions per category per
period; nothing here mutates the ledger."""

from __future__ import annotations

from django.db import models

from apps.common.models import SoftDeletableModel
from apps.finance.models import Category


class BudgetPeriod(models.TextChoices):
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    YEARLY = "yearly", "Yearly"


class Budget(SoftDeletableModel):
    name = models.CharField(max_length=120)
    period = models.CharField(max_length=10, choices=BudgetPeriod.choices, default=BudgetPeriod.MONTHLY)
    currency = models.CharField(max_length=3)
    starts_on = models.DateField()
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "is_active"])]


class BudgetLine(SoftDeletableModel):
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="lines")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="budget_lines")
    limit_minor = models.BigIntegerField()
    rollover = models.BooleanField(default=False)  # carry unspent to next period

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["budget", "category"],
                name="uniq_budget_category",
                condition=models.Q(deleted_at__isnull=True),
            ),
            models.CheckConstraint(condition=models.Q(limit_minor__gte=0), name="budget_limit_nonneg"),
        ]
