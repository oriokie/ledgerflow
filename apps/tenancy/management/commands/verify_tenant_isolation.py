"""Prove — against the live database — that tenant isolation is switched on.

Row-level security is the whole of this product's multi-tenancy. Every other
guard (the scoped managers, `use_tenant`, the API permissions) is defence in
depth on top of it, and all of them are in application code that a single
missing `.filter()` can sidestep. RLS is the layer that holds when the code is
wrong, so a deployment where it is silently inert has no tenant isolation at
all, only the appearance of it.

It really is silent. PostgreSQL exempts superusers and `BYPASSRLS` roles from
every policy without a warning, an error, or a log line — queries simply return
other tenants' rows. The official `postgres` Docker image creates
`POSTGRES_USER` as a superuser, so the obvious way to stand this stack up
produces exactly that: a working-looking deployment with no isolation. This
command exists because that failure has no symptom you would ever notice from
the outside.

Run after every deploy (`setup.sh` does) and any time the database credentials
change:

    python manage.py verify_tenant_isolation

Exit status is 0 only when isolation is genuinely enforced.
"""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.common.rls import bind_db_tenant


class Command(BaseCommand):
    help = "Verify that PostgreSQL row-level security is actually enforcing tenant isolation."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError(
                f"Database vendor is {connection.vendor!r}, not PostgreSQL. Tenant "
                "isolation depends on row-level security and cannot be enforced here."
            )

        self._check_connecting_role()
        self._check_policies_exist()
        self._prove_isolation_empirically()
        self.stdout.write(self.style.SUCCESS("Tenant isolation is enforced."))

    # -- 1. the role ---------------------------------------------------------
    def _check_connecting_role(self):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT current_user, rolsuper, rolbypassrls " "FROM pg_roles WHERE rolname = current_user"
            )
            role, is_superuser, bypasses_rls = cur.fetchone()

        if is_superuser or bypasses_rls:
            reason = "a SUPERUSER" if is_superuser else "granted BYPASSRLS"
            raise CommandError(
                f"The application connects to PostgreSQL as {role!r}, which is {reason}.\n"
                "PostgreSQL exempts such roles from every row-level security policy, so\n"
                "tenant isolation is NOT being enforced — one workspace can read another's\n"
                "data. This is the default when DATABASE_URL uses the same role the\n"
                "postgres image created from POSTGRES_USER.\n\n"
                "Fix it by pointing DATABASE_URL at an ordinary role. On the bundled\n"
                "database, as the superuser:\n\n"
                "    CREATE ROLE ledgerflow_app LOGIN PASSWORD '<a new strong password>'\n"
                "      NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;\n"
                "    GRANT ALL ON SCHEMA public TO ledgerflow_app;\n"
                "    GRANT ALL ON ALL TABLES IN SCHEMA public TO ledgerflow_app;\n"
                "    GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO ledgerflow_app;\n"
                "    REASSIGN OWNED BY ledgerflow TO ledgerflow_app;\n\n"
                "then set DATABASE_URL to that role and restart web/worker/beat.\n"
                "Take a backup first — REASSIGN OWNED rewrites object ownership."
            )
        self.stdout.write(f"  role {role!r} is subject to RLS")

    # -- 2. the policies -----------------------------------------------------
    def _check_policies_exist(self):
        """Every table carrying a `tenant_isolation` policy must have RLS both
        enabled and FORCEd.

        Scoped to tables that already have the policy rather than to every
        table with a `tenant_id` column, because the two sets differ by design:
        memberships and invitations are read before any tenant is bound (that
        is how a user finds their workspaces at all), and the billing and
        platform_admin tables are read across tenants by the operator console.
        Demanding RLS there would assert a product decision this command has no
        business making. What it can insist on is that nothing which *was*
        protected has quietly lost it — FORCE especially, since without it the
        owning role is exempt and migrations make the app role the owner.
        """
        with connection.cursor() as cur:
            cur.execute("""
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                  AND EXISTS (SELECT 1 FROM pg_policy p
                              WHERE p.polrelid = c.oid
                                AND p.polname = 'tenant_isolation')
                """)
            tables = cur.fetchall()

        if not tables:
            raise CommandError(
                "No table carries a `tenant_isolation` policy. Either `migrate` has not "
                "run, or the RLS migrations were reversed — there is no isolation here."
            )

        unprotected = [name for name, enabled, forced in tables if not (enabled and forced)]
        if unprotected:
            raise CommandError(
                "These tables have a tenant_isolation policy that is not being applied "
                "(RLS disabled, or enabled without FORCE):\n  "
                + "\n  ".join(sorted(unprotected))
                + "\n\nRe-run `python manage.py migrate`; the RLS migrations set both."
            )
        self.stdout.write(f"  {len(tables)} tables have tenant isolation enabled and forced")

    # -- 3. the behaviour ----------------------------------------------------
    def _prove_isolation_empirically(self):
        """Configuration can be right and still be bypassed. Ask the database
        directly: bound to tenant A, are tenant B's rows visible?

        Read-only and rolled back, so it is safe against a live database.
        """
        # Probe a table that actually carries the policy. `tenancy_tenant` is
        # deliberately not one of them — it is the registry of tenants, keyed by
        # `id`, and is read to resolve a tenant in the first place.
        with connection.cursor() as cur:
            cur.execute("""
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_policy p ON p.polrelid = c.oid
                WHERE n.nspname = 'public' AND p.polname = 'tenant_isolation'
                ORDER BY c.relname
                """)
            protected = [row[0] for row in cur.fetchall()]

        # Needs at least one row somewhere, or "zero visible" proves nothing:
        # an empty table looks identical to a perfectly filtered one.
        probe = None
        for table in protected:
            with connection.cursor() as cur:
                cur.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 - name from pg_class
                if cur.fetchone()[0]:
                    probe = table
                    break

        if probe is None:
            self.stdout.write(
                "  (every tenant table is empty — a read-back would pass vacuously, "
                "so it was skipped; re-run once there is data)"
            )
            return

        stranger = uuid.uuid4()  # a tenant that certainly owns nothing
        with transaction.atomic():
            bind_db_tenant(stranger)
            with connection.cursor() as cur:
                cur.execute(f"SELECT count(*) FROM {probe}")  # noqa: S608 - name from pg_class
                (visible,) = cur.fetchone()
            transaction.set_rollback(True)

        if visible:
            raise CommandError(
                f"Bound to a tenant that owns nothing, {visible} row(s) of {probe} were "
                "still visible.\nRow-level security is not filtering. Do not put real "
                "customer data in this deployment until this is resolved."
            )
        self.stdout.write(f"  a foreign tenant binding sees zero rows of {probe}")
