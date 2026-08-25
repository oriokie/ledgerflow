"""Receivables read side."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import Prefetch, Sum
from django.utils import timezone

from .models import Receivable, ReceivableStatus, Repayment


@dataclass(frozen=True, slots=True)
class ReceivableView:
    receivable_id: str
    counterparty: str
    kind: str
    description: str
    currency: str
    principal_minor: int
    repaid_minor: int
    outstanding_minor: int
    lent_on: date
    due_on: date | None
    status: str
    #: Negative when still in the future, positive once late, None when no date
    #: was ever agreed. Null rather than 0 so "no deadline" is never rendered
    #: as "due today".
    days_overdue: int | None
    #: How long the money has been out, whatever was agreed. This is the figure
    #: that actually matters for an informal loan with no due date — it is what
    #: turns "I lent Sam something once" into "that was fourteen months ago".
    days_outstanding: int
    repayment_count: int
    last_received_on: date | None
    source_account_id: str | None


@dataclass(frozen=True, slots=True)
class ReceivableSummary:
    currency: str
    outstanding_minor: int
    overdue_minor: int
    settled_minor: int
    written_off_minor: int
    count: int
    overdue_count: int
    #: Who owes the most, for the one-line headline. None when nothing is owed.
    largest_counterparty: str | None
    largest_minor: int


def receivable_views(*, as_of: date | None = None, include_closed: bool = True) -> list[ReceivableView]:
    """Every claim, biggest outstanding first.

    Repayments are prefetched and summed in Python rather than annotated, so a
    receivable with no repayments costs nothing extra and the aggregate cannot
    be silently multiplied by a join — the classic annotate-two-relations bug.
    """
    as_of = as_of or timezone.localdate()
    qs = Receivable.objects.prefetch_related(
        Prefetch("repayments", queryset=Repayment.objects.order_by("-received_on"))
    )
    if not include_closed:
        qs = qs.filter(status=ReceivableStatus.OUTSTANDING)

    views: list[ReceivableView] = []
    for r in qs:
        repayments = list(r.repayments.all())
        repaid = sum(p.amount_minor for p in repayments)
        outstanding = max(0, r.principal_minor - repaid)
        views.append(
            ReceivableView(
                receivable_id=str(r.id),
                counterparty=r.counterparty,
                kind=r.kind,
                description=r.description,
                currency=r.currency,
                principal_minor=r.principal_minor,
                repaid_minor=repaid,
                outstanding_minor=outstanding,
                lent_on=r.lent_on,
                due_on=r.due_on,
                status=r.status,
                days_overdue=(as_of - r.due_on).days if r.due_on else None,
                days_outstanding=(as_of - r.lent_on).days,
                repayment_count=len(repayments),
                last_received_on=repayments[0].received_on if repayments else None,
                source_account_id=str(r.source_account_id) if r.source_account_id else None,
            )
        )
    views.sort(key=lambda v: v.outstanding_minor, reverse=True)
    return views


def summary(*, as_of: date | None = None) -> ReceivableSummary | None:
    """Headline figures, or None when nothing has ever been recorded.

    None rather than a row of zeroes, for the same reason the income endpoint
    answers 204: "you are owed nothing" and "you have not told us about
    anything" are different statements, and only one of them is a finding.

    Sums across currencies are *not* attempted — the dominant currency wins and
    the rest are excluded, consistent with `net_worth`'s refusal to add
    currencies without FX.
    """
    as_of = as_of or timezone.localdate()
    views = receivable_views(as_of=as_of)
    if not views:
        return None

    counts: dict[str, int] = {}
    for v in views:
        counts[v.currency] = counts.get(v.currency, 0) + 1
    currency = max(counts.items(), key=lambda kv: kv[1])[0]
    scoped = [v for v in views if v.currency == currency]

    live = [v for v in scoped if v.status == ReceivableStatus.OUTSTANDING]
    overdue = [v for v in live if v.days_overdue is not None and v.days_overdue > 0]
    largest = max(live, key=lambda v: v.outstanding_minor, default=None)

    return ReceivableSummary(
        currency=currency,
        outstanding_minor=sum(v.outstanding_minor for v in live),
        overdue_minor=sum(v.outstanding_minor for v in overdue),
        settled_minor=sum(v.principal_minor for v in scoped if v.status == ReceivableStatus.SETTLED),
        written_off_minor=sum(
            v.outstanding_minor for v in scoped if v.status == ReceivableStatus.WRITTEN_OFF
        ),
        count=len(live),
        overdue_count=len(overdue),
        largest_counterparty=largest.counterparty if largest else None,
        largest_minor=largest.outstanding_minor if largest else 0,
    )


def total_outstanding_minor(currency: str) -> int:
    """What is still owed to the household in `currency`.

    Exposed for other modules (net worth overlays, the coach) that want the
    figure without the whole view. Written-off claims are excluded: the point
    of writing one off is that you have stopped counting it.
    """
    rows = Receivable.objects.filter(currency=currency, status=ReceivableStatus.OUTSTANDING)
    principal = rows.aggregate(total=Sum("principal_minor"))["total"] or 0
    repaid = Repayment.objects.filter(receivable__in=rows).aggregate(total=Sum("amount_minor"))["total"] or 0
    return max(0, principal - repaid)
