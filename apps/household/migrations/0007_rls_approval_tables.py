"""Row-Level Security for the approval tables.

Same fail-closed pattern as the rest. The caveat from `0002` applies unchanged:
these policies keep one household's approval history away from another's, and
do nothing to partition anything between two partners who share a tenant.

For approvals that second boundary is intentionally absent. An approval is a
conversation between the members of one household about their shared money —
there is nobody inside the tenant it should be hidden from, and a rule never
reaches a private account in the first place (see `approvals.matching_rule`).
"""

from __future__ import annotations

from django.db import migrations

RLS_TABLES = [
    "household_approvalrule",
    "household_spendapproval",
    "household_approvalcomment",
]


def apply_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    cursor = schema_editor.connection.cursor()
    for table in RLS_TABLES:
        cursor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        cursor.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        cursor.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
            """
        )


def drop_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    cursor = schema_editor.connection.cursor()
    for table in RLS_TABLES:
        cursor.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        cursor.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        cursor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")


class Migration(migrations.Migration):
    dependencies = [
        ("household", "0006_approvalrule_spendapproval_approvalcomment_and_more"),
    ]

    operations = [migrations.RunPython(apply_rls, drop_rls)]
