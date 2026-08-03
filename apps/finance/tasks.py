"""Recurring-transaction scheduler (Celery beat).

Topology (P1 fix): a lightweight **dispatcher** runs daily and fans out one
task per active tenant onto the queue, so N workers materialize tenants in
parallel and a single slow or failing tenant is isolated to its own task with
its own retry — instead of one worker walking every tenant serially inside one
beat tick (which would not finish within the day at scale, and would let one
slow tenant delay all others).

Because `RecurringTransaction` is RLS-protected, each per-tenant task binds that
tenant's GUC + contextvar exactly like a request would, in its own transaction,
so one tenant's failure can't roll back another's postings.

At very large tenant counts, the dispatcher's "distinct active tenants" scan can
be narrowed to "tenants with a due template today" via a dedicated BYPASSRLS
reader role — noted as a further scale follow-up.
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

from .recurring import materialize_due

logger = logging.getLogger("ledgerflow.recurring")

DISPATCH_BATCH = 500  # tenants per sub-dispatch task


@shared_task(name="finance.dispatch_recurring_transactions")
def dispatch_recurring_transactions() -> int:
    """Beat entrypoint: fan out recurring materialization across all active
    tenants without loading every id into memory or enqueuing millions of
    tasks from one tick.

    Strategy: stream active tenant ids with a server-side cursor
    (`.iterator()`, bounded memory) and hand off fixed-size batches to
    `dispatch_recurring_batch`, which enqueues the per-tenant tasks. This keeps
    the beat task O(1) in memory and spreads enqueue load across workers.

    A per-tenant task whose tenant has no due templates is cheap (one indexed
    count via `recurring_due_idx` returning nothing), so dispatching all active
    tenants is acceptable; narrowing to only-tenants-with-due-work needs a
    cross-tenant (BYPASSRLS) reader and is the documented next-tier optimization
    if the empty-task volume ever matters.
    """
    batch: list[str] = []
    batches = 0
    total = 0
    qs = Tenant.objects.filter(is_active=True).values_list("id", flat=True)
    for tenant_id in qs.iterator(chunk_size=DISPATCH_BATCH):
        batch.append(str(tenant_id))
        total += 1
        if len(batch) >= DISPATCH_BATCH:
            dispatch_recurring_batch.delay(batch)
            batches += 1
            batch = []
    if batch:
        dispatch_recurring_batch.delay(batch)
        batches += 1
    logger.info("recurring: streamed %d tenants into %d dispatch batches", total, batches)
    return total


@shared_task(name="finance.dispatch_recurring_batch")
def dispatch_recurring_batch(tenant_ids: list[str]) -> int:
    """Enqueue one per-tenant materialization task for a batch of tenants.
    Splitting dispatch into batches means no single task enqueues an unbounded
    number of children."""
    for tenant_id in tenant_ids:
        run_recurring_for_tenant.delay(tenant_id)
    return len(tenant_ids)


@shared_task(
    name="finance.run_recurring_for_tenant",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def run_recurring_for_tenant(self, tenant_id: str) -> int:
    """Materialize one tenant's due templates. Isolated per tenant: a failure
    retries this tenant only and never touches another's run. Idempotent —
    `materialize_due` keys each posting as recurring:{id}:{date}, so a retry
    after partial success re-posts nothing."""
    # Celery serializes the UUID to a string over the wire; coerce back so the
    # tenant-context identity check in TenantOwnedModel.save() (UUID == UUID)
    # holds. Passing the raw string would make every save fail the guard.
    tenant_uuid = uuid.UUID(str(tenant_id))
    today = timezone.localdate()
    try:
        with transaction.atomic():
            bind_db_tenant(tenant_uuid)
            with use_tenant(tenant_uuid):
                created = materialize_due(today=today)
        logger.info("recurring: tenant %s created %d transactions", tenant_uuid, created)
        return created
    except Exception as exc:
        logger.exception("recurring materialization failed for tenant %s", tenant_id)
        raise self.retry(exc=exc) from exc


# Backwards-compatible alias: the old single-task entrypoint now delegates to
# the dispatcher so any existing schedule/reference keeps working.
@shared_task(name="finance.run_recurring_transactions")
def run_recurring_transactions() -> int:
    return dispatch_recurring_transactions()


@shared_task(name="finance.reconcile_account_balances")
def reconcile_account_balances() -> int:
    """Drift guard (P2): the materialized AccountBalance is a cache of the
    immutable ledger; caches drift. Periodically recompute each account's
    balance from the ledger lines and alert on any mismatch. Fans out per
    tenant like the recurring dispatcher. Returns tenants dispatched."""
    tenant_ids = list(Tenant.objects.filter(is_active=True).values_list("id", flat=True))
    for tenant_id in tenant_ids:
        reconcile_balances_for_tenant.delay(str(tenant_id))
    return len(tenant_ids)


@shared_task(name="finance.reconcile_balances_for_tenant")
def reconcile_balances_for_tenant(tenant_id: str) -> int:
    """Recompute one tenant's balances from the ledger and log drift. Returns
    the number of accounts that had drifted (0 = healthy)."""
    from apps.finance.models import FinancialAccount
    from apps.finance.selectors import account_current_balance_minor
    from apps.finance.services import recompute_account_balance

    tenant_uuid = uuid.UUID(str(tenant_id))
    drifted = 0
    with transaction.atomic():
        bind_db_tenant(tenant_uuid)
        with use_tenant(tenant_uuid):
            for account in FinancialAccount.objects.select_related("ledger_account").all():
                before = account_current_balance_minor(account)
                after = recompute_account_balance(financial_account=account)
                if before != after:
                    drifted += 1
                    logger.error(
                        "balance drift corrected: tenant=%s account=%s materialized=%s ledger=%s",
                        tenant_id,
                        account.id,
                        before,
                        after,
                    )
                    # A log line only helps someone already watching the log.
                    # Divergence between a customer's materialized balance and
                    # the immutable ledger is exactly what the operator console
                    # exists to put in front of a human.
                    from apps.platform_admin.notifications import raise_platform_alert

                    raise_platform_alert(
                        category="ledger.drift",
                        severity="critical",
                        title="Account balance drifted from the ledger",
                        body=(
                            f"Materialized {before} vs ledger {after}; corrected. "
                            "A write path bypassed the posting service."
                        ),
                        tenant_id=tenant_uuid,
                        subject_type="finance.FinancialAccount",
                        subject_id=account.id,
                        dedupe_key=f"ledger.drift:{account.id}:{after}",
                    )
    return drifted
