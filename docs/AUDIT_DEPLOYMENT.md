# LedgerFlow — Deployment Readiness

**Method.** Inspected the deployment artefacts, ran `manage.py check --deploy`
against production settings, and exercised the probes. Three gaps were fixed
during the assessment; they are marked below.

**Verdict: deployable to a single server today; not yet operable at scale.**

The distinction matters. Everything needed to *run* the software is present and
several parts are done well. What is thin is everything that tells you it is
running *correctly* — and one gap (no CI) means nothing verifies a release
before it ships.

---

## Summary

| Area | State |
|---|---|
| Error monitoring | **Fixed** — was absent; opt-in Sentry wired |
| Logging | **Strong** — JSON, request-ID correlation, stdout |
| Health checks | **Fixed** — was unfailable; liveness/readiness split |
| Observability | **Gap** — no metrics, no tracing |
| Configuration | **Strong** — env-driven, fails closed at boot |
| Deployment | Good, with **no CI/CD** |
| Backup & recovery | **Gap** — documented, not automated, never tested |
| Documentation | **Strong** for setup, **absent** for incidents |
| Environment config | **Strong** |

---

## 1. Fixed during this assessment

### Health checks were unfailable

The deployment probe was:

```python
def health_check(request):
    return JsonResponse({"status": "ok"})
```

It returned 200 with the database down, Redis unreachable and migrations
unapplied. That is worse than having no probe: an orchestrator reads it as
healthy, keeps routing traffic to an instance that can serve nothing, and never
restarts it.

The irony is that a *rich* health probe already existed — `platform_admin/health.py`
checks database size and connections, cache round-trip, Celery worker liveness
and queue depth, storage, outbox backlog and integration status. It was wired to
the operator console and not to the deployment.

Now split, because the two answer different questions:

* **`/healthz` — liveness.** Checks nothing external, deliberately. If liveness
  depended on the database, an outage would fail it on every replica at once and
  the orchestrator would restart the whole fleet — turning a recoverable blip
  into a thundering-herd restart loop.
* **`/readyz` — readiness.** Database, cache round-trip, and **migrations
  applied**. Failing readiness removes an instance from the load balancer
  without killing it, which is what a rolling deploy needs.

The migration check earns its place: a container that starts before its
migration has run serves 500s on exactly the tables that changed, and nothing
else in the stack notices. Readiness holds it out of rotation until the schema
catches up. It proved itself immediately — the first run returned 503 against a
dev database with two unapplied migrations.

18 tests, each asserting the probe **can fail**. A health check that cannot
fail is not a health check.

### The app container had no health check

`db` and `redis` had them; `web` did not, so Docker would never restart a hung
application container and Caddy had no readiness signal. Added, pointed at
`/readyz` (not `/healthz` — see above), with a `start_period` covering
migrations and `collectstatic` in the entrypoint.

### No error monitoring at all

No Sentry, Rollbar or equivalent. The only record of a production exception was
a line in stdout that nobody is paged about.

Wired opt-in: activates only when `SENTRY_DSN` is set, degrades with a warning
if the package is absent, so a deployment that does not want it is unaffected.
`send_default_pii=False` deliberately — this product handles household financial
data, and a tracker capturing request bodies would accumulate transaction memos,
payee names and amounts in a third-party system that was never part of the
privacy posture.

---

## 2. Remaining gaps, in priority order

### G-1 — No CI/CD (highest)

There is no `.github/workflows`, no `.gitlab-ci.yml`, no pipeline of any kind.
**Nothing runs the 1,572 tests before a release.** The suite's value is entirely
dependent on someone remembering to run it.

This is the largest gap because it multiplies every other one: the contract
test, the property tests, the security suite and `check --deploy` are all
sitting there unexecuted at the moment they matter.

A minimal pipeline is an afternoon: run migrations, run the suite, run
`manage.py check --deploy`, build both images, and refuse the deploy on any
failure. Two specifics this codebase needs:

* **Run the suite twice**, or with `--create-db`. The `--reuse-db` /
  transactional-test interaction documented in the testing audit produces a
  suite that passes once and fails on the second run.
* **Create the database role without `SUPERUSER`.** A superuser bypasses RLS
  entirely, so the entire tenant-isolation suite would pass vacuously. This
  caught me on the first day of this project.

### G-2 — No metrics or tracing

No Prometheus, OpenTelemetry, statsd or APM. There is no time series for request
latency, error rate, queue depth or database connections — so the only way to
learn that p95 has doubled is a customer complaint.

The platform console's health snapshot is a *point-in-time* read, which answers
"is it broken now" and not "when did this start" or "is it getting worse".

The performance work in the testing audit produced the first measured
characteristics (transaction list 6 queries flat; CSV import ~15 queries per
row). Those are laboratory numbers. Nothing measures production.

