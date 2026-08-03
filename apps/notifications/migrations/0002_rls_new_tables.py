"""Row-Level Security for the tables added alongside the notifications app.

Follows the exact pattern established in
`ledger/migrations/0002_financial_integrity.py`: enable + FORCE row-level
security and install a fail-closed tenant-isolation policy (an unbound
`app.current_tenant` GUC yields NULL, and `tenant_id = NULL` is never true, so
an unbound connection sees zero rows rather than everything).

Kept as its own migration (rather than editing 0002) because these tables are
created by later migrations across three apps; this one depends on all of them
so every table exists before RLS is applied.
"""

from __future__ import annotations

from django.db import migrations

NEW_RLS_TABLES = [
    "goals_savingsgoal",
    "goals_goalcontribution",
    "notifications_notification",
    "notifications_notificationpreference",
    "finance_bill",
]


def apply_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    c = schema_editor.connection.cursor()
    for table in NEW_RLS_TABLES:
        c.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        c.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        c.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
            """
        )


def revert_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    c = schema_editor.connection.cursor()
    for table in NEW_RLS_TABLES:
        c.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        c.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        c.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0001_initial"),
        ("goals", "0001_initial"),
        ("finance", "0002_transaction_split_group_bill"),
    ]
    operations = [migrations.RunPython(apply_rls, revert_rls)]
