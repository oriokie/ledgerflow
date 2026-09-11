"""One real-world obligation, one cash-flow event.

A household often records the same rent twice: as a Bill (the due date they
want a reminder for) and as a RecurringTransaction (the standing payment that
actually posts). Counting both invents an overdraft. Income already avoids
this with ``IncomeSource.recurring_transaction``; this module is the expense
side of the same identity.
"""

from __future__ import annotations

from django.db import transaction

from .models import Bill, BillStatus, RecurringTransaction, RecurringType

LIVE_BILL = (BillStatus.UPCOMING, BillStatus.OVERDUE)


def unlinked_bills():
    """Bills whose cash movement is not already posted by a template.

    Soonest-due first so auto-link attaches the live reminder, not a later
    duplicate that happens to share the amount.
    """
    return Bill.objects.filter(status__in=LIVE_BILL, recurring_transaction__isnull=True).order_by(
        "due_on", "id"
    )


def live_bills_for_cash():
    """Alias kept for call sites that read as 'what still moves cash'."""
    return unlinked_bills()


@transaction.atomic
def link_matching_commitments() -> int:
    """Attach an unlinked bill to the expense template that already posts it.

    Match is exact: same currency, same amount, and either the same payee or
    the same name. Fuzzy matching would silently swallow two genuine
    obligations that happen to cost the same. Idempotent — a re-run only
    links what is still free.

    Returns how many bills were newly linked.
    """
    claimed = set(
        Bill.objects.filter(recurring_transaction_id__isnull=False).values_list(
            "recurring_transaction_id", flat=True
        )
    )
    by_payee: dict[tuple, RecurringTransaction] = {}
    by_name: dict[tuple, RecurringTransaction] = {}
    for template in RecurringTransaction.objects.filter(is_active=True, txn_type=RecurringType.EXPENSE):
        if template.id in claimed:
            continue
        ccy = template.currency.upper()
        if template.payee_id:
            by_payee[(ccy, template.amount_minor, template.payee_id)] = template
        name = (template.memo or "").strip().lower()
        if name:
            by_name[(ccy, template.amount_minor, name)] = template

    linked = 0
    for bill in unlinked_bills().select_related("payee"):
        ccy = bill.currency.upper()
        rec = None
        if bill.payee_id:
            rec = by_payee.get((ccy, bill.amount_minor, bill.payee_id))
        if rec is None:
            rec = by_name.get((ccy, bill.amount_minor, bill.name.strip().lower()))
        if rec is None:
            continue
        bill.recurring_transaction = rec
        bill.save(update_fields=["recurring_transaction", "updated_at"])
        claimed.add(rec.id)
        by_payee = {k: v for k, v in by_payee.items() if v.id != rec.id}
        by_name = {k: v for k, v in by_name.items() if v.id != rec.id}
        linked += 1
    return linked
