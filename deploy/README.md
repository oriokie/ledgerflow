# Installing & Running LedgerFlow

Three paths, in increasing order of "how permanent is this":

1. [Local on a Mac](#1-local-on-a-mac) — for developing/running on your laptop.
2. [Automated server deploy](#2-automated-server-deploy) — one command turns a
   fresh Debian/Ubuntu **or** RHEL-family (RHEL, Rocky, AlmaLinux, Amazon
   Linux 2023) VM into a running, TLS-terminated production stack.
3. [Manual / managed-infra notes](#3-manual--managed-infrastructure) — for
   Kubernetes/ECS or a managed Postgres/Redis.

LedgerFlow is Docker-first, so every path is fundamentally the same four
processes — **web** (gunicorn), **worker** (Celery), **beat** (Celery
scheduler), plus **Postgres** and **Redis**. Nothing in the app holds state
between requests, so web and worker scale horizontally; only one `beat` should
ever run.

---

## 1. Local on a Mac

### Fastest: Docker Desktop

If you have [Docker Desktop](https://www.docker.com/products/docker-desktop/):

```bash
cd ledgerflow
bash deploy/mac-setup.sh --docker
```

That creates a `.env` (with a real MFA encryption key generated for you) and
runs `docker compose up`. When it finishes:

- API: <http://localhost:8000/api/v1/>
- Interactive API docs: <http://localhost:8000/api/docs/>
- Health check: <http://localhost:8000/healthz/>

```bash
docker compose logs -f                                   # tail logs
docker compose exec web python manage.py createsuperuser # make an admin user
docker compose down                                      # stop everything
```

### Native (venv + Homebrew), for running the code directly

Prefer to run/debug on the host without containers:

```bash
cd ledgerflow
bash deploy/mac-setup.sh          # installs Postgres 16 + Redis via brew,
                                  # creates the DB, a .venv, installs deps,
                                  # writes .env, and runs migrations
```

Then run the three processes in separate terminals (each with the venv active
via `source .venv/bin/activate`):

```bash
make run       # API server on :8000
make worker    # Celery worker
make beat      # Celery beat scheduler
```

Other handy targets: `make test`, `make lint`, `make format`, `make shell`.

### Fully manual (if you'd rather not use the script)

```bash
brew install postgresql@16 redis && brew services start postgresql@16 && brew services start redis
createuser -s app 2>/dev/null; psql postgres -c "ALTER ROLE app PASSWORD 'app';"
createdb -O app ledgerflow

python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements/development.txt

cp .env.example .env
# set FIELD_ENCRYPTION_KEY — generate one with:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# paste the result into .env as FIELD_ENCRYPTION_KEY=...

python manage.py migrate
make run   # + make worker + make beat in other terminals
```

`FIELD_ENCRYPTION_KEY` is the only value you *must* set for auth/MFA to work;
everything else in `.env.example` has a working local default.

---

## 2. Automated server deploy

Two flavours of the same result:

* **`deploy/setup.sh` — interactive (recommended for a person).** Walks
  through every decision with prompts and validation: domain and extra
  hostnames, **web server (Caddy / nginx / Apache / none)**, **database
  (bundled Postgres or an external managed one)**, **file storage (local
  volume or S3-compatible)**, outbound email, payments, then writes `.env`,
  installs what the choices need, issues **Let's Encrypt TLS** (certbot for
  nginx/Apache, automatic for Caddy) and starts the stack.

  ```bash
  sudo bash deploy/setup.sh
  ```

  Re-running keeps your `.env`, secrets and database; `--reconfigure-web`
  switches web server or re-issues TLS without touching the app.

* **`deploy/provision.sh` — non-interactive (for CI or a one-liner).** Same
  stack, no questions, Caddy-fronted: installs Docker, creates a deploy user,
  generates strong secrets, configures a firewall + automatic security
  updates, and brings up web/worker/beat + Postgres + Redis with automatic
  TLS.

With nginx or Apache, the host server terminates TLS and proxies everything to
the stack's loopback-only internal origin (`127.0.0.1:8080`), which serves the
SPA and routes `/api`, `/django-admin` and `/static` to Django — so path
routing lives in one place regardless of which web server fronts it.

### Already hosting other sites on this box?

Pick **`existing`** at the web-server prompt. `setup.sh` checks ports 80/443
before it asks anything, so if cPanel, Plesk or your own nginx already owns
them, Caddy is withdrawn from the menu and `existing` becomes the default —
the app binds nothing public, and you get the exact nginx / Apache /
`.htaccess` snippet to paste into the vhost for your domain.

Nothing that already serves those ports is modified, stopped or reconfigured,
and TLS stays that server's job. On cPanel in particular, do not let this
script write vhosts: the panel owns and regenerates them.

`.htaccess` cannot use `ProxyPreserveHost` (Apache forbids the directive
there), so the internal origin pins the public `Host` header itself. That is
why the proxy works even though the front end rewrites `Host` to
`127.0.0.1:8080`.

### Prerequisites

- A server (any provider: DigitalOcean, Hetzner, EC2, Lightsail…) running
  Ubuntu/Debian **or** the RHEL family (RHEL, Rocky, AlmaLinux, Amazon Linux
  2023) if you're using `setup.sh`. `provision.sh`, the non-interactive path,
  is Ubuntu/Debian only.
- A domain name with an **A record pointing at the server's public IP** (TLS
  issuance needs this to resolve before you run the script).
- Ports 80 and 443 reachable from the internet.

### Steps

```bash
# 1. Get the code onto the server (pick one):
git clone <your-repo-url> ledgerflow      # if it's in a git remote
#   …or from your laptop:  rsync -av --exclude .git ./ledgerflow user@server:~/ledgerflow

# 2. From inside the repo, run the provisioner as root:
cd ledgerflow
sudo DOMAIN=app.yourdomain.com ACME_EMAIL=you@yourdomain.com \
     bash deploy/provision.sh
```

That's it. The script is **idempotent** — re-run it any time (e.g. after
pulling new code) and it rebuilds and restarts the stack without touching your
generated secrets.

What you get, and where:

| Thing | Location |
|---|---|
| App directory | `/opt/ledgerflow` |
| Generated secrets | `/opt/ledgerflow/.env` (chmod 600 — **back this up**) |
| Compose file | `deploy/docker-compose.server.yml` |
| TLS | Automatic via Caddy (`deploy/Caddyfile`) |

### Day-2 operations (from `/opt/ledgerflow`)

```bash
CF=deploy/docker-compose.server.yml
docker compose -f $CF ps                     # service status
docker compose -f $CF logs -f web            # tail web logs
docker compose -f $CF exec web python manage.py createsuperuser
docker compose -f $CF up -d --build          # redeploy after a code change
docker compose -f $CF down                   # stop (data volumes persist)
```

### Knowing when it breaks, and why

Three tools, installed by `setup.sh`/`provision.sh` but each runnable on its own.

```bash
sudo bash deploy/doctor.sh              # what is wrong, right now
sudo bash deploy/firewall-docker.sh     # reconcile the host firewall with Docker
sudo bash deploy/install-monitor.sh     # alert me when the site stops serving
```

**`doctor.sh`** walks the stack bottom-up — host, packet forwarding, containers,
whether the app can actually open a socket to Postgres and Redis, then the public
endpoints. The first failure is nearly always the real one; everything below it
tends to be a consequence. Run it whenever something looks wrong, and after any
firewall change.

**`firewall-docker.sh`** is the preventative half. Every host firewall — CSF, UFW,
firewalld — rebuilds the iptables ruleset on reload, and unless told otherwise it
rebuilds it *without* the chains Docker installed when the daemon started. Docker
never finds out, because it only writes those rules at startup. The containers keep
running and every connection between them times out.

That is not a hypothetical: it took this application down for about six hours on
2026-08-06. The tell is distinctive and misleading — `docker compose ps` shows
Postgres healthy while the app cannot reach it, and restarting the containers
changes nothing, because the containers were never the problem. `systemctl restart
docker` is what actually fixes it, by making the daemon reinstall its rules.

The script detects whichever firewall is present, applies that firewall's idiom for
permitting the container bridge, and then **tests that a container really can reach
the database** rather than trusting the config it just wrote. On CSF it also writes
`/etc/csf/csfpost.sh`, which CSF runs after every rebuild — so the rules come back
even if someone later turns its `DOCKER` option off again.

**`install-monitor.sh`** sets up a systemd timer that probes `/readyz/` every minute
and alerts after three consecutive failures (~3 minutes), with `doctor.sh` output in
the alert body so the cause arrives with the notification. Configure at least one
channel in `.env` first — it refuses to install otherwise, because a monitor with
nobody to tell looks like coverage on the next incident review and isn't:

```bash
ALERT_WEBHOOK_URL=https://hooks.slack.com/services/...   # Slack, Discord, ntfy
# and/or
ALERT_EMAIL_TO=you@example.com
ALERT_SMTP_URL=smtps://smtp.example.com:465
ALERT_SMTP_USER=apikey
ALERT_SMTP_PASSWORD=...
```

Prove it reaches you before trusting it — a webhook URL with a typo is
indistinguishable from "no outages yet":

```bash
sudo bash deploy/install-monitor.sh --test
```

> **This monitor cannot report a dead host.** It runs on the machine it watches, so
> power loss, a network outage or a full disk produce silence rather than an alert —
> and silence is not evidence of health. Pair it with an external check
> (Healthchecks.io, UptimeRobot, BetterStack) pointed at `https://$DOMAIN/readyz/`.
> The on-host monitor tells you *why*; the external one tells you *at all*.

Why `/readyz/` and not `/healthz/`: liveness deliberately checks nothing external, so
that a database outage doesn't make Docker restart every replica at once. It returns a
confident 200 while the app cannot reach Postgres. Readiness touches the database, the
cache and migration state — the things that actually went dark.

### Filling in the optional integrations

The generated `.env` has empty placeholders for SMTP (invitation/notification
email), S3-compatible object storage (attachments), and OAuth. Fill them in,
then `docker compose -f deploy/docker-compose.server.yml up -d` to apply. Until
then, the app runs fine — email falls back to console/none and attachments use
local disk.

### Looking inside the database

LedgerFlow requires **PostgreSQL** — row-level security, the append-only
triggers and JSONB all have no MySQL equivalent — so it does not appear in
cPanel's MySQL database list, and cannot be moved there.

The bundled Postgres publishes on `127.0.0.1:5432`, loopback only. Reach it
with an SSH tunnel rather than opening the port:

```bash
ssh -L 5432:127.0.0.1:5432 you@server     # then connect a client to localhost:5432
```

Database `ledgerflow`, user `ledgerflow`, password in `.env`
(`POSTGRES_PASSWORD`). Or skip the tunnel entirely:

```bash
docker compose -f deploy/docker-compose.server.yml exec db psql -U ledgerflow ledgerflow
```

Answer yes to the pgweb prompt (or add `--profile pgweb`) for a browser UI on
`127.0.0.1:8081`, reached the same way. **pgweb has no login of its own** —
anyone who can reach the port has full SQL access, which is why it is loopback
only and off by default. Never proxy it from a public vhost.

### Verifying tenant isolation (important)

```bash
docker compose -f deploy/docker-compose.server.yml exec web \
  python manage.py verify_tenant_isolation
```

`setup.sh` runs this after every deploy. It matters because PostgreSQL exempts
**superuser and `BYPASSRLS` roles from every row-level security policy** —
silently, with no error or log line. Since row-level security *is* this
product's tenant isolation, a deployment whose `DATABASE_URL` uses a superuser
has no isolation at all while looking completely healthy.

This is easy to hit by accident: the `postgres` image creates `POSTGRES_USER`
as a superuser. If the command reports a problem, it prints the exact SQL to
create an ordinary role and switch to it. Take a backup first — the fix
reassigns object ownership.

### Backups (do set this up)

The `pgdata` Docker volume holds everything. A minimal nightly dump:

```bash
docker compose -f deploy/docker-compose.server.yml exec -T db \
  pg_dump -U ledgerflow ledgerflow | gzip > backup-$(date +%F).sql.gz
```

Put that in a cron job and ship the file off-box (S3, etc.). For anything
serious, prefer a **managed Postgres** with point-in-time recovery — see below.

---

## 3. Manual / managed infrastructure

For production at scale, don't run the database on the app box. Point the app at
managed services and drop the `db`/`redis` services from the compose file:

- Set `DATABASE_URL` to your managed Postgres (RDS, Cloud SQL, Neon, …). The app
  needs a normal Postgres 16+ role; Row-Level Security and the append-only
  triggers are created by migrations, so no special DB setup is required beyond
  the database existing.
- Set `REDIS_URL` (and `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`) to a
  managed Redis (ElastiCache, Memorystore, Redis Cloud).
- Set `DEFAULT_FILE_STORAGE=storages.backends.s3.S3Storage` plus the
  `AWS_*` vars for attachment storage.

Then run the same Docker image under your orchestrator (Kubernetes/ECS/Nomad).
Key points, all already handled by the image:

- **Migrations**: run once per release as a separate job/one-off task, or let
  the container run them via `RUN_MIGRATIONS=true` (the entrypoint applies them
  before serving; Postgres advisory locks make concurrent replicas safe). For
  zero-downtime, prefer the separate-job approach.
- **Static files**: `COLLECT_STATIC=true` runs `collectstatic` on start;
  whitenoise serves them, so no separate static host is required.
- **Health probe**: point your load balancer at `GET /healthz/`.
- **Exactly one `beat`**; scale `web`/`worker` freely.
- **TLS**: terminate at your load balancer. Production settings already trust
  `X-Forwarded-Proto`, so HTTPS detection works behind a proxy.

See [`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) and
[`../docs/CONFIGURATION.md`](../docs/CONFIGURATION.md) for the full topology and
every environment variable.

---

## The frontend (React SPA)

The web UI lives in `frontend/app/` (Vite + React + TypeScript). It's a pure
single-page app that talks to the API — no server-side rendering.

### Local development

```bash
cd frontend/app
cp .env.example .env       # VITE_API_BASE_URL=http://localhost:8000/api/v1
npm install
npm run dev                # http://localhost:5173
```

Run the backend (`make run`, or the Docker stack) alongside it. In development
the backend allows all CORS origins, so the SPA on :5173 talks to the API on
:8000 directly. Log in with a user you've created (`createsuperuser`, or the
in-app **Create account** link).

### Production

The automated server deploy (§2) builds and serves the frontend for you: the
`frontend` service in `deploy/docker-compose.server.yml` compiles the SPA to
static files, and **Caddy serves everything from one origin** — `/api/*` and
`/admin/*` go to Django, everything else is the SPA (with a history-API
fallback so a hard refresh on `/goals` still works). Because it's same-origin,
production needs no CORS.

To ship a new frontend build after changing code:

```bash
docker compose -f deploy/docker-compose.server.yml up -d --build frontend caddy
```

If you host the frontend separately (e.g. on a CDN/static host) instead, build
with your API URL baked in:

```bash
cd frontend/app
VITE_API_BASE_URL=https://api.yourdomain.com/api/v1 npm run build
# deploy the dist/ folder; and add that origin to CORS_ALLOWED_ORIGINS on the API
```

---

## Environment variables you'll actually set

Full reference in [`../docs/CONFIGURATION.md`](../docs/CONFIGURATION.md). The
few that matter most:

| Variable | Why | Local default |
|---|---|---|
| `DJANGO_SECRET_KEY` | Django signing key | dev placeholder (fine locally) |
| `FIELD_ENCRYPTION_KEY` | **Required** — encrypts MFA secrets at rest | must be set (scripts generate one) |
| `DJANGO_ALLOWED_HOSTS` | Your domain(s) in prod | `localhost,127.0.0.1` |
| `DATABASE_URL` | Postgres connection | local Postgres |
| `REDIS_URL` | Cache + Celery broker | local Redis |
| `DOMAIN` / `ACME_EMAIL` | TLS on the server path | n/a |

The provisioning script generates `DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`,
and the Postgres password for you on first run — you never invent secrets by
hand.
