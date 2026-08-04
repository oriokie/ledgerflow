"""Regression tests for the pre-launch audit findings.

Each test names the finding it locks down, so a future reader can tell what the
assertion is defending against rather than inferring it from the mechanics.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from django.db import transaction
from django.db.utils import IntegrityError

from apps.common import audit as tenant_audit
from apps.common.audit import AuditLog
from apps.common.frontend_urls import invitation_accept, password_reset
from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant
from apps.investments.models import Security
from apps.tenancy import services as tenancy
from apps.tenancy.models import Role
from tests.conftest import _bearer_client
from tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


@contextmanager
def _tenant(membership):
    with transaction.atomic():
        bind_db_tenant(membership.tenant_id)
        with use_tenant(membership.tenant_id, actor_id=membership.user_id):
            yield


def _client(membership):
    return _bearer_client(membership.user, tenant_id=membership.tenant_id)


# ============================================================ D-2: frontend URLs
def test_invitation_link_points_at_the_real_route(settings):
    """Previously derived from OAUTH_REDIRECT_URI, producing the wrong origin,
    a stray /auth segment, and a path that was never a page."""
    settings.FRONTEND_BASE_URL = "https://app.example.com"
    assert invitation_accept("tok123") == "https://app.example.com/invite?token=tok123"


def test_reset_link_points_at_the_real_route(settings):
    settings.FRONTEND_BASE_URL = "https://app.example.com"
    assert password_reset("tok123") == "https://app.example.com/reset-password?token=tok123"


def test_frontend_base_url_tolerates_a_trailing_slash(settings):
    settings.FRONTEND_BASE_URL = "https://app.example.com/"
    assert "//invite" not in invitation_accept("t")


def test_invitation_email_url_matches_a_declared_react_route(settings):
    """Guards the class of bug, not just the instance: if the SPA route is
    renamed without updating frontend_urls, this fails."""
    import pathlib
    import re

    app = pathlib.Path("frontend/app/src/App.tsx").read_text()
    routes = set(re.findall(r'<Route\s+path="([^"]+)"', app))
    settings.FRONTEND_BASE_URL = "http://x"
    for url, expected in ((invitation_accept("t"), "/invite"), (password_reset("t"), "/reset-password")):
        assert expected in routes, f"{expected} is not a declared route"
        assert url.startswith(f"http://x{expected}")


# ====================================================== D-1: dispatch after commit
def test_invitation_email_is_queued_only_after_commit(monkeypatch, django_capture_on_commit_callbacks):
    """The worker runs on another connection; dispatching inline raced the
    commit and the task silently returned without sending.

    pytest-django wraps each test in a transaction that never commits, so
    `on_commit` callbacks are captured rather than fired — which is precisely
    what proves the dispatch is registered as a callback and not called inline.
    """
    membership = MembershipFactory(role=Role.OWNER)
    dispatched: list = []

    from apps.tenancy import tasks

    monkeypatch.setattr(tasks.send_invitation_email, "delay", lambda **kw: dispatched.append(kw))

    with django_capture_on_commit_callbacks(execute=True) as callbacks, _tenant(membership):
        tenancy.create_invitation(
            tenant=membership.tenant,
            invited_by_membership=membership,
            email="new@example.test",
            role=Role.MEMBER,
        )
        # Nothing dispatched while the block was open — it was deferred.
    assert len(callbacks) == 1
    assert len(dispatched) == 1
    assert dispatched[0]["invitation_id"]


def test_a_rolled_back_invitation_never_emails_anyone(monkeypatch, django_capture_on_commit_callbacks):
    """A rolled-back invitation must not email a token that will never work."""
    membership = MembershipFactory(role=Role.OWNER)
    dispatched: list = []
    from apps.tenancy import tasks

    monkeypatch.setattr(tasks.send_invitation_email, "delay", lambda **kw: dispatched.append(kw))

    with (
        django_capture_on_commit_callbacks(execute=True),
        pytest.raises(RuntimeError),
        _tenant(membership),
    ):
        tenancy.create_invitation(
            tenant=membership.tenant,
            invited_by_membership=membership,
            email="new@example.test",
            role=Role.MEMBER,
        )
        raise RuntimeError("something later failed")

    assert dispatched == []


# ================================================================ D-3: audit trail
def test_closing_a_workspace_is_recorded():
    membership = MembershipFactory(role=Role.OWNER)
    with _tenant(membership):
        tenancy.close_workspace(tenant=membership.tenant, actor_membership=membership)
        row = AuditLog.objects.get(action="workspace.closed")
        assert row.actor_id == membership.user_id
        assert row.changes["is_active"] == [True, False]


def test_a_role_change_records_both_sides():
    owner = MembershipFactory(role=Role.OWNER)
    member = MembershipFactory(tenant=owner.tenant, role=Role.MEMBER)
    with _tenant(owner):
        tenancy.change_member_role(actor_membership=owner, target_membership=member, new_role=Role.VIEWER)
        row = AuditLog.objects.get(action="member.role_changed")
        assert row.changes["role"] == [Role.MEMBER, Role.VIEWER]


def test_removing_a_member_is_attributable():
    """The question a shared household most wants answered."""
    owner = MembershipFactory(role=Role.OWNER)
    member = MembershipFactory(tenant=owner.tenant, role=Role.MEMBER)
    with _tenant(owner):
        tenancy.remove_member(actor_membership=owner, target_membership=member)
        row = AuditLog.objects.get(action="member.removed")
        assert row.actor_id == owner.user_id


def test_audit_rows_carry_the_tenant_that_produced_them():
    """This table is deliberately not RLS-protected (it records workspace
    creation, which predates a bound tenant), so correct `tenant_id` stamping
    is what any reader must filter on."""
    a, b = MembershipFactory(role=Role.OWNER), MembershipFactory(role=Role.OWNER)
    with _tenant(a):
        tenancy.close_workspace(tenant=a.tenant, actor_membership=a)
    row = AuditLog.objects.get(action="workspace.closed")
    assert row.tenant_id == a.tenant_id
    assert row.tenant_id != b.tenant_id


def test_audit_never_breaks_an_operation_when_no_tenant_is_bound():
    """Services run from management commands and Celery too."""
    assert tenant_audit.record(action="x.y", target_type="t", target_id=uuid.uuid4()) is None


def test_diff_keeps_only_what_moved():
    changes = tenant_audit.diff({"a": 1, "b": 2}, {"a": 1, "b": 3})
    assert changes == {"b": [2, 3]}


def test_the_audit_log_is_append_only():
    membership = MembershipFactory(role=Role.OWNER)
    with _tenant(membership):
        tenancy.close_workspace(tenant=membership.tenant, actor_membership=membership)
        row = AuditLog.objects.get(action="workspace.closed")
    # The BEFORE UPDATE trigger's RAISE EXCEPTION surfaces through psycopg as
    # IntegrityError, not a bare Exception — narrowed so this only passes for
    # the trigger actually firing, not any unrelated failure in the block.
    with pytest.raises(IntegrityError), transaction.atomic():
        AuditLog.objects.filter(pk=row.pk).update(action="tampered")


# ============================================================== F-2: securities
def test_a_mistyped_security_can_be_corrected():
    membership = MembershipFactory()
    client = _client(membership)
    created = client.post(
        "/api/v1/investments/securities/",
        {"symbol": "BONDKEDDD", "name": "Kenya Bond", "asset_class": "bond", "currency": "KES"},
        format="json",
    )
    assert created.status_code == 201

    fixed = client.patch(
        f"/api/v1/investments/securities/{created.data['id']}/", {"symbol": "BONDKE"}, format="json"
    )
    assert fixed.status_code == 200
    assert fixed.data["symbol"] == "BONDKE"


def test_a_security_can_be_deleted_and_the_symbol_reused():
    """The typo case: delete the wrong one, create the right one."""
    membership = MembershipFactory()
    client = _client(membership)
    payload = {"symbol": "VTI", "name": "Total Market", "asset_class": "etf", "currency": "USD"}
    created = client.post("/api/v1/investments/securities/", payload, format="json")

    assert client.delete(f"/api/v1/investments/securities/{created.data['id']}/").status_code == 204
    assert client.get("/api/v1/investments/securities/").data == []
    # Unique constraint is scoped to live rows, so the symbol is free again.
    assert client.post("/api/v1/investments/securities/", payload, format="json").status_code == 201


def test_renaming_onto_an_existing_symbol_is_refused():
    membership = MembershipFactory()
    client = _client(membership)
    a = client.post(
        "/api/v1/investments/securities/",
        {"symbol": "AAA", "name": "A", "asset_class": "etf", "currency": "USD"},
        format="json",
    )
    client.post(
        "/api/v1/investments/securities/",
        {"symbol": "BBB", "name": "B", "asset_class": "etf", "currency": "USD"},
        format="json",
    )
    clash = client.patch(f"/api/v1/investments/securities/{a.data['id']}/", {"symbol": "BBB"}, format="json")
    assert clash.status_code == 422
    assert "already tracked" in clash.data["detail"]


def test_a_security_with_holdings_cannot_be_deleted():
    """Deleting it would orphan positions and rewrite historical cost basis.

    The FK is `on_delete=PROTECT`, so the database already refused this — the
    service check exists to turn a raw ProtectedError into a sentence the user
    can act on.
    """
    from apps.investments import services as inv

    membership = MembershipFactory()
    client = _client(membership)
    created = client.post(
        "/api/v1/investments/securities/",
        {"symbol": "VOO", "name": "S&P 500", "asset_class": "etf", "currency": "USD"},
        format="json",
    )
    account = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Brokerage", "account_type": "investment", "currency": "USD"},
        format="json",
    )
    assert account.status_code in (200, 201), account.data

    with _tenant(membership):
        from apps.finance.models import FinancialAccount
        from apps.investments.models import Holding

        Holding.objects.create(
            security=Security.objects.get(id=created.data["id"]),
            financial_account=FinancialAccount.objects.get(id=account.data["id"]),
            quantity="1",
        )
        with pytest.raises(inv.InvestmentError, match="history refers to it"):
            inv.delete_security(security=Security.objects.get(id=created.data["id"]))


def test_a_missing_security_is_a_404_not_a_500():
    membership = MembershipFactory()
    assert (
        _client(membership)
        .patch(f"/api/v1/investments/securities/{uuid.uuid4()}/", {"name": "x"}, format="json")
        .status_code
        == 404
    )


# ==================================================================== F-3: tags
def test_a_tag_can_be_renamed_and_deleted():
    membership = MembershipFactory()
    client = _client(membership)
    created = client.post("/api/v1/finance/tags/", {"name": "hoilday"}, format="json")
    assert created.status_code == 201

    renamed = client.patch(f"/api/v1/finance/tags/{created.data['id']}/", {"name": "holiday"}, format="json")
    assert renamed.status_code == 200
    assert renamed.data["name"] == "holiday"

    assert client.delete(f"/api/v1/finance/tags/{created.data['id']}/").status_code == 204
    assert client.get("/api/v1/finance/tags/").data == []


def test_renaming_onto_an_existing_tag_is_refused():
    membership = MembershipFactory()
    client = _client(membership)
    a = client.post("/api/v1/finance/tags/", {"name": "travel"}, format="json")
    client.post("/api/v1/finance/tags/", {"name": "food"}, format="json")
    clash = client.patch(f"/api/v1/finance/tags/{a.data['id']}/", {"name": "food"}, format="json")
    assert clash.status_code == 409


def test_deleting_a_tag_frees_its_name():
    membership = MembershipFactory()
    client = _client(membership)
    created = client.post("/api/v1/finance/tags/", {"name": "temp"}, format="json")
    client.delete(f"/api/v1/finance/tags/{created.data['id']}/")
    assert client.post("/api/v1/finance/tags/", {"name": "temp"}, format="json").status_code == 201


# ============================================================ D-4: learning store
def test_merchant_profile_is_locked_before_mutation():
    """Counters and the category_counts JSON were read-modify-write; a
    concurrent update lost an entire category key, not just an increment."""
    import inspect

    from apps.intelligence import automation_services

    src = inspect.getsource(automation_services.learn_from_transaction)
    assert "select_for_update" in src


# ============================================================== D-5: plan limits
def test_seat_check_takes_a_lock_before_counting():
    import inspect

    src = inspect.getsource(tenancy.add_member)
    assert "lock_tenant_for_limit_check" in src
    assert src.index("lock_tenant_for_limit_check") < src.index("ensure_can_add_member(")


# ================================================================== D-6: drift
def test_balance_drift_raises_a_platform_alert():
    import inspect

    from apps.finance import tasks as finance_tasks

    src = inspect.getsource(finance_tasks.reconcile_balances_for_tenant)
    assert "raise_platform_alert" in src
    assert "ledger.drift" in src


# ====================================================== G-6: reading the trail
def test_a_member_can_read_the_workspace_activity_trail():
    """The question a shared household actually asks: who deleted that?"""
    owner = MembershipFactory(role=Role.OWNER)
    member = MembershipFactory(tenant=owner.tenant, role=Role.MEMBER)
    with _tenant(owner):
        tenancy.change_member_role(actor_membership=owner, target_membership=member, new_role=Role.VIEWER)

    body = _client(owner).get("/api/v1/tenancy/workspaces/activity/").json()
    rows = body["results"] if isinstance(body, dict) else body
    entry = next(r for r in rows if r["action"] == "member.role_changed")

    assert entry["label"] == "Changed a member's role"
    assert entry["actor_name"] == (owner.user.full_name or owner.user.email)
    assert entry["changes"]["role"] == [Role.MEMBER, Role.VIEWER]


def test_the_activity_trail_is_scoped_to_the_workspace():
    """This table is deliberately not RLS-protected, so the endpoint's own
    filtering is the whole isolation guarantee."""
    a = MembershipFactory(role=Role.OWNER)
    b = MembershipFactory(role=Role.OWNER)
    with _tenant(a):
        tenancy.close_workspace(tenant=a.tenant, actor_membership=a)

    body = _client(b).get("/api/v1/tenancy/workspaces/activity/").json()
    rows = body["results"] if isinstance(body, dict) else body
    assert rows == []


def test_a_viewer_cannot_read_the_activity_trail():
    """Who administered the workspace is governance, not finance."""
    owner = MembershipFactory(role=Role.OWNER)
    viewer = MembershipFactory(tenant=owner.tenant, role=Role.VIEWER)
    assert _client(viewer).get("/api/v1/tenancy/workspaces/activity/").status_code == 403


def test_a_system_action_is_labelled_as_automation():
    """Null actor means a task or webhook — different from an unknown person."""
    membership = MembershipFactory(role=Role.OWNER)
    with _tenant(membership):
        tenant_audit.record(
            action="transaction.voided",
            target_type="finance.Transaction",
            target_id=uuid.uuid4(),
            actor_id=None,
        )

    body = _client(membership).get("/api/v1/tenancy/workspaces/activity/").json()
    rows = body["results"] if isinstance(body, dict) else body
    assert rows[0]["actor_name"] == "Automation"


def test_resolving_actor_names_does_not_scale_with_row_count(django_assert_num_queries):
    """A 50-row page must not become 50 lookups."""
    owner = MembershipFactory(role=Role.OWNER)
    with _tenant(owner):
        for _ in range(12):
            tenant_audit.record(
                action="transaction.voided",
                target_type="finance.Transaction",
                target_id=uuid.uuid4(),
                actor_id=owner.user_id,
            )

    client = _client(owner)
    # Warm auth/membership lookups so the assertion covers the view only.
    client.get("/api/v1/tenancy/workspaces/activity/")
    with django_assert_num_queries(7):
        client.get("/api/v1/tenancy/workspaces/activity/")


def test_an_unlabelled_action_still_appears():
    """Dropping unknown actions would make the log lie by omission."""
    membership = MembershipFactory(role=Role.OWNER)
    with _tenant(membership):
        tenant_audit.record(
            action="some.future.action", target_type="x", target_id=uuid.uuid4(), actor_id=membership.user_id
        )

    body = _client(membership).get("/api/v1/tenancy/workspaces/activity/").json()
    rows = body["results"] if isinstance(body, dict) else body
    assert rows[0]["label"] == "some.future.action"


def test_a_bad_since_filter_is_a_field_error():
    membership = MembershipFactory(role=Role.OWNER)
    response = _client(membership).get("/api/v1/tenancy/workspaces/activity/", {"since": "last tuesday"})
    assert response.status_code == 400
    assert "since" in response.json()
