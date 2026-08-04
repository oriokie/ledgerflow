"""Workspace data export (GDPR portability).

Gathers a workspace's financial data into a single JSON-serializable dict. Runs
under the target tenant's context so RLS + scoped managers apply. Read-only.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant


def _rows(qs, fields: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for obj in qs:
        row: dict[str, Any] = {}
        for f in fields:
            val = getattr(obj, f, None)
            row[f] = str(val) if val is not None and not isinstance(val, (int, float, bool, str)) else val
        out.append(row)
    return out


def export_workspace_data(*, tenant) -> dict[str, Any]:
    """Return a portable snapshot of the workspace's data. Import models lazily
    to avoid coupling tenancy to the finance/planning apps at module load."""
    from apps.budgeting.models import Budget
    from apps.finance.models import Bill, Category, FinancialAccount, Payee, Tag, Transaction
    from apps.goals.models import SavingsGoal

    with transaction.atomic(), use_tenant(tenant.id):
        bind_db_tenant(tenant.id)
        data: dict[str, Any] = {
            "workspace": {
                "id": str(tenant.id),
                "name": tenant.name,
                "type": tenant.type,
                "base_currency": tenant.base_currency,
                "default_locale": tenant.default_locale,
                "default_timezone": tenant.default_timezone,
            },
            "accounts": _rows(
                FinancialAccount.objects.all(),
                ["id", "name", "account_type", "currency", "mask", "is_active"],
            ),
            "categories": _rows(Category.objects.all(), ["id", "name", "kind", "path"]),
            "payees": _rows(Payee.objects.all(), ["id", "name"]),
            "tags": _rows(Tag.objects.all(), ["id", "name"]),
            "transactions": _rows(
                Transaction.objects.all(),
                ["id", "amount_minor", "currency", "occurred_at", "memo", "status", "source"],
            ),
            "bills": _rows(
                Bill.objects.all(),
                ["id", "name", "amount_minor", "currency", "due_on", "status"],
            ),
            "budgets": _rows(Budget.objects.all(), ["id", "name", "period", "currency", "starts_on"]),
            "goals": _rows(
                SavingsGoal.objects.all(),
                ["id", "name", "target_minor", "currency", "target_date", "status"],
            ),
        }
    return data
