"""Income HTTP surface, including the isolation that makes it safe to have.

Income is the most sensitive table in the product: a debt balance says what a
household owes, a salary says what it is worth, who employs it and what is
withheld from it. The cross-tenant test at the bottom is the one that matters
most in this file.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db

BASE = "/api/v1/income"
TODAY = date(2026, 6, 15)


def _client(membership) -> APIClient:
    client = APIClient()
    token = RefreshToken.for_user(membership.user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(membership.tenant_id))
    return client


def _payload(**overrides) -> dict:
    return {
        "name": "Salary",
        "kind": "employment",
        "currency": "USD",
        "net_minor": 300_000,
        "frequency": "monthly",
        "starts_on": "2025-01-01",
        **overrides,
    }


def test_create_and_list_a_source(tenant_context):
    _membership, client = tenant_context
    created = client.post(f"{BASE}/sources/", _payload(), format="json")
    assert created.status_code == 201, created.data
    assert created.data["reliability"] == "fixed"
    assert created.data["monthly_net_minor"] == 300_000

    listed = client.get(f"{BASE}/sources/")
    assert listed.status_code == 200
    assert [s["name"] for s in listed.data] == ["Salary"]


def test_net_above_gross_is_rejected_with_a_readable_message(tenant_context):
    _membership, client = tenant_context
    response = client.post(
        f"{BASE}/sources/", _payload(net_minor=400_000, gross_minor=300_000), format="json"
    )
    assert response.status_code == 422
    assert "Net cannot exceed gross" in response.data["detail"]


def test_summary_is_204_before_any_income_is_recorded(tenant_context):
    """Not a body full of zeros.

    Zeros would assert the household earns nothing. The absence is the truth:
    they have not told us yet, and the UI must ask rather than claim.
    """
    _membership, client = tenant_context
    assert client.get(f"{BASE}/summary/").status_code == 204


def test_summary_reports_committed_income(tenant_context):
    _membership, client = tenant_context
    client.post(f"{BASE}/sources/", _payload(net_minor=400_000), format="json")

    response = client.get(f"{BASE}/summary/")
    assert response.status_code == 200
    assert response.data["monthly_net_minor"] == 400_000
    assert response.data["committed"] is not None
    assert response.data["committed"]["free_minor"] == 400_000
    assert response.data["committed"]["committed_pct"] == 0.0


def test_percentage_deduction_without_gross_is_refused(tenant_context):
    _membership, client = tenant_context
    source = client.post(f"{BASE}/sources/", _payload(), format="json").data
    response = client.post(
        f"{BASE}/sources/{source['id']}/deductions/",
        {"kind": "tax", "percent_bp": 2000},
        format="json",
    )
    assert response.status_code == 422
    assert "percentage" in response.data["detail"]


def test_deduction_and_receipt_round_trip(tenant_context):
    _membership, client = tenant_context
    source = client.post(
        f"{BASE}/sources/", _payload(net_minor=240_000, gross_minor=300_000), format="json"
    ).data

    deduction = client.post(
        f"{BASE}/sources/{source['id']}/deductions/",
        {"kind": "tax", "percent_bp": 2000},
        format="json",
    )
    assert deduction.status_code == 201

    receipt = client.post(
        f"{BASE}/sources/{source['id']}/receipts/",
        {"occurred_on": str(TODAY), "net_minor": 245_000, "post_to_ledger": False},
        format="json",
    )
    assert receipt.status_code == 201

    detail = client.get(f"{BASE}/sources/{source['id']}/")
    assert detail.status_code == 200
    assert len(detail.data["deductions"]) == 1
    assert len(detail.data["receipts"]) == 1
    assert detail.data["deductions_minor"] == 60_000

    removed = client.delete(f"{BASE}/sources/{source['id']}/deductions/{deduction.data['id']}/")
    assert removed.status_code == 204
    assert client.get(f"{BASE}/sources/{source['id']}/").data["deductions"] == []


def test_a_deduction_belonging_to_another_source_is_not_deletable(tenant_context):
    """The URL nests deduction under source; the query must honour both ids."""
    _membership, client = tenant_context
    first = client.post(f"{BASE}/sources/", _payload(gross_minor=400_000), format="json").data
    second = client.post(f"{BASE}/sources/", _payload(name="Second", gross_minor=400_000), format="json").data
    deduction = client.post(
        f"{BASE}/sources/{first['id']}/deductions/",
        {"kind": "tax", "amount_minor": 1000},
        format="json",
    ).data

    response = client.delete(f"{BASE}/sources/{second['id']}/deductions/{deduction['id']}/")
    assert response.status_code == 404


def test_patch_cannot_change_currency(tenant_context):
    _membership, client = tenant_context
    source = client.post(f"{BASE}/sources/", _payload(), format="json").data
    response = client.patch(
        f"{BASE}/sources/{source['id']}/", {"currency": "EUR", "name": "Renamed"}, format="json"
    )
    assert response.status_code == 200
    assert response.data["currency"] == "USD"
    assert response.data["name"] == "Renamed"


def test_speculative_flag_travels_with_the_figure(tenant_context):
    """How certain a number is has to be in the payload.

    If the client has to re-derive it, some screen eventually renders a guess
    as a fact.
    """
    _membership, client = tenant_context
    response = client.post(
        f"{BASE}/sources/", _payload(kind="self_employment", name="Freelance"), format="json"
    )
    assert response.status_code == 201
    assert response.data["reliability"] == "irregular"
    assert response.data["is_speculative"] is True
    assert response.data["expected_is_observed"] is False


def test_income_is_not_visible_across_tenants():
    """The test that justifies the RLS migration.

    Two households, two workspaces, one endpoint. Neither may see the other's
    salary — not through the list, and not through a direct id.
    """
    theirs = MembershipFactory()
    mine = MembershipFactory()
    their_client, my_client = _client(theirs), _client(mine)

    created = their_client.post(f"{BASE}/sources/", _payload(name="Their salary"), format="json")
    assert created.status_code == 201
    source_id = created.data["id"]

    assert my_client.get(f"{BASE}/sources/").data == []
    assert my_client.get(f"{BASE}/sources/{source_id}/").status_code == 404
    assert my_client.patch(f"{BASE}/sources/{source_id}/", {"name": "x"}, format="json").status_code == 404
    assert my_client.delete(f"{BASE}/sources/{source_id}/").status_code == 404
    assert my_client.get(f"{BASE}/summary/").status_code == 204

    # ...and the owner still sees it, so the test cannot pass by breaking reads.
    assert their_client.get(f"{BASE}/sources/{source_id}/").status_code == 200


def test_anonymous_access_is_rejected():
    response = APIClient().get(f"{BASE}/sources/")
    assert response.status_code in (401, 403)


def test_a_viewer_may_read_but_not_write(tenant_context):
    """Method-aware authorization: reading income is a viewer right, editing it
    is not."""
    from apps.tenancy.models import Role

    membership, _client_ = tenant_context
    membership.role = Role.VIEWER
    membership.save(update_fields=["role"])
    client = _client(membership)

    assert client.get(f"{BASE}/sources/").status_code == 200
    assert client.post(f"{BASE}/sources/", _payload(), format="json").status_code == 403


def test_ad_hoc_source_is_counted_but_has_no_monthly_figure(tenant_context):
    _membership, client = tenant_context
    response = client.post(
        f"{BASE}/sources/",
        _payload(name="Gigs", kind="self_employment", frequency="ad_hoc"),
        format="json",
    )
    assert response.status_code == 201
    assert response.data["monthly_net_minor"] is None

    summary = client.get(f"{BASE}/summary/")
    # No income has a knowable cadence, so there is no monthly total to give —
    # but the source is still counted so the UI can explain the gap.
    assert summary.status_code == 200
    assert summary.data["monthly_net_minor"] == 0
    assert summary.data["ad_hoc_count"] == 1


def test_receipts_move_the_expected_figure_for_variable_income(tenant_context):
    _membership, client = tenant_context
    source = client.post(
        f"{BASE}/sources/",
        _payload(name="Retainer", kind="business", net_minor=100_000),
        format="json",
    ).data
    assert source["reliability"] == "variable"

    for n, amount in enumerate((200_000, 220_000, 240_000), start=1):
        client.post(
            f"{BASE}/sources/{source['id']}/receipts/",
            {
                "occurred_on": str(date.today() - timedelta(days=30 * n)),
                "net_minor": amount,
                "post_to_ledger": False,
            },
            format="json",
        )

    refreshed = client.get(f"{BASE}/sources/{source['id']}/").data
    assert refreshed["expected_is_observed"] is True
    assert refreshed["expected_net_minor"] == 220_000
    assert refreshed["variance_pct"] == pytest.approx(9.1, abs=0.1)


def test_recording_a_receipt_posts_to_transactions(tenant_context):
    """Income recorded on /income must appear on the Transactions page."""
    from apps.finance import services as finance_services
    from apps.finance.models import AccountType, Transaction
    from tests.utils import tenant_scope

    membership, client = tenant_context
    with tenant_scope(membership.tenant_id):
        account = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )

    source = client.post(
        f"{BASE}/sources/",
        _payload(deposit_account_id=str(account.id), pay_day=15),
        format="json",
    ).data
    assert source["deposit_account_id"] == str(account.id)

    receipt = client.post(
        f"{BASE}/sources/{source['id']}/receipts/",
        {
            "occurred_on": str(TODAY),
            "net_minor": 300_000,
            "deposit_account_id": str(account.id),
        },
        format="json",
    )
    assert receipt.status_code == 201, receipt.data
    assert receipt.data["transaction_id"]

    with tenant_scope(membership.tenant_id):
        txn = Transaction.objects.get(id=receipt.data["transaction_id"])
        assert txn.amount_minor == 300_000
        assert txn.financial_account_id == account.id


def test_receipt_without_account_explains_what_to_fix(tenant_context):
    _membership, client = tenant_context
    source = client.post(f"{BASE}/sources/", _payload(), format="json").data
    response = client.post(
        f"{BASE}/sources/{source['id']}/receipts/",
        {"occurred_on": str(TODAY), "net_minor": 300_000},
        format="json",
    )
    assert response.status_code == 422
    assert "account" in response.data["detail"].lower()
