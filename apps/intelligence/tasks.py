"""Scheduled coach runs (Celery beat).

Follows the topology of the recurring-transaction and alert dispatchers: a
lightweight beat entrypoint streams active tenants and fans out one isolated
per-tenant task, so a slow or failing tenant can't hold up the rest and each
runs under its own RLS binding.

Insight generation is idempotent per condition (see `Insight.dedupe_key`), so a
daily sweep refreshes existing rows rather than piling up duplicates, and a
retry after a worker crash is safe. That property is what makes scheduling this
sensible at all — without it, a nightly run would be actively harmful.

The expiry purge runs in the same task rather than on its own schedule: an
insight that has just expired should not survive until a separate job happens to
run, or the feed shows stale advice for up to a day.
"""

from __future__ import annotations

import logging
import uuid

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant
from apps.tenancy.models import Tenant

logger = logging.getLogger("ledgerflow.intelligence")

DISPATCH_BATCH = 500


@shared_task(name="intelligence.dispatch_coach_run")
def dispatch_coach_run() -> int:
    """Beat entrypoint: fan out the daily coach run across active tenants."""
    batch: list[str] = []
    total = 0
    qs = Tenant.objects.filter(is_active=True).values_list("id", flat=True)
    for tenant_id in qs.iterator(chunk_size=DISPATCH_BATCH):
        batch.append(str(tenant_id))
        total += 1
        if len(batch) >= DISPATCH_BATCH:
            dispatch_coach_batch.delay(batch)
            batch = []
    if batch:
        dispatch_coach_batch.delay(batch)
    logger.info("coach-run: streamed %d tenants", total)
    return total


@shared_task(name="intelligence.dispatch_coach_batch")
def dispatch_coach_batch(tenant_ids: list[str]) -> int:
    for tenant_id in tenant_ids:
        run_coach_for_tenant.delay(tenant_id)
    return len(tenant_ids)


@shared_task(
    name="intelligence.run_coach_for_tenant",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    acks_late=True,
)
def run_coach_for_tenant(self, tenant_id: str) -> int:
    """Regenerates insights and the daily briefing for one workspace.

    Weekly and monthly briefings are produced on their own boundaries rather
    than every day: rewriting "this month in review" each morning would mean
    the user never sees a stable monthly summary, and the period_start key
    would churn.
    """
    from . import coach

    tenant_uuid = uuid.UUID(str(tenant_id))
    today = timezone.localdate()

    try:
        with transaction.atomic():
            bind_db_tenant(tenant_uuid)
            with use_tenant(tenant_uuid):
                coach.purge_expired_insights(as_of=today)
                insights = coach.generate_insights(as_of=today)
                coach.generate_briefing(period="daily", as_of=today)

                # Monday starts a new week; the 1st starts a new month.
                if today.weekday() == 0:
                    coach.generate_briefing(period="weekly", as_of=today)
                if today.day == 1:
                    coach.generate_briefing(period="monthly", as_of=today)

        count = len(insights)
        if count:
            logger.info("coach-run: tenant %s has %d live insights", tenant_uuid, count)
        return count
    except Exception as exc:  # pragma: no cover - retry path
        logger.exception("coach-run: tenant %s failed", tenant_uuid)
        raise self.retry(exc=exc) from exc
