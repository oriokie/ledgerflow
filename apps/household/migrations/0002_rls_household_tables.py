"""Row-Level Security for the household tables.

The same fail-closed pattern as every other tenant-scoped table. Worth being
explicit about what this does and does not protect, because this app is the one
place the two boundaries meet:

RLS protects the **tenant** boundary — one household cannot read another's
sharing policies, dependants or approval history. It does *not* protect the
**member** boundary, because a policy binds a tenant and two partners share
one. Everything keeping a private account away from a partner lives in
`visibility.py`, in Python, and has no database backstop. That is stated here
so nobody reads these policies and concludes the harder half is handled.
"""

from __future__ import annotations

from django.db import migrations

RLS_TABLES = [
    "household_householdprofile",
    "household_dependant",
    "household_accountsharing",
    "household_changerequest",
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
    dependencies = [("household", "0001_initial")]
    operations = [migrations.RunPython(apply_rls, revert_rls)]
