"""Row-Level Security for the contribution and audit tables.

Same fail-closed pattern as every other tenant-scoped table, and the same
caveat as `0002`: RLS binds a *tenant*, so it keeps one household's agreements
and activity log away from another household's. It does not partition anything
between two partners who share a tenant — that boundary lives in Python.

For `household_auditevent` there is a second property worth stating. The policy
below permits INSERT and SELECT for the bound tenant, and the model refuses
UPDATE and DELETE in `save()`/`delete()`. Those are two different mechanisms
guarding two different things: the policy stops another household reading the
log, and the model stops *this* household rewriting it. Neither substitutes for
the other, and the application-level half is the one that makes the log worth
trusting.
"""

from __future__ import annotations

from django.db import migrations

RLS_TABLES = [
    "household_contributionagreement",
    "household_contributionterm",
    "household_auditevent",
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
        ("household", "0004_contributionagreement_auditevent_contributionterm"),
    ]

    operations = [migrations.RunPython(apply_rls, drop_rls)]
