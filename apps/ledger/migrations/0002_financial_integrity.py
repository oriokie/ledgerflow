"""Financial-integrity DDL (PostgreSQL only).

1. Row-Level Security on every tenant-scoped table: even a raw query or a
   compromised code path cannot cross tenants. Policy reads the tenant from a
   per-transaction GUC `app.current_tenant`, bound by
   `apps.common.api_base.TenantScopedAPIView` for the life of the request.
   Fail-closed: unset GUC -> NULL comparison -> zero rows.
2. Append-only triggers on the immutable financial tables: UPDATE/DELETE raise.
   Corrections must be reversing entries.

No-ops on non-Postgres backends so the sqlite/test path still runs.
"""

from __future__ import annotations

from django.db import migrations

RLS_TABLES = [
    "ledger_account",
    "ledger_journalentry",
    "ledger_ledgerline",
    "ledger_accountbalance",
    "finance_financialaccount",
    "finance_wallet",
    "finance_category",
    "finance_payee",
    "finance_tag",
    "finance_transaction",
    "finance_transactiontag",
    "finance_attachment",
    "finance_recurringtransaction",
    "budgeting_budget",
    "budgeting_budgetline",
    "intelligence_categorizationsuggestion",
    "intelligence_automationrule",
]
# common_outboxevent / common_auditlog / tenancy_* are intentionally NOT
# RLS-protected: they are control-plane data written during operations that
# predate a per-request tenant GUC (workspace creation, invitation
# acceptance) and read cross-tenant by trusted background workers. tenant_id
# is still stamped and filtered at the application layer.

IMMUTABLE_TABLES = ["ledger_journalentry", "ledger_ledgerline", "common_auditlog"]


def apply_integrity(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    c = schema_editor.connection.cursor()

    for table in RLS_TABLES:
        c.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        c.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        c.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
        """)

    c.execute("""
        CREATE OR REPLACE FUNCTION ledgerflow_forbid_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Record is append-only; correct via a reversing entry (table %).', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
    """)
    for table in IMMUTABLE_TABLES:
        c.execute(f"""
            CREATE TRIGGER {table}_no_mutation
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION ledgerflow_forbid_mutation();
        """)


def revert_integrity(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    c = schema_editor.connection.cursor()
    for table in IMMUTABLE_TABLES:
        c.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table};")
    c.execute("DROP FUNCTION IF EXISTS ledgerflow_forbid_mutation();")
    for table in RLS_TABLES:
        c.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        c.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        c.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0001_initial"),
        ("finance", "0001_initial"),
        ("budgeting", "0001_initial"),
        ("common", "0001_initial"),
        # `RLS_TABLES` above names two intelligence tables, so they have to
        # exist before this runs. Without this dependency the graph was free to
        # schedule it first and a fresh database failed to build with
        # `relation "intelligence_categorizationsuggestion" does not exist` —
        # it only ever worked because INSTALLED_APPS order happened to break
        # the tie the right way, which is not a guarantee.
        ("intelligence", "0001_initial"),
    ]
    operations = [migrations.RunPython(apply_integrity, revert_integrity)]
