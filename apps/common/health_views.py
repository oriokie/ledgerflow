"""Liveness and readiness endpoints.

The deployment health check was `JsonResponse({"status": "ok"})` — a function
that cannot fail. It returned 200 with the database down, Redis unreachable and
migrations unapplied, which is worse than having no health check at all: an
orchestrator reads it as healthy and keeps routing traffic to an instance that
can serve nothing, and never restarts it.

Liveness and readiness are deliberately separate, because they answer different
questions and the wrong answer to either is costly:

* **`/healthz` — liveness.** "Is this process alive?" Checks nothing external.
  A dependency outage must not make every container look dead: if the database
  goes down and liveness fails, the orchestrator restarts every replica at once
  and turns a recoverable outage into a thundering-herd restart loop.

* **`/readyz` — readiness.** "Can this instance serve a request?" Checks the
  database, the cache, and that migrations are applied. Failing readiness pulls
  the instance out of the load balancer *without* killing it, which is exactly
  right during a rolling deploy or a brief dependency blip.

Neither endpoint is authenticated — an orchestrator has no credentials — so
neither reveals anything an attacker could use: no versions, no hostnames, no
connection strings. Just names and booleans.
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse

logger = logging.getLogger("ledgerflow.health")


def liveness(request):
    """Is the process running? Deliberately checks nothing else."""
    return JsonResponse({"status": "alive"})


def readiness(request):
    """Can this instance serve traffic?

    Returns 503 with a per-check breakdown when it cannot, so an operator
    reading the probe output learns *which* dependency is down rather than
    having to go and find out.
    """
    checks: dict[str, bool] = {}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = True
    except Exception:  # noqa: BLE001 — a probe must report, never raise
        logger.exception("readiness: database unreachable")
        checks["database"] = False

    try:
        cache.set("ledgerflow:readyz", "1", 5)
        # A cache that accepts writes and returns nothing is a live failure
        # mode, not a hypothetical: it silently halves throughput while
        # looking perfectly healthy to a connection test.
        checks["cache"] = cache.get("ledgerflow:readyz") == "1"
    except Exception:  # noqa: BLE001
        logger.exception("readiness: cache unreachable")
        checks["cache"] = False

    checks["migrations"] = _migrations_applied()

    ready = all(checks.values())
    return JsonResponse(
        {"status": "ready" if ready else "not ready", "checks": checks},
        status=200 if ready else 503,
    )


def _migrations_applied() -> bool:
    """Whether the schema matches the code.

    Included because the failure it catches is quiet and expensive: a container
    that starts before its migration has run serves 500s on exactly the tables
    that changed, and nothing else in the stack notices. Readiness failing here
    holds the new version out of the load balancer until the schema catches up.
    """
    try:
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        return not executor.migration_plan(targets)
    except Exception:  # noqa: BLE001
        logger.exception("readiness: could not determine migration state")
        return False