`django-prometheus` plus the existing `/readyz` checks would cover most of it
cheaply.

### G-3 — Backup is a suggestion, not a system

`deploy/README.md` says *"Backups (do set this up)"* and offers a `pg_dump`
one-liner to put in cron. That is honest, and it is not a backup strategy:

* **Nothing is automated.** A README instruction is not a running job.
* **No restore has been tested.** An untested backup is a hypothesis. The
  failure mode — discovering at 3am that the dumps have been zero bytes for six
  weeks — is common enough to be a cliché.
* **No RPO/RTO stated**, so nobody knows how much data loss is acceptable or how
  long recovery should take.
* **Media is not covered.** Production mandates S3 for attachments, and the dump
  covers Postgres only. Receipt images would survive only if the bucket has its
  own versioning.
* **`FIELD_ENCRYPTION_KEY` is not addressed.** TOTP secrets and stored payment
  credentials are encrypted with it. A database backup restored without that key
  is a backup of unreadable data — this is the single most likely way a restore
  succeeds and still fails.

The README does the right thing by recommending managed Postgres with
point-in-time recovery. That should be the documented default rather than the
"for anything serious" footnote.

### G-4 — No runbooks

`deploy/README.md` and `docs/DEPLOYMENT.md` cover installation, topology,
migrations, the beat schedule and scaling well. Neither covers what to do when
something breaks:

* How to roll back a bad release (no procedure; no image tagging strategy).
* What to do when the dunning sweep or outbox relay backs up.
* How to rotate `SECRET_KEY`, `FIELD_ENCRYPTION_KEY` or provider credentials —
  and specifically that rotating `FIELD_ENCRYPTION_KEY` requires re-encrypting
  every stored secret, which is not a config change.
* Who is paged, and for what.

The platform console's alert categories (`ledger.drift`, `webhook.failed`,
`queue.backlog`, `payment.failed`) are a ready-made list of the incidents worth
writing runbooks for.

### G-5 — Smaller items

* **19 `drf_spectacular` warnings** mean the published OpenAPI schema is
  incomplete for those views — relevant now that a contract test exists and
  generated client types are the next step.
* **Secret-key strength is unvalidated at boot.** The comment in
  `production.py` correctly says `check --deploy` validates it — but with no CI
  (G-1), nothing runs that.
* **Log aggregation is unconfigured.** Writing JSON to stdout is exactly right;
  nothing ships it anywhere.
* **No zero-downtime story.** `entrypoint.sh` runs migrations before gunicorn
  starts, which is fine for a single instance and a race with multiple replicas
  starting together.

---

## 3. What is genuinely production-grade

Not filler — these are the parts that would take weeks to add later:

**Logging** is done properly: JSON formatter forced in production, a
`RequestIDFilter` giving correlation IDs across a request, per-logger levels,
and everything to stdout where a container platform expects it. Most projects
at this stage log unstructured text to a file.

**Configuration** fails closed. `DJANGO_ALLOWED_HOSTS` missing raises at import
— before the process serves a request — rather than defaulting to a wildcard.
`DEBUG = False` is a literal, not a switchable env var. Object storage is
mandatory in production, so nobody accidentally ships attachments to a container
filesystem that vanishes on deploy.

**`manage.py check --deploy` reports zero security warnings.** All 19 findings
are schema-generation warnings. HSTS at one year with preload and subdomains,
SSL redirect, secure cookies, `X_FRAME_OPTIONS = DENY`,
`SECURE_CONTENT_TYPE_NOSNIFF` and the proxy SSL header are all set.

**The topology is correct**: `web`, `worker` and `beat` as separate services,
with beat explicitly documented as exactly-one-per-deployment — the mistake that
otherwise produces duplicate dunning emails.

**Setup documentation is unusually good** — 9.6KB covering Mac local, automated
server provisioning, and managed infrastructure, with the honest note that
"until then, the app runs fine — email falls back to console and attachments use
local disk."

---

## 4. Recommended order

1. **CI pipeline** — tests, `check --deploy`, image build. Nothing else is
   trustworthy without it, and it is an afternoon.
2. **Automated backups with a tested restore**, including the encryption key.
   Write the restore procedure and then actually run it.
3. **Metrics** — `django-prometheus` and a dashboard for latency, error rate and
   queue depth.
4. **Runbooks** for the four alert categories the console already raises.
5. **Log shipping** to an aggregator.
6. Close the `drf_spectacular` warnings, then generate client types from the
   schema — completing the contract-test work.

Items 1 and 2 are what stand between "deployable" and "operable". I would not
put customer financial data on this until both exist.

---

## 5. Not covered

No infrastructure review (TLS configuration in practice, WAF, network
segmentation, database exposure), no disaster-recovery rehearsal, no capacity
planning, and no cost modelling. The `provision.sh` script was read but not
executed against a real server.
