"""Receivables: money other people owe you.

The product modelled every liability in detail and had no model of the other
direction at all — a household could record that it owed a friend, but not that
a friend owed it. For the informal lending most households actually do, that is
often the largest single thing they are owed and the one most likely to be
forgotten.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from apps.receivables import selectors, services
from apps.receivables.models import Receivable, ReceivableStatus
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db

LENT_ON = date(2026, 1, 10)


def _lend(counterparty="Wanjiru", amount=50_000, **kw):
    kw.setdefault("lent_on", LENT_ON)
    kw.setdefault("currency", "USD")
    return services.create_receivable(counterparty=counterparty, principal_minor=amount, **kw)


# --------------------------------------------------------------------- basics
def test_a_claim_records_who_owes_what():
    with tenant_scope(uuid.uuid4()):
        r = _lend("Wanjiru", 50_000, description="Rent share", due_on=date(2026, 2, 10))
        assert r.status == ReceivableStatus.OUTSTANDING
        assert services.outstanding_minor(r) == 50_000


def test_a_claim_against_nobody_is_refused():
    """A receivable's whole purpose is to be chaseable."""
    with tenant_scope(uuid.uuid4()):
        with pytest.raises(services.ReceivableError):
            _lend(counterparty="   ")


def test_money_cannot_be_owed_back_before_it_went_out():
    with tenant_scope(uuid.uuid4()):
        with pytest.raises(services.ReceivableError):
            _lend(due_on=date(2026, 1, 1))


def test_a_claim_needs_a_positive_amount():
    with tenant_scope(uuid.uuid4()):
        with pytest.raises(services.ReceivableError):
            _lend(amount=0)


# ----------------------------------------------------------------- repayments
def test_part_payments_reduce_what_is_outstanding_without_rewriting_the_original():
    """Principal is never decremented — the outstanding figure is derived.

    Keeping the original amount means the history stays legible: "lent 50,000,
    got 20,000 back" rather than a balance that silently became 30,000 with no
    record of what it was.
    """
    with tenant_scope(uuid.uuid4()):
        r = _lend(amount=50_000)
        services.record_repayment(receivable=r, amount_minor=20_000, received_on=date(2026, 2, 1))

        r.refresh_from_db()
        assert r.principal_minor == 50_000, "the original claim is not rewritten"
        assert services.outstanding_minor(r) == 30_000
        assert r.status == ReceivableStatus.OUTSTANDING


def test_a_claim_settles_itself_when_the_last_payment_lands():
    """Status is derived, never set by hand — one that can disagree with the
    sums beneath it is a status nobody can trust."""
    with tenant_scope(uuid.uuid4()):
        r = _lend(amount=50_000)
        services.record_repayment(receivable=r, amount_minor=20_000, received_on=date(2026, 2, 1))
        services.record_repayment(receivable=r, amount_minor=30_000, received_on=date(2026, 3, 1))

        r.refresh_from_db()
        assert r.status == ReceivableStatus.SETTLED
        assert services.outstanding_minor(r) == 0


def test_an_overpayment_never_reads_as_the_household_owing_money_back():
    """Someone rounds up, or pays twice. Outstanding floors at zero rather than
    going negative, which would read as a debt in the other direction."""
    with tenant_scope(uuid.uuid4()):
        r = _lend(amount=50_000)
        services.record_repayment(receivable=r, amount_minor=60_000, received_on=date(2026, 2, 1))
        assert services.outstanding_minor(r) == 0
        r.refresh_from_db()
        assert r.status == ReceivableStatus.SETTLED


def test_money_cannot_come_back_before_it_went_out():
    with tenant_scope(uuid.uuid4()):
        r = _lend()
        with pytest.raises(services.ReceivableError):
            services.record_repayment(receivable=r, amount_minor=1_000, received_on=date(2025, 12, 1))


# ----------------------------------------------------------------- write-offs
def test_writing_off_keeps_the_record():
    """That a loan was never repaid is worth remembering — for the user, and
    for anyone deciding whether to lend to that person again."""
    with tenant_scope(uuid.uuid4()):
        r = _lend(amount=50_000)
        services.write_off(receivable=r)

        r.refresh_from_db()
        assert r.status == ReceivableStatus.WRITTEN_OFF
        assert Receivable.objects.filter(id=r.id).exists(), "written off is not deleted"


def test_a_written_off_debt_that_gets_paid_comes_back_to_life():
    """People do sometimes pay debts you'd given up on, and refusing the entry
    would leave the user unable to record money genuinely in their hand."""
    with tenant_scope(uuid.uuid4()):
        r = _lend(amount=50_000)
        services.write_off(receivable=r)
        services.record_repayment(receivable=r, amount_minor=20_000, received_on=date(2026, 6, 1))

        r.refresh_from_db()
        assert r.status == ReceivableStatus.OUTSTANDING
        assert services.outstanding_minor(r) == 30_000


def test_there_is_nothing_to_write_off_on_a_settled_claim():
    with tenant_scope(uuid.uuid4()):
        r = _lend(amount=50_000)
        services.record_repayment(receivable=r, amount_minor=50_000, received_on=date(2026, 2, 1))
        with pytest.raises(services.ReceivableError):
            services.write_off(receivable=r)


