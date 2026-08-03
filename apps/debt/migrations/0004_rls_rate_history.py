"""Fail-closed RLS for the rate history table and the offset join.

Same pattern as every other tenant-scoped table. The M2M join carries no
`tenant_id` of its own, so it is scoped through its parent profile — without
that, the join table would be the one unguarded path to which accounts offset
which debts.
"""

from __future__ import annotations

from django.db import migrations

RLS_TABLES = ["debt_debtratehistory"]
JOIN_TABLE = "debt_debtprofile_offset_accounts"


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
                SELECT 1 FROM debt_debtprofile p
                WHERE p.id = {JOIN_TABLE}.debtprofile_id
                  AND p.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM debt_debtprofile p
                WHERE p.id = {JOIN_TABLE}.debtprofile_id
                  AND p.tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
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
    dependencies = [("debt", "0003_debtratehistory_debtprofile_annual_fee_minor_and_more")]
    operations = [migrations.RunPython(apply_rls, revert_rls)]
