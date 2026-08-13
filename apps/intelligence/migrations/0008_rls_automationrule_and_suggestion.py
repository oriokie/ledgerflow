"""Fail-closed RLS for `AutomationRule` and `CategorizationSuggestion`.

Every other tenant-scoped table in this app got RLS in `0003_rls_coach_tables`
(Insight, Briefing) or `0006_rls_automation_tables` (AutomationSuggestion,
MerchantProfile) — these two were missed, and tenant isolation on them has
been ORM-only (`TenantScopedManager`) ever since `0001_initial`. Worth closing
now: `AutomationRule` is becoming load-bearing for the first time with a real
editor UI, rather than sitting unreachable behind dead client code.

Neither model has a join table (both reference `finance.Transaction`/
`finance.Category` by plain FK, not M2M), so this is the simple one-policy-
per-table shape, same as `0003`.
"""

from __future__ import annotations

from django.db import migrations

RLS_TABLES = [
    "intelligence_automationrule",
    "intelligence_categorizationsuggestion",
]


def apply_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    c = schema_editor.connection.cursor()
    for table in RLS_TABLES:
        c.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        c.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        # DROP IF EXISTS first: makes this safe to re-run against a database
        # where the policy was already created (e.g. a retried migration),
        # rather than failing on the second attempt.
        c.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
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
    dependencies = [("intelligence", "0007_alter_insight_kind")]
    operations = [migrations.RunPython(apply_rls, revert_rls)]
