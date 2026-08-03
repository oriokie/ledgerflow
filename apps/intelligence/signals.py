"""Intelligence signals — react to new transactions.

When a transaction is first created, run the advisory pipeline: suggest a
category (auto-applying only above the confidence threshold) and evaluate the
user's automation rules. This lives in `intelligence` (which depends on
`finance`), never in `finance` — keeping the dependency arrow pointing the
right way, so the accounting core stays unaware of the AI layer.

Two safeguards matter here:

* **created-only** — we act on `kwargs["created"]`, so the re-save that
  applying a suggestion/automation triggers doesn't re-enter the pipeline.
* **re-entrancy guard** — a thread-local flag hard-stops recursion even if a
  downstream save path is added later. Cheap insurance around a signal that
  itself causes saves.

The whole pipeline is best-effort: a provider or rule error is logged and
swallowed, never allowed to break the user's transaction write. Categorization
is advisory by design; failing to suggest is not a failure to record money.
"""

from __future__ import annotations

import logging
import threading

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant
from apps.finance.models import Transaction

logger = logging.getLogger("ledgerflow.intelligence")

_running = threading.local()


def _pipeline_enabled() -> bool:
    from django.conf import settings

    # default on; a deployment can disable the auto-pipeline via settings
    return getattr(settings, "INTELLIGENCE_AUTO_PIPELINE", True)


@receiver(post_save, sender=Transaction)
def _on_transaction_created(sender, instance: Transaction, created, **kwargs):
    if not created or not _pipeline_enabled():
        return
    # Never auto-categorize a transfer (it has no category by definition) or a
    # transaction that already arrived categorized (e.g. an import that mapped
    # its own category, or a rule-sourced write).
    if instance.transfer_group is not None or instance.category_id is not None:
        return
    if getattr(_running, "active", False):
        return

    tenant_id = instance.tenant_id
    txn_pk = instance.pk
    if tenant_id is None:
        return

    def _run():
        _running.active = True
        try:
            from . import services

            # The creating request's transaction has committed, so its tenant
            # binding (contextvar + DB GUC) has unwound. Re-establish it in a
            # fresh atomic block — same ceremony the recurring tasks use — or
            # the pipeline's RLS-scoped reads would see zero rows.
            with transaction.atomic():
                bind_db_tenant(tenant_id)
                with use_tenant(tenant_id):
                    fresh = Transaction.objects.filter(pk=txn_pk).first()
                    if fresh is None:
                        return
                    try:
                        services.suggest_and_maybe_apply(fresh)
                    except Exception:  # noqa: BLE001 - advisory, must never break the write
                        logger.exception("auto-categorization failed", extra={"txn_id": str(txn_pk)})
                    try:
                        services.run_automation(fresh)
                    except Exception:  # noqa: BLE001
                        logger.exception("automation run failed", extra={"txn_id": str(txn_pk)})
                    try:
                        _maybe_notify_large(fresh)
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "large-transaction notification failed",
                            extra={"txn_id": str(txn_pk)},
                        )
        finally:
            _running.active = False

    # Run after the creating transaction commits: the row is durable and we're
    # not nesting saves inside the original atomic block. Eager-Celery/test
    # mode commits synchronously, so tests observe the effect deterministically
    # via django_capture_on_commit_callbacks.
    transaction.on_commit(_run)


def _maybe_notify_large(txn) -> None:
    """Raise a large-transaction alert to the transaction's creator, if it
    crosses their configured threshold. No-op when no threshold is set (the
    default), so this stays silent unless a user opts in."""
    from apps.notifications import services as notif_services
    from apps.users.models import User

    recipient = None
    if txn.created_by_id is not None:
        recipient = User.objects.filter(id=txn.created_by_id).first()
    if recipient is None:
        return
    notif_services.notify_large_transaction(txn, user=recipient)
