"""Fail-closed RLS for the automation tables.

Same pattern as every other tenant-scoped table. The suggestion↔transaction
join carries no `tenant_id` of its own and is scoped through its parent
suggestion — without that it would be the one unguarded path to which
transactions a workspace has been asked about.

Merchant profiles are the learning store: they describe where a household
shops and how they think about it.
"""

from __future__ import annotations

from django.db import migrations

RLS_TABLES = [
    "intelligence_automationsuggestion",
    "intelligence_merchantprofile",
]

JOIN_TABLE = "intelligence_automationsuggestion_transactions"


def apply_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    c = schema_editor.connection.cursor()
    for table in RLS_TABLES:
        c.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        c.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        c.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
            """
        )

    c.execute(f"ALTER TABLE {JOIN_TABLE} ENABLE ROW LEVEL SECURITY;")
    c.execute(f"ALTER TABLE {JOIN_TABLE} FORCE ROW LEVEL SECURITY;")
    c.execute(
        f"""
        CREATE POLICY tenant_isolation ON {JOIN_TABLE}
        USING (
            EXISTS (
                SELECT 1 FROM intelligence_automationsuggestion s
                WHERE s.id = {JOIN_TABLE}.automationsuggestion_id
                  AND s.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM intelligence_automationsuggestion s
                WHERE s.id = {JOIN_TABLE}.automationsuggestion_id
                  AND s.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
            )
        );
        """
    )


def revert_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    c = schema_editor.connection.cursor()
    for table in [*RLS_TABLES, JOIN_TABLE]:
        c.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        c.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        c.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")


class Migration(migrations.Migration):
    dependencies = [("intelligence", "0005_merchantprofile_automationsuggestion")]
    operations = [migrations.RunPython(apply_rls, revert_rls)]
