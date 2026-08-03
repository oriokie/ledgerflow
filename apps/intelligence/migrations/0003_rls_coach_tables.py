"""Row-Level Security for the coach's tables.

Follows the pattern established in `ledger/migrations/0002_financial_integrity.py`:
enable **and force** row-level security, then install a fail-closed tenant
isolation policy. An unbound `app.current_tenant` GUC yields NULL, and
`tenant_id = NULL` is never true, so a connection with no tenant bound sees zero
rows rather than every tenant's.

Insights are among the most sensitive rows in the product — they describe a
household's spending in plain language — so this is not optional hardening.

The M2M join table gets the same treatment. It carries no `tenant_id` of its
own, so it is protected by an EXISTS check against the parent briefing; without
that, the join table would be the one unguarded path to the data.
"""

from __future__ import annotations

from django.db import migrations

NEW_RLS_TABLES = [
    "intelligence_insight",
    "intelligence_briefing",
]

JOIN_TABLE = "intelligence_briefing_insights"


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

    # The join table has no tenant_id column; scope it through its briefing.
    c.execute(f"ALTER TABLE {JOIN_TABLE} ENABLE ROW LEVEL SECURITY;")
    c.execute(f"ALTER TABLE {JOIN_TABLE} FORCE ROW LEVEL SECURITY;")
    c.execute(
        f"""
        CREATE POLICY tenant_isolation ON {JOIN_TABLE}
        USING (
            EXISTS (
                SELECT 1 FROM intelligence_briefing b
                WHERE b.id = {JOIN_TABLE}.briefing_id
                  AND b.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM intelligence_briefing b
                WHERE b.id = {JOIN_TABLE}.briefing_id
                  AND b.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
            )
        );
        """
    )


def revert_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    c = schema_editor.connection.cursor()
    for table in [*NEW_RLS_TABLES, JOIN_TABLE]:
        c.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        c.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        c.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")


class Migration(migrations.Migration):
    dependencies = [
        ("intelligence", "0002_insight_and_briefing"),
    ]
    operations = [migrations.RunPython(apply_rls, revert_rls)]
