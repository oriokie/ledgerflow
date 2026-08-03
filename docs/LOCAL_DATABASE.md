# Working with the database locally (macOS)

Which of these applies depends on how you started LedgerFlow. If you ran
`deploy/mac-setup.sh --docker` or `docker compose up`, use the **Docker**
column. If you ran it without `--docker`, Postgres is a Homebrew service on the
host — use the **Native** column.

Not sure? `docker compose ps` lists a `db` container if you're on Docker.

---

## Connect to a psql prompt

| | Command |
|---|---|
| **Docker** | `docker compose exec db psql -U ledgerflow -d ledgerflow` |
| **Native** | `psql ledgerflow` |

Useful once you're in:

```sql
\dt                                  -- list tables
\d finance_transaction               -- describe one
SELECT count(*) FROM finance_transaction;
\q                                   -- quit
```

> **Row-level security applies to you too.** Most tables are RLS-protected and
> fail closed, so a plain `SELECT * FROM finance_transaction` returns **zero
> rows** rather than an error — the isolation is on the data, not the
> application. To see a workspace's rows you must bind its tenant first:
>
> ```sql
> SET app.current_tenant = '<tenant-uuid>';
> SELECT count(*) FROM finance_transaction;
> ```
>
> An empty result is almost always this, not missing data. `SHOW
> app.current_tenant;` tells you what is currently bound.

---

## Django shell (respects tenant scoping)

Usually easier than SQL, because the ORM handles RLS binding for you:

```bash
# Docker
docker compose exec web python manage.py shell

# Native
python manage.py shell
```

```python
from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant
from apps.tenancy.models import Membership
from django.db import transaction

m = Membership.objects.first()
with transaction.atomic():
    bind_db_tenant(m.tenant_id)
    with use_tenant(m.tenant_id, actor_id=m.user_id):
        from apps.finance.models import Transaction
        print(Transaction.objects.count())
```

Without both `bind_db_tenant` (the Postgres GUC that RLS reads) and
`use_tenant` (the contextvar the ORM managers read), you get either
`UnscopedAccessError` or a silent zero — the same trap as above, one layer up.

---

## Reset

### Wipe everything and start over

The bluntest option, and usually what you want in a dev environment:

```bash
# Docker — deletes the volume, so the data is genuinely gone
docker compose down -v
docker compose up -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_plans
docker compose exec web python manage.py seed_platform_demo
```

```bash
# Native
dropdb ledgerflow && createdb ledgerflow
python manage.py migrate
python manage.py seed_plans
python manage.py seed_platform_demo
```

`seed_platform_demo` recreates the admin (`admin@ledgerflow.test` /
`PlatformAdmin!2026`) and ten demo workspaces. It refuses to run unless
`DEBUG=True` unless you pass `--i-know-this-is-not-production`.

### Keep the schema, drop the data

Faster than a full reset when migrations haven't changed:

```bash
python manage.py flush --no-input     # truncates every table
python manage.py seed_plans           # flush removes migration-seeded rows too
python manage.py seed_platform_demo
```

> `flush` also removes data written by *data migrations* — the FX rates from
> `fx/0002_seed_rates` in particular. If currency conversion suddenly returns
> nothing after a flush, that is why; re-running `migrate` will not restore
> them because the migration is already recorded as applied. The quickest fix
> is a full reset, or `python manage.py migrate fx 0001 && python manage.py migrate fx`.

### Reset one workspace only

```python
# manage.py shell
from apps.tenancy.models import Tenant
Tenant.objects.filter(name="The Otieno Household").delete()
```

Cascades through that workspace's accounts, transactions and ledger entries.
Other workspaces are untouched.

---

## Reset the test database

The test suite reuses its database between runs (`--reuse-db` in `pytest.ini`),
which is fast but occasionally leaves a stale schema after a migration change:

```bash
pytest --create-db          # rebuild it once
pytest                      # subsequent runs reuse it again
```

If tests fail in ways that make no sense — especially "column does not exist" —
`--create-db` is the first thing to try.

---

## Backups

```bash
# Docker
docker compose exec -T db pg_dump -U ledgerflow ledgerflow > backup-$(date +%F).sql
cat backup-2026-07-29.sql | docker compose exec -T db psql -U ledgerflow -d ledgerflow

# Native
pg_dump ledgerflow > backup-$(date +%F).sql
psql ledgerflow < backup-2026-07-29.sql
```

A restore into a non-empty database will conflict on primary keys. Drop and
recreate first, or restore into a fresh database name.

---

## When something is wrong

**"password authentication failed"** — the credentials in `.env` don't match the
database. On Docker, `docker compose down -v` and up again regenerates both
consistently. On native, check `DATABASE_URL`.

**"could not connect to server"** — Postgres isn't running.
`brew services start postgresql@16`, or `docker compose up -d db`.

**"relation does not exist"** — migrations haven't run: `manage.py migrate`.

**Queries return nothing and you expected rows** — almost certainly RLS. See the
note at the top; bind the tenant.

**Port 5432 already in use** — a Homebrew Postgres and a Docker one are both
running. `brew services stop postgresql@16`, or change the host port in
`docker-compose.yml`.
