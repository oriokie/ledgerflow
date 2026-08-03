"""Regression: setup actions must produce visible feedback.

Both the investments and debt planners gated their entire body on a derived
summary that stays null until there is *transactional* activity. A user who
followed the empty state's own instructions — add a security, add a credit
card — saw the identical empty state afterwards, because neither action creates
a holding or a balance on its own. Nothing acknowledged what they had just
done, which reads as a broken page.

These tests lock down the data the pages need to tell "you have nothing" apart
from "you have set things up but not used them yet".
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from django.db import transaction

from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant
from apps.debt import selectors as debt_selectors
from apps.finance.models import AccountType
from apps.investments.models import Security
from tests.conftest import _bearer_client
from tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


def _client():
    membership = MembershipFactory()
    return membership, _bearer_client(membership.user, tenant_id=membership.tenant_id)


@contextmanager
def _tenant(membership):
    """Bind a tenant the way the API layer does, for calling selectors directly.

    Both halves are needed: `bind_db_tenant` sets the Postgres GUC that RLS
    reads, and `use_tenant` sets the contextvar the ORM managers read. Binding
    only one produces either an `UnscopedAccessError` or a silent zero rows.
    """
    with transaction.atomic():
        bind_db_tenant(membership.tenant_id)
        with use_tenant(membership.tenant_id, actor_id=membership.user_id):
            yield


# ----------------------------------------------------------------- investments
def test_a_created_security_is_listed_even_with_no_holdings():
    """The exact reported symptom: 'already tracked' but nothing on the page."""
    _, client = _client()
    created = client.post(
        "/api/v1/investments/securities/",
        {"symbol": "BONDKEDDD", "name": "Kenya Bond", "asset_class": "bond", "currency": "KES"},
        format="json",
    )
    assert created.status_code == 201

    listed = client.get("/api/v1/investments/securities/")
    assert listed.status_code == 200
    assert [s["symbol"] for s in listed.data] == ["BONDKEDDD"]

    # And the portfolio is legitimately empty — which is why the page must not
    # gate the securities list behind it.
    assert client.get("/api/v1/investments/portfolio/").status_code == 204


def test_the_duplicate_message_matches_what_is_listed():
    """If the check says it exists, the list must show it. Any divergence is
    the bug the user actually experienced."""
    _, client = _client()
    payload = {"symbol": "bondkeddd", "name": "Kenya Bond", "asset_class": "bond", "currency": "KES"}
    client.post("/api/v1/investments/securities/", payload, format="json")

    again = client.post("/api/v1/investments/securities/", payload, format="json")
    assert again.status_code == 422
    assert "already tracked" in again.data["detail"]

    symbols = {s["symbol"] for s in client.get("/api/v1/investments/securities/").data}
    assert "BONDKEDDD" in symbols


def test_a_soft_deleted_security_is_neither_listed_nor_blocks_recreation():
    """The two must agree in both directions."""
    membership, client = _client()
    payload = {"symbol": "VTI", "name": "Total Market", "asset_class": "etf", "currency": "USD"}
    client.post("/api/v1/investments/securities/", payload, format="json")

    with _tenant(membership):
        Security.objects.get(symbol="VTI").delete()

    assert client.get("/api/v1/investments/securities/").data == []
    assert client.post("/api/v1/investments/securities/", payload, format="json").status_code == 201


# ------------------------------------------------------------------------ debt
def _liability(client, name="Visa", balance_minor=0):
    """Create a credit card, optionally with an opening balance."""
    body = {
        "name": name,
        "account_type": AccountType.CREDIT_CARD,
        "currency": "USD",
    }
    if balance_minor:
        body["opening_balance_minor"] = balance_minor
    response = client.post("/api/v1/finance/accounts/", body, format="json")
    assert response.status_code in (200, 201), response.data
    return response.data


def test_a_zero_balance_card_is_tracked_even_though_nothing_is_owed():
    """The reported debt symptom: add the card the page told you to add, and
    the page still says 'No debt tracked'."""
    _, client = _client()
    _liability(client, name="Visa")

    # Nothing is owed, so the planner correctly has no summary...
    assert client.get("/api/v1/debt/debts/summary/").status_code == 204
    assert client.get("/api/v1/debt/debts/").data == []

    # ...but the account exists, and the page must be able to say so.
    tracked = client.get("/api/v1/debt/debts/tracked/")
    assert tracked.status_code == 200
    assert [row["name"] for row in tracked.data] == ["Visa"]
    assert tracked.data[0]["balance_minor"] == 0
    assert tracked.data[0]["has_terms"] is False


def test_tracked_is_an_empty_list_when_there_are_genuinely_no_accounts():
    """'Two cards, both at zero' and 'no cards' must be distinguishable."""
    _, client = _client()
    response = client.get("/api/v1/debt/debts/tracked/")
    assert response.status_code == 200
    assert response.data == []


def test_tracked_liabilities_never_feed_planning_arithmetic():
    """A paid-off card must not appear in the payoff plan or inflate counts."""
    membership, client = _client()
    _liability(client, name="Paid off card")

    with _tenant(membership):
        assert debt_selectors.debt_views() == []
        assert debt_selectors.debt_summary() is None
        assert len(debt_selectors.tracked_liabilities()) == 1


def test_tracked_reports_terms_once_they_are_entered():
    _, client = _client()
    account = _liability(client, name="Visa")

    response = client.put(
        f"/api/v1/debt/debts/{account['id']}/terms/",
        {"apr": "19.99", "minimum_payment_minor": 2500},
        format="json",
    )
    assert response.status_code in (200, 201), response.data

    row = client.get("/api/v1/debt/debts/tracked/").data[0]
    assert row["has_terms"] is True
    assert row["apr"] == pytest.approx(19.99)
    assert row["minimum_payment_minor"] == 2500


def test_a_card_with_a_balance_appears_in_both_views():
    _, client = _client()
    _liability(client, name="Visa", balance_minor=50_000)

    assert client.get("/api/v1/debt/debts/summary/").status_code == 200
    tracked = client.get("/api/v1/debt/debts/tracked/").data
    assert tracked[0]["balance_minor"] == 50_000


def test_tracked_excludes_non_liability_accounts():
    _, client = _client()
    client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": AccountType.CHECKING, "currency": "USD"},
        format="json",
    )
    assert client.get("/api/v1/debt/debts/tracked/").data == []


def test_tracked_liabilities_query_count_is_fixed(django_assert_num_queries):
    """The page loads this on every visit; it must not grow with account count."""
    membership, client = _client()
    for index in range(4):
        _liability(client, name=f"Card {index}")

    # Fixed cost regardless of how many accounts exist: the accounts query
    # plus its three prefetches.
    with _tenant(membership), django_assert_num_queries(5):
        debt_selectors.tracked_liabilities()
