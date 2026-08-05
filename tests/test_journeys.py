"""End-to-end user journeys.

Every step below already has unit and API tests. The journeys exist because
that was not enough: the invitation flow shipped broken in two independent ways
while `create_invitation`, `send_invitation_email` and `AcceptInvitePage` all
had passing tests. Nothing tested the *seam*.

So these tests deliberately assert the outcome a person gets rather than the
mechanism that delivers it — the habit that would have caught the export 401
and the inline-dispatch race, both of which had tests asserting the broken
mechanism and passing.

They are slower than unit tests and there are only four. That is the intended
trade: they are a smoke alarm for integration, not a substitute for the 1,266
tests underneath.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.finance.models import Transaction, TransactionStatus
from apps.tenancy.models import Role
from tests.conftest import _bearer_client
from tests.factories import MembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _client(membership):
    return _bearer_client(membership.user, tenant_id=membership.tenant_id)


def _account(client, name="Current", kind="checking", opening=1_000_000):
    # Funded: a workspace blocks manual overdrafts by default, so an account
    # with nothing in it cannot record an expense.
    r = client.post(
        "/api/v1/finance/accounts/",
        {
            "name": name,
            "account_type": kind,
            "currency": "USD",
            "opening_balance_minor": opening,
        },
        format="json",
    )
    assert r.status_code in (200, 201), r.data
    return r.data


def _category(client, name="Groceries", kind="expense"):
    r = client.post(
        "/api/v1/finance/categories/",
        {"name": name, "kind": kind, "currency": "USD"},
        format="json",
    )
    assert r.status_code in (200, 201), r.data
    return r.data


# ============================================================================
# Journey 1 — set up a workspace and see money land in a budget
# ============================================================================
def test_journey_import_to_budget():
    """From an empty workspace to a budget that reflects imported spending.

    This is the product's core loop. Each step is individually tested; what is
    tested here is that the output of one is the input of the next — an import
    that posts to the ledger, a budget that reads the ledger, and a number that
    matches what was in the CSV.
    """
    membership = MembershipFactory(role=Role.OWNER)
    client = _client(membership)

    account = _account(client)
    groceries = _category(client, "Groceries")

    # --- import a bank statement -------------------------------------------
    csv = (
        "date,description,amount,external_id\n"
        "2026-03-02,TESCO STORES,-42.50,tx-001\n"
        "2026-03-09,TESCO STORES,-31.25,tx-002\n"
        "2026-03-16,SALARY,2000.00,tx-003\n"
    )
    imported = client.post(
        "/api/v1/finance/transactions/import/",
        {"account_id": account["id"], "content": csv, "default_category_id": groceries["id"]},
        format="json",
    )
    assert imported.status_code == 201, imported.data
    assert imported.data["imported"] == 3, imported.data

    # --- re-importing the same file changes nothing ------------------------
    # The property that matters to a user is "I didn't double-count my rent",
    # not "the dedupe branch executed".
    again = client.post(
        "/api/v1/finance/transactions/import/",
        {"account_id": account["id"], "content": csv, "default_category_id": groceries["id"]},
        format="json",
    )
    assert again.data["imported"] == 0
    assert again.data["skipped_duplicate"] == 3

    # --- the money is in the ledger, not just a table -----------------------
    # The journal link is internal and deliberately not serialised, so this
    # checks the data rather than the response: an import that created rows
    # without posting them would leave every balance and report wrong while the
    # transaction list looked perfectly correct.
    listing = client.get("/api/v1/finance/transactions/").data
    rows = listing["results"] if isinstance(listing, dict) else listing
    assert len(rows) == 3

    from django.db import transaction as db_transaction

    from apps.common.rls import bind_db_tenant
    from apps.common.tenant_context import use_tenant

    with db_transaction.atomic():
        bind_db_tenant(membership.tenant_id)
        with use_tenant(membership.tenant_id, actor_id=membership.user_id):
            posted = Transaction.objects.filter(journal_entry__isnull=False).count()
    assert posted == 3, "imported rows must post to the ledger"

    # --- a budget reads that spending --------------------------------------
    budget = client.post(
        "/api/v1/budgeting/budgets/",
        {"name": "March", "currency": "USD", "starts_on": "2026-03-01", "period": "monthly"},
        format="json",
    )
    assert budget.status_code in (200, 201), budget.data
    line = client.post(
        f"/api/v1/budgeting/budgets/{budget.data['id']}/lines/",
        {"category_id": groceries["id"], "limit_minor": 10_000},
        format="json",
    )
    assert line.status_code in (200, 201), line.data

    status_body = client.get(
        f"/api/v1/budgeting/budgets/{budget.data['id']}/status/",
        {"as_of": "2026-03-31"},
    )
    assert status_body.status_code == 200, status_body.data
    lines = status_body.data["lines"]
    # Ids come back as UUID objects from create and strings from status, so
    # compare as strings rather than relying on the serialiser being uniform.
    groceries_line = next(row for row in lines if str(row["category_id"]) == str(groceries["id"]))

    # $42.50 + $31.25 of groceries, and the salary must not be counted as spend.
    assert groceries_line["actual_minor"] == 7375, groceries_line
    assert groceries_line["limit_minor"] == 10_000
    assert groceries_line["remaining_minor"] == 2625


# ============================================================================
# Journey 2 — invite a member and confirm their role actually limits them
# ============================================================================
def test_journey_invite_member_and_role_limits(django_capture_on_commit_callbacks):
    """The flow that shipped broken twice.

    Asserts what the invitee experiences: an email arrives, it contains a link
    that resolves to the accept page, the token in it works, and afterwards the
    role they were given is the role they actually have.
    """
    owner = MembershipFactory(role=Role.OWNER)
    client = _client(owner)
    invitee = UserFactory(email="newcomer@example.test")
    mail.outbox.clear()

    # --- the invitation is sent, not merely recorded ------------------------
    from django.test import override_settings

    # Delivery is deferred to `transaction.on_commit` so a worker can never
    # race the commit. pytest wraps each test in a transaction that never
    # commits, so the journey has to run the hooks explicitly — the need to do
    # so is itself evidence the dispatch is deferred rather than inline.
    with (
        override_settings(FRONTEND_BASE_URL="https://app.example.test"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        sent = client.post(
            "/api/v1/tenancy/workspaces/invitations/",
            {"email": invitee.email, "role": Role.VIEWER},
            format="json",
        )
        assert sent.status_code in (200, 201), sent.data

    assert len(mail.outbox) == 1, "the invitee received nothing"
    body = mail.outbox[0].body
    assert invitee.email in mail.outbox[0].to

    # --- the link in the email actually goes somewhere ----------------------
    import re

    match = re.search(r"https://app\.example\.test(/[^\s?]+)\?token=([\w\-]+)", body)
    assert match, f"no usable accept link in the email:\n{body}"
    path, token = match.group(1), match.group(2)

    import pathlib

    routes = set(re.findall(r'<Route\s+path="([^"]+)"', pathlib.Path("frontend/app/src/App.tsx").read_text()))
    assert path in routes, f"the email links to {path}, which is not a page"

    # --- the token works ----------------------------------------------------
    invitee_client = _bearer_client(invitee)
    accepted = invitee_client.post("/api/v1/tenancy/invitations/accept/", {"token": token}, format="json")
    assert accepted.status_code in (200, 201), accepted.data

    # --- and the role they were given is the role they have -----------------
    member_client = _bearer_client(invitee, tenant_id=owner.tenant_id)
    assert member_client.get("/api/v1/finance/accounts/").status_code == 200
    blocked = member_client.post(
        "/api/v1/finance/accounts/",
        {"name": "Should not exist", "account_type": "checking", "currency": "USD"},
        format="json",
    )
    assert blocked.status_code == 403, "a VIEWER wrote to the workspace"


# ============================================================================
# Journey 3 — a payment fails, recovery runs, access comes back
# ============================================================================
def test_journey_failed_payment_to_recovery():
    """Billing, dunning, tenancy and notifications, in the order they happen.

    The user-visible arc is: the card fails, the workspace eventually locks,
    the customer pays, and everything they had is still there.
    """
    from apps.billing import dunning
    from apps.billing.dunning_models import DunningCase, DunningCaseStatus
    from apps.billing.models import (
        BillingInterval,
        Payment,
        PaymentStatus,
        Plan,
        PlanTier,
        Subscription,
        SubscriptionStatus,
    )
    from apps.tenancy.models import Tenant

    membership = MembershipFactory(role=Role.OWNER)
    tenant_id = membership.tenant_id
    dunning.ensure_default_policy()

    plan = Plan.objects.create(
        tier=PlanTier.PLUS,
        name="Plus",
        price_minor=900,
        currency="USD",
        interval=BillingInterval.MONTHLY,
    )
    sub = Subscription.objects.create(
        tenant_id=tenant_id, plan=plan, status=SubscriptionStatus.ACTIVE, provider="stripe"
    )

    # --- the card fails -----------------------------------------------------
    failed = Payment.objects.create(
        tenant_id=tenant_id,
        subscription=sub,
        amount_minor=900,
        currency="USD",
        status=PaymentStatus.FAILED,
        provider="stripe",
        failure_reason="card_declined",
    )
    case = dunning.on_payment_failed(payment=failed)
    assert case is not None

    # Access is not revoked immediately — the grace period is the point.
    assert Tenant.objects.get(id=tenant_id).is_active
    assert _client(membership).get("/api/v1/finance/accounts/").status_code == 200

    # --- nobody pays, so the workspace locks --------------------------------
    dunning.run_due_attempts(now=timezone.now() + timedelta(days=22))
    case.refresh_from_db()
    assert case.status == DunningCaseStatus.SUSPENDED
    assert not Tenant.objects.get(id=tenant_id).is_active

    # --- the customer pays --------------------------------------------------
    recovered = Payment.objects.create(
        tenant_id=tenant_id,
        subscription=sub,
        amount_minor=900,
        currency="USD",
        status=PaymentStatus.SUCCEEDED,
        provider="stripe",
    )
    dunning.on_payment_succeeded(payment=recovered)

    # --- and everything is back ---------------------------------------------
    case.refresh_from_db()
    sub.refresh_from_db()
    assert case.status == DunningCaseStatus.RECOVERED
    assert sub.status == SubscriptionStatus.ACTIVE
    assert Tenant.objects.get(id=tenant_id).is_active
    assert _client(membership).get("/api/v1/finance/accounts/").status_code == 200

    # Nothing scheduled may still fire at a customer who has paid.
    assert not DunningCase.objects.filter(subscription=sub, status=DunningCaseStatus.OPEN).exists()


# ============================================================================
# Journey 4 — reconcile a statement to zero
# ============================================================================
def test_journey_reconcile_a_statement():
    """The trust ritual: tick off what cleared and watch the difference vanish.

    Runs the whole loop rather than the endpoint — spend, discover a gap,
    reconcile part of it, confirm the remainder is exactly what has not cleared.
    """
    membership = MembershipFactory(role=Role.OWNER)
    client = _client(membership)
    account = _account(client)
    category = _category(client, "Living")

    def spend(amount, memo, days_ago):
        r = client.post(
            "/api/v1/finance/transactions/",
            {
                "type": "expense",
                "financial_account_id": account["id"],
                "category_id": category["id"],
                "amount_minor": amount,
                "occurred_at": (timezone.now() - timedelta(days=days_ago)).isoformat(),
                "memo": memo,
            },
            format="json",
        )
        assert r.status_code in (200, 201), r.data
        return r.data

    on_statement = [spend(2500, "Rent", 20), spend(1200, "Power", 18)]
    still_in_flight = spend(800, "Cheque not yet cleared", 2)

    # --- the bank says -3700; the ledger says -4500 --------------------------
    before = client.get(
        f"/api/v1/finance/accounts/{account['id']}/reconciliation/",
        {"statement_balance_minor": -3700},
    ).data
    assert before["ledger_balance_minor"] == -4500
    assert before["difference_minor"] == -3700, "nothing reconciled yet"
    assert before["is_balanced"] is False

    # --- tick off what appears on the statement ------------------------------
    marked = client.post(
        "/api/v1/finance/transactions/reconcile/",
        {"transaction_ids": [t["id"] for t in on_statement]},
        format="json",
    )
    assert marked.data["updated"] == 2

    # --- the difference reaches zero, and the remainder is explained ---------
    after = client.get(
        f"/api/v1/finance/accounts/{account['id']}/reconciliation/",
        {"statement_balance_minor": -3700},
    ).data
    assert after["difference_minor"] == 0
    assert after["is_balanced"] is True
    assert after["uncleared_minor"] == -800
    assert [r["memo"] for r in after["uncleared"]] == ["Cheque not yet cleared"]

    # --- and the workspace can see who did it -------------------------------
    activity = client.get("/api/v1/tenancy/workspaces/activity/").json()
    rows = activity["results"] if isinstance(activity, dict) else activity
    assert any(r["action"] == "transactions.reconciled" for r in rows)

    # Reconciling does not alter the money, only its confirmation state.
    unchanged = Transaction.unscoped.get(id=still_in_flight["id"])
    assert unchanged.status == TransactionStatus.POSTED
