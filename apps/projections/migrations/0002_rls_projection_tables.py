"""Row-Level Security for scenarios, their events and assumption sets.

Same fail-closed pattern as every other tenant-scoped table: enable and force
RLS, then scope rows to the bound tenant. An unbound `app.current_tenant` GUC
yields NULL, and `tenant_id = NULL` is never true, so a connection with no
tenant bound sees nothing rather than everything.

Scenarios earn this as much as any table in the product and arguably more than
most. A ledger row records what happened; a scenario records what someone is
*considering* — leaving a job, separating, whether they can afford to care for
a parent. Leaking one across a tenant boundary would disclose intent, which
people guard more closely than balances.
"""

from __future__ import annotations

from django.db import migrations

RLS_TABLES = [
    "projections_assumptionset",
    "projections_scenario",
    "projections_scenarioevent",
]


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


def revert_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    c = schema_editor.connection.cursor()
    for table in RLS_TABLES:
        c.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        c.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        c.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")


class Migration(migrations.Migration):
    dependencies = [("projections", "0001_initial")]
    operations = [migrations.RunPython(apply_rls, revert_rls)]
