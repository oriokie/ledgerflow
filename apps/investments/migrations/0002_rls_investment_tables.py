"""Row-Level Security for the investment tables.

Same fail-closed pattern as the rest of the product: enable **and force** RLS,
then scope every row to the bound tenant. An unbound `app.current_tenant` GUC
yields NULL, and `tenant_id = NULL` is never true, so a connection with no
tenant sees zero rows rather than everyone's holdings.

Holdings are among the most sensitive rows in the system — they describe what a
household owns and what it is worth — so this is not optional hardening.
"""

from __future__ import annotations

from django.db import migrations

RLS_TABLES = [
    "investments_security",
    "investments_holding",
    "investments_lot",
    "investments_investmenttransaction",
    "investments_pricequote",
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
    dependencies = [("investments", "0001_initial")]
    operations = [migrations.RunPython(apply_rls, revert_rls)]
