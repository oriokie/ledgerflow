"""Finance signals — keep derived caches correct.

Any write that changes a tenant's financial state (a new/updated transaction, a
recomputed balance) must invalidate that tenant's cached analytics (health
score, recommendations, anomalies). We do this with a single version bump per
tenant, fired on transaction COMMIT so a rolled-back write never invalidates.

Hooking the models here (rather than editing every service) means new write
paths are covered automatically — there's no service you can forget to
annotate.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.common.cache import invalidate_tenant
from apps.ledger.models import AccountBalance

from .models import Transaction


def _invalidate(tenant_id) -> None:
    if tenant_id is None:
        return
    # fire after commit so a rolled-back transaction leaves caches intact
    transaction.on_commit(lambda: invalidate_tenant(tenant_id))


@receiver(post_save, sender=Transaction)
def _on_transaction_saved(sender, instance, **kwargs):
    _invalidate(instance.tenant_id)


@receiver(post_save, sender=AccountBalance)
def _on_balance_saved(sender, instance, **kwargs):
    _invalidate(instance.tenant_id)
