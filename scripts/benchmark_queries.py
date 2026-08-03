#!/usr/bin/env python
"""Query benchmark for LedgerFlow hot read paths.

Seeds a realistic dataset in a rolled-back transaction and reports query count
+ wall time for each hot selector, so a regression (an accidental N+1, a lost
index) shows up as a number, not a vibe.

Run: DEBUG=True python scripts/benchmark_queries.py   (DEBUG needed for query capture)
"""

import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from django.db import connection, reset_queries  # noqa: E402
from django.db import transaction as dbtx  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402

from apps.common.rls import bind_db_tenant  # noqa: E402
from apps.common.tenant_context import use_tenant  # noqa: E402
from apps.finance import selectors as sel  # noqa: E402
from apps.finance import services as fs  # noqa: E402
from apps.finance.models import AccountType, CategoryKind  # noqa: E402
from apps.finance.payees import create_payee  # noqa: E402

N = int(os.environ.get("BENCH_N", "500"))


def profile(label, fn):
    reset_queries()
    with CaptureQueriesContext(connection) as ctx:
        t0 = time.perf_counter()
        result = fn()
        if hasattr(result, "__iter__") and not isinstance(result, (dict, list)):
            list(result)
        dt = (time.perf_counter() - t0) * 1000
    flag = "  <-- N+1?" if len(ctx.captured_queries) > 3 else ""
    print(f"{label:44s} queries={len(ctx.captured_queries):4d}  {dt:7.1f}ms{flag}")


def main():
    tenant = uuid.uuid4()
    with dbtx.atomic():
        bind_db_tenant(tenant)
        with use_tenant(tenant):
            checking = fs.create_financial_account(
                name="Checking", account_type=AccountType.CHECKING, currency="USD"
            )
            cats = [
                fs.create_category(name=f"Cat{i}", kind=CategoryKind.EXPENSE, currency="USD")
                for i in range(8)
            ]
            payees = [create_payee(name=f"Merchant {i}") for i in range(20)]
            base = datetime.now(UTC) - timedelta(days=N)
            for i in range(N):
                fs.record_expense(
                    financial_account=checking,
                    category=cats[i % 8],
                    amount_minor=100 + i,
                    occurred_at=base + timedelta(hours=i * 4),
                    payee=payees[i % 20],
                )
            now = datetime.now(UTC)
            print(f"\nDataset: {N} transactions\n" + "=" * 66)
            profile("list_transactions (unpaginated)", lambda: sel.list_transactions())
            profile("net_worth", lambda: sel.net_worth())
            profile("cash_flow (month)", lambda: sel.cash_flow(start=now - timedelta(days=30), end=now))
            profile(
                "category_breakdown (month)",
                lambda: sel.category_breakdown(start=now - timedelta(days=30), end=now),
            )
            profile("account_current_balance_minor", lambda: sel.account_current_balance_minor(checking))
            profile(
                "account_statement",
                lambda: sel.account_statement(
                    financial_account=checking, start=now - timedelta(days=N * 2), end=now
                ),
            )
            dbtx.set_rollback(True)


if __name__ == "__main__":
    main()
