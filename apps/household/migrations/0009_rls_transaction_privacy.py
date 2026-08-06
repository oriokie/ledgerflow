"""Row-Level Security for the transaction-privacy table.

The usual caveat, and here it is sharper than anywhere else in this app: RLS
keeps one household's privacy marks away from another household's. It does
nothing to keep a partner's mark away from *their* partner — that is the entire
job of `transaction_privacy.py`, in Python, with no database backstop.

The table itself is not secret. Knowing that a transaction was marked private is
different from knowing what it was, and hiding the marks would only produce
unexplained gaps.
"""

from __future__ import annotations

from django.db import migrations

RLS_TABLES = ["household_transactionprivacy"]


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
    dependencies = [("household", "0008_transactionprivacy")]

    operations = [migrations.RunPython(apply_rls, drop_rls)]
