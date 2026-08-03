"""Regression tests for the production-readiness review fixes.

Grouped by the finding they close:
  P0-1  outbox relay actually publishes (and only marks published on success)
  P0-2  automation set_category by slug works
  P0-3  flag_review is a real, queryable state
  P0-4  intelligence API is wired and returns provider output
  P1-2  RLS fails closed (no tenant bound -> zero rows) at the API boundary
  P1-4  cross-tenant isolation at the HTTP layer
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from django.test import override_settings

from apps.common.models import OutboxEvent
from apps.common.publishing import reset_publisher_cache
from apps.common.tasks import relay_outbox
from apps.finance import services as finance_services
from apps.finance.models import AccountType, CategoryKind, Transaction
from apps.finance.payees import create_payee
from apps.intelligence import services as intel_services
from apps.intelligence.models import AutomationRule
from tests.conftest import _bearer_client
from tests.factories import MembershipFactory
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db

TENANT_HDR = "HTTP_X_TENANT_ID"


def _now():
    return datetime.now(UTC)


# ------------------------------------------------------------------ P0-1 outbox
class _CapturingPublisher:
    published: list = []

    def publish(self, event):
        _CapturingPublisher.published.append(str(event.event_id))


class _FailingPublisher:
    def publish(self, event):
        raise RuntimeError("broker down")


@override_settings(EVENT_PUBLISHER="tests.test_review_fixes._CapturingPublisher")
def test_outbox_relay_publishes_then_marks_published():
    reset_publisher_cache()
    _CapturingPublisher.published = []
    tenant = uuid.uuid4()
    ev = OutboxEvent.objects.create(
        tenant_id=tenant,
        aggregate_type="test.Agg",
        aggregate_id=uuid.uuid4(),
        event_type="test.happened",
        payload={"x": 1},
    )
    count = relay_outbox()
    ev.refresh_from_db()
    assert count == 1
    assert str(ev.event_id) in _CapturingPublisher.published  # actually delivered
    assert ev.published_at is not None  # marked only after delivery
    reset_publisher_cache()


@override_settings(EVENT_PUBLISHER="tests.test_review_fixes._FailingPublisher")
def test_outbox_relay_does_not_mark_published_on_failure():
    reset_publisher_cache()
    ev = OutboxEvent.objects.create(
        tenant_id=uuid.uuid4(),
        aggregate_type="test.Agg",
        aggregate_id=uuid.uuid4(),
        event_type="test.happened",
        payload={},
    )
    count = relay_outbox()
    ev.refresh_from_db()
    assert count == 0
    assert ev.published_at is None  # NOT lost — stays for retry
    reset_publisher_cache()


# ------------------------------------------------------------------ P0-2 slug
def test_automation_set_category_by_slug():
    with tenant_scope(uuid.uuid4()):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        groceries = finance_services.create_category(
            name="Groceries", kind=CategoryKind.EXPENSE, currency="USD"
        )
        misc = finance_services.create_category(
            name="Uncategorized", kind=CategoryKind.EXPENSE, currency="USD"
        )
        assert groceries.slug == "groceries"  # slug is populated

        AutomationRule.objects.create(
            name="Whole Foods -> groceries by slug",
            priority=10,
            conditions={"all": [{"field": "payee_normalized", "op": "contains", "value": "whole foods"}]},
            actions=[{"type": "set_category", "slug": "groceries"}],  # the docs-advertised shape
        )
        payee = create_payee(name="Whole Foods Market")
        txn = finance_services.record_expense(
            financial_account=checking,
            category=misc,
            amount_minor=4000,
            occurred_at=_now(),
            payee=payee,
        )
        finance_services.update_transaction(txn=txn, category=None)

        effects = intel_services.run_automation(txn)
        txn.refresh_from_db()
        assert txn.category_id == groceries.id  # slug matched — the P0-2 bug is fixed
        assert any("category" in e for e in effects)


# ------------------------------------------------------------------ P0-3 review
def test_automation_flag_review_sets_real_state():
    with tenant_scope(uuid.uuid4()):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        misc = finance_services.create_category(name="Misc", kind=CategoryKind.EXPENSE, currency="USD")
        AutomationRule.objects.create(
            name="Large -> review",
            priority=10,
            conditions={"all": [{"field": "amount_minor", "op": "abs_gte", "value": 100000}]},
            actions=[{"type": "flag_review", "reason": "large amount"}],
        )
        txn = finance_services.record_expense(
            financial_account=checking,
            category=misc,
            amount_minor=250000,
            occurred_at=_now(),
        )
        finance_services.update_transaction(txn=txn, category=None)
        intel_services.run_automation(txn)
        txn.refresh_from_db()
        assert txn.needs_review is True
        assert txn.review_reason == "large amount"
        # queryable review queue
        assert Transaction.objects.filter(needs_review=True).count() == 1


# ------------------------------------------------------------------ P0-4 API wired
def test_health_score_endpoint_returns_provider_output(tenant_context):
    _membership, client = tenant_context
    resp = client.get("/api/v1/intelligence/health-score/")
    assert resp.status_code == 200, resp.data
    assert "score" in resp.data and "components" in resp.data
    assert len(resp.data["components"]) == 5


def test_recommendations_endpoint_wired(tenant_context):
    _membership, client = tenant_context
    resp = client.get("/api/v1/intelligence/recommendations/")
    assert resp.status_code == 200
    assert isinstance(resp.data, list)


def test_automation_rule_create_validates_action_allowlist(tenant_context):
    _membership, client = tenant_context
    # a disallowed action must be rejected at save time
    bad = client.post(
        "/api/v1/intelligence/automation-rules/",
        {
            "name": "evil",
            "conditions": {"all": [{"field": "memo", "op": "contains", "value": "x"}]},
            "actions": [{"type": "post_journal_entry"}],
        },
        format="json",
    )
    assert bad.status_code == 422
    good = client.post(
        "/api/v1/intelligence/automation-rules/",
        {
            "name": "ok",
            "conditions": {"all": [{"field": "memo", "op": "contains", "value": "x"}]},
            "actions": [{"type": "flag_review"}],
        },
        format="json",
    )
    assert good.status_code == 201


# ------------------------------------------------------------------ P1-4 isolation
def test_api_cross_tenant_isolation():
    """Tenant A creates an account; tenant B must not see it through the API."""
    m_a = MembershipFactory()
    m_b = MembershipFactory()
    client_a = _bearer_client(m_a.user, tenant_id=m_a.tenant_id)
    client_b = _bearer_client(m_b.user, tenant_id=m_b.tenant_id)

    created = client_a.post(
        "/api/v1/finance/accounts/",
        {"name": "A-Checking", "account_type": "checking", "currency": "USD"},
        format="json",
    )
    assert created.status_code == 201

    a_list = client_a.get("/api/v1/finance/accounts/")
    b_list = client_b.get("/api/v1/finance/accounts/")
    assert any(a["name"] == "A-Checking" for a in a_list.data)
    assert all(a["name"] != "A-Checking" for a in b_list.data)  # RLS isolates


def test_api_requires_tenant_membership():
    """A user with no membership in the requested tenant is refused — the
    permission gate in front of RLS."""
    m_a = MembershipFactory()
    outsider = MembershipFactory()  # a different tenant/user
    # outsider's user, but ask for tenant A's id
    client = _bearer_client(outsider.user, tenant_id=m_a.tenant_id)
    resp = client.get("/api/v1/finance/accounts/")
    assert resp.status_code in (403, 404)  # not authorized for that tenant


def test_rls_fails_closed_without_tenant():
    """Direct-DB proof: with no tenant GUC bound, a tenant-scoped query returns
    zero rows rather than everything (fail-closed).

    In production each request is its own transaction, so the request-scoped
    `SET LOCAL app.current_tenant` never leaks to the next request. The test
    harness runs inside one wrapping transaction, so we reset the GUC
    explicitly to reproduce the 'fresh connection, no tenant' state a new
    request sees.
    """
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        finance_services.create_financial_account(
            name="Scoped", account_type=AccountType.CHECKING, currency="USD"
        )

    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("RESET app.current_tenant")  # simulate a fresh, unbound request
        cur.execute("SELECT count(*) FROM finance_financialaccount")
        (visible,) = cur.fetchone()
    assert visible == 0  # fail-closed: unset GUC -> NULL -> zero rows


# ------------------------------------------------------------------ P3-5 bulk_create stamping
def test_bulk_created_tags_are_tenant_stamped_and_rls_visible():
    """bulk_create bypasses Model.save(), so tenant_id must be stamped
    explicitly. Regression guard for the previously-fixed tagging path: a
    bulk-created TransactionTag must be visible under its tenant's RLS (proving
    tenant_id was set) and carry the right tenant."""
    from apps.finance import tagging
    from apps.finance.models import Tag, TransactionTag

    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        cat = finance_services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
        txn = finance_services.record_expense(
            financial_account=checking, category=cat, amount_minor=1000, occurred_at=_now()
        )
        tag = Tag.objects.create(name="reimbursable", tenant_id=tenant)
        tagging.set_transaction_tags(txn=txn, tags=[tag])

        links = list(TransactionTag.objects.filter(transaction=txn))
        assert len(links) == 1  # RLS-visible => tenant_id was stamped
        assert links[0].tenant_id == tenant
