"""Make the platform audit log append-only at the database level.

The tenant audit log (`common_auditlog`) is already protected this way. The
platform log needs it more, not less: it is the record of what employees did
to customers, and the people with the most motive to edit it are exactly the
people with production database access. An application-layer "we never issue
UPDATEs" convention is not a control — a trigger is.

Reuses `ledgerflow_forbid_mutation()`, created by
`apps/ledger/migrations/0002_financial_integrity.py`, rather than defining a
second identical function. `CREATE OR REPLACE` is used defensively so this
migration is independent of apply order.

No-op on non-Postgres backends, matching the existing integrity migrations.
"""

from __future__ import annotations

from django.db import migrations

TABLE = "platform_admin_platformauditlog"


def apply_immutability(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    c = schema_editor.connection.cursor()
    c.execute("""
        CREATE OR REPLACE FUNCTION ledgerflow_forbid_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Record is append-only; correct via a reversing entry (table %).', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
    """)
    c.execute(f"""
        CREATE TRIGGER {TABLE}_no_mutation
        BEFORE UPDATE OR DELETE ON {TABLE}
        FOR EACH ROW EXECUTE FUNCTION ledgerflow_forbid_mutation();
    """)


def revert_immutability(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    c = schema_editor.connection.cursor()
    c.execute(f"DROP TRIGGER IF EXISTS {TABLE}_no_mutation ON {TABLE};")


class Migration(migrations.Migration):
    dependencies = [
        ("platform_admin", "0001_initial"),
        ("ledger", "0002_financial_integrity"),
    ]

    operations = [migrations.RunPython(apply_immutability, revert_immutability)]
