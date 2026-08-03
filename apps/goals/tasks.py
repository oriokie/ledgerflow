"""Daily auto-contribution sweep (Celery beat).

Mirrors the topology of the recurring-transaction and alert dispatchers exactly:
a lightweight beat entrypoint streams active tenants and fans out one isolated
per-tenant task, so a slow or failing tenant can't hold up the rest and each runs
under its own RLS binding.

The underlying service is idempotent per goal per month (see
`run_due_auto_contributions`), so a retry, an overlapping run, or a catch-up
after an outage can never double-fund a goal. That property is what makes it
safe to schedule this daily rather than trying to fire exactly once on each
goal's chosen day.
"""

from __future__ import annotations

import logging
import uuid

from celery import shared_task
from django.db import transaction

from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant
from apps.tenancy.models import Tenant

logger = logging.getLogger("ledgerflow.goals")

DISPATCH_BATCH = 500


@shared_task(name="goals.dispatch_auto_contributions")
def dispatch_auto_contributions() -> int:
    """Beat entrypoint: fan out per-tenant auto-contribution runs, streamed with
    a server-side cursor and bounded batches."""
    batch: list[str] = []
    total = 0
    qs = Tenant.objects.filter(is_active=True).values_list("id", flat=True)
    for tenant_id in qs.iterator(chunk_size=DISPATCH_BATCH):
        batch.append(str(tenant_id))
        total += 1
        if len(batch) >= DISPATCH_BATCH:
            dispatch_auto_contribution_batch.delay(batch)
            batch = []
    if batch:
        dispatch_auto_contribution_batch.delay(batch)
    logger.info("goal-auto-contrib: streamed %d tenants", total)
    return total


@shared_task(name="goals.dispatch_auto_contribution_batch")
def dispatch_auto_contribution_batch(tenant_ids: list[str]) -> int:
    for tenant_id in tenant_ids:
        run_auto_contributions_for_tenant.delay(tenant_id)
    return len(tenant_ids)


@shared_task(
    name="goals.run_auto_contributions_for_tenant",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def run_auto_contributions_for_tenant(self, tenant_id: str) -> int:
    """Posts any auto-contributions due for one workspace.

    `acks_late` plus the service's per-month idempotency means a worker dying
    mid-run is safe: the task is redelivered and already-posted goals are
    skipped rather than funded twice.
    """
    from . import services

    tenant_uuid = uuid.UUID(str(tenant_id))
    try:
        with transaction.atomic():
            bind_db_tenant(tenant_uuid)
            with use_tenant(tenant_uuid):
                posted = services.run_due_auto_contributions()
        if posted:
            logger.info("goal-auto-contrib: tenant %s posted %d contributions", tenant_uuid, posted)
        return posted
    except Exception as exc:  # pragma: no cover - retry path
        logger.exception("goal-auto-contrib: tenant %s failed", tenant_uuid)
        raise self.retry(exc=exc) from exc