# --------------------------------------------------------------------- views
def test_a_claim_with_no_due_date_is_never_reported_as_overdue():
    """Most informal loans have no date attached. Inventing one would
    manufacture an overdue warning nobody agreed to — but how long the money
    has been out is still reported, because that is the figure that matters."""
    with tenant_scope(uuid.uuid4()):
        _lend(amount=50_000, due_on=None)
        (view,) = selectors.receivable_views(as_of=date(2026, 6, 10))

    assert view.days_overdue is None
    assert view.days_outstanding == 151


def test_overdue_is_counted_from_the_agreed_date():
    with tenant_scope(uuid.uuid4()):
        _lend(amount=50_000, due_on=date(2026, 2, 10))
        (view,) = selectors.receivable_views(as_of=date(2026, 3, 10))

    assert view.days_overdue == 28


def test_summary_is_absent_rather_than_zeroed_when_nothing_is_recorded():
    """"You are owed nothing" and "you haven't told us about anything" are
    different statements, and only one of them is a finding."""
    with tenant_scope(uuid.uuid4()):
        assert selectors.summary() is None


def test_summary_separates_outstanding_overdue_and_written_off():
    with tenant_scope(uuid.uuid4()):
        _lend("Wanjiru", 50_000, due_on=date(2026, 2, 10))  # overdue by as_of
        _lend("Otieno", 30_000, due_on=date(2026, 12, 1))  # not yet due
        settled = _lend("Achieng", 10_000)
        services.record_repayment(
            receivable=settled, amount_minor=10_000, received_on=date(2026, 2, 1)
        )
        lost = _lend("Kamau", 5_000)
        services.write_off(receivable=lost)

        result = selectors.summary(as_of=date(2026, 3, 10))

    assert result.currency == "USD"
    assert result.outstanding_minor == 80_000, "settled and written-off are not outstanding"
    assert result.overdue_minor == 50_000
    assert result.settled_minor == 10_000
    assert result.written_off_minor == 5_000
    assert result.count == 2
    assert result.overdue_count == 1
    assert result.largest_counterparty == "Wanjiru"


def test_total_outstanding_excludes_what_was_given_up_on():
    with tenant_scope(uuid.uuid4()):
        _lend("Wanjiru", 50_000)
        lost = _lend("Kamau", 5_000)
        services.write_off(receivable=lost)

        assert selectors.total_outstanding_minor("USD") == 50_000


# ------------------------------------------------------------------- editing
def test_a_claim_can_be_corrected():
    with tenant_scope(uuid.uuid4()):
        r = _lend("Wanjuru", 50_000)
        services.update_receivable(receivable=r, counterparty="Wanjiru", principal_minor=45_000)

        r.refresh_from_db()
        assert r.counterparty == "Wanjiru"
        assert r.principal_minor == 45_000


def test_correcting_the_principal_downward_can_settle_a_claim():
    """Status follows the sums wherever they move, not only when money lands."""
    with tenant_scope(uuid.uuid4()):
        r = _lend(amount=50_000)
        services.record_repayment(receivable=r, amount_minor=20_000, received_on=date(2026, 2, 1))
        # It was 20,000 all along, not 50,000.
        services.update_receivable(receivable=r, principal_minor=20_000)

        r.refresh_from_db()
        assert r.status == ReceivableStatus.SETTLED


def test_the_currency_cannot_be_changed():
    """Every repayment already recorded is denominated in it — changing it
    would reinterpret history rather than correct it."""
    with tenant_scope(uuid.uuid4()):
        r = _lend()
        with pytest.raises(services.ReceivableError):
            services.update_receivable(receivable=r, currency="KES")


# ------------------------------------------------------------------ isolation
def test_receivables_are_tenant_isolated():
    """These rows name third parties who are not users of this product,
    alongside what they owe and how long they've failed to pay it."""
    a, b = uuid.uuid4(), uuid.uuid4()
    with tenant_scope(a):
        _lend("Wanjiru", 50_000)
        assert Receivable.objects.count() == 1
    with tenant_scope(b):
        assert Receivable.objects.count() == 0
        assert selectors.summary() is None


# ------------------------------------------------------------------ API surface
def test_the_api_round_trips_a_claim_and_its_repayments(tenant_context):
    _, client = tenant_context

    created = client.post(
        "/api/v1/receivables/",
        {
            "counterparty": "Wanjiru",
            "kind": "personal",
            "description": "Rent share",
            "currency": "USD",
            "principal_minor": 50_000,
            "lent_on": "2026-01-10",
            "due_on": "2026-02-10",
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    rid = created.data["id"]
    assert created.data["outstanding_minor"] == 50_000

    paid = client.post(
        f"/api/v1/receivables/{rid}/repayments/",
        {"amount_minor": 20_000, "received_on": "2026-02-01"},
        format="json",
    )
    assert paid.status_code == 201, paid.data
    assert paid.data["outstanding_minor"] == 30_000
    assert paid.data["status"] == "outstanding"

    detail = client.get(f"/api/v1/receivables/{rid}/")
    assert detail.status_code == 200
    assert len(detail.data["repayments"]) == 1

    summary = client.get("/api/v1/receivables/summary/")
    assert summary.status_code == 200
    assert summary.data["outstanding_minor"] == 30_000

    assert client.delete(f"/api/v1/receivables/{rid}/").status_code == 204
    assert client.get("/api/v1/receivables/").data == []


def test_the_summary_is_204_when_nothing_has_been_recorded(tenant_context):
    _, client = tenant_context
    assert client.get("/api/v1/receivables/summary/").status_code == 204
