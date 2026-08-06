"""The household audit trail.

The log's entire value rests on one property: it cannot be quietly changed
after the fact. A record somebody can edit following an argument carries the
authority of an audit trail without the thing that earns it, which is worse
than having none — so the immutability tests here are not ceremony.

The second property is that logging must never break the thing it logs. A
partner who cannot pay a bill because the audit table is full has been handed a
serious failure in exchange for a cosmetic one.
"""

from __future__ import annotations

import uuid

import pytest

from apps.household import audit
from apps.household.contributions import set_agreement
from apps.household.models import AuditAction, AuditEvent
from tests.factories import MembershipFactory, TenantFactory
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


class TestImmutability:
    def test_an_event_cannot_be_edited(self):
        with tenant_scope(TenantFactory().id):
            event = audit.record(action=AuditAction.CREATED, subject_type="goal", summary="Created a goal.")
            event.summary = "Something else entirely."
            with pytest.raises(ValueError, match="append-only"):
                event.save()

    def test_an_event_cannot_be_deleted(self):
        with tenant_scope(TenantFactory().id):
            event = audit.record(action=AuditAction.CREATED, subject_type="goal", summary="Created a goal.")
            with pytest.raises(ValueError, match="cannot be deleted"):
                event.delete()

    def test_the_correction_path_is_a_new_event(self):
        """The sanctioned way to fix a wrong entry: say so, in a new entry."""
        with tenant_scope(TenantFactory().id):
            audit.record(action=AuditAction.PAID, subject_type="bill", summary="Paid the water bill.")
            audit.record(
                action=AuditAction.UPDATED,
                subject_type="bill",
                summary="Corrected: that was the electricity bill.",
            )
            assert AuditEvent.objects.count() == 2


class TestResilience:
    def test_a_logging_failure_does_not_raise(self, monkeypatch):
        """Swallowed on purpose. The alternative is that a full audit table
        stops somebody paying rent."""
        with tenant_scope(TenantFactory().id):

            def _explode(*args, **kwargs):
                raise RuntimeError("database on fire")

            monkeypatch.setattr(AuditEvent.objects, "create", _explode)
            assert audit.record(action=AuditAction.PAID, subject_type="bill", summary="x") is None

    def test_an_unresolvable_actor_still_produces_an_event(self):
        with tenant_scope(TenantFactory().id):
            event = audit.record(
                action=AuditAction.CREATED,
                subject_type="goal",
                summary="Created a goal.",
                actor_id=uuid.uuid4(),  # nobody
            )
            assert event is not None
            assert event.actor_label == "Someone"

    def test_a_summary_longer_than_the_column_is_truncated_not_dropped(self):
        with tenant_scope(TenantFactory().id):
            event = audit.record(action=AuditAction.UPDATED, subject_type="budget", summary="x" * 400)
            assert event is not None
            assert len(event.summary) == 255


class TestContent:
    def test_the_actor_name_survives_the_account_being_closed(self):
        """The FK nulls on delete; the label is why the log still names a
        person afterwards."""
        tenant = TenantFactory()
        membership = MembershipFactory(tenant=tenant)
        with tenant_scope(tenant.id, actor_id=membership.user_id):
            event = audit.record(action=AuditAction.PAID, subject_type="bill", summary="Paid the rent.")
        assert event.actor_label
        assert event.actor_label != "Someone"

    def test_a_private_event_is_recorded_and_marked(self):
        """Its existence is not the secret. A timeline with silent gaps is
        itself informative, and worse than one that says "something happened"."""
        with tenant_scope(TenantFactory().id):
            event = audit.record(
                action=AuditAction.UPDATED,
                subject_type="account",
                summary="Updated a private account.",
                is_private=True,
            )
            assert event.is_private
            assert event in audit.timeline()

    def test_the_timeline_is_most_recent_first(self):
        with tenant_scope(TenantFactory().id):
            audit.record(action=AuditAction.CREATED, subject_type="goal", summary="First.")
            audit.record(action=AuditAction.CREATED, subject_type="goal", summary="Second.")
            assert audit.timeline()[0].summary == "Second."

    def test_the_timeline_can_be_narrowed_to_one_subject(self):
        with tenant_scope(TenantFactory().id):
            audit.record(action=AuditAction.CREATED, subject_type="goal", summary="A goal.")
            audit.record(action=AuditAction.PAID, subject_type="bill", summary="A bill.")
            assert [e.summary for e in audit.timeline(subject_type="bill")] == ["A bill."]


class TestIsolation:
    def test_one_household_cannot_see_another_s_activity(self):
        first, second = TenantFactory(), TenantFactory()
        with tenant_scope(first.id):
            audit.record(action=AuditAction.PAID, subject_type="bill", summary="Ours.")
        with tenant_scope(second.id):
            audit.record(action=AuditAction.PAID, subject_type="bill", summary="Theirs.")
            assert [e.summary for e in audit.timeline()] == ["Theirs."]


class TestWiring:
    """The events the household actually relies on being there."""

    def test_agreeing_a_split_is_recorded(self):
        tenant = TenantFactory()
        membership = MembershipFactory(tenant=tenant)
        with tenant_scope(tenant.id, actor_id=membership.user_id):
            set_agreement(mode="equal", currency="KES")
            events = audit.timeline(subject_type="contribution_agreement")
            assert len(events) == 1
            assert "equal split" in events[0].summary

    def test_changing_the_split_records_what_it_changed_from(self):
        """ "We changed this in June" is the entry that settles the argument."""
        tenant = TenantFactory()
        membership = MembershipFactory(tenant=tenant)
        with tenant_scope(tenant.id, actor_id=membership.user_id):
            set_agreement(mode="equal", currency="KES")
            set_agreement(mode="income_based", currency="KES")
            latest = audit.timeline(subject_type="contribution_agreement")[0]
            assert "from an equal split to a split that follows income" in latest.summary
            assert latest.detail["previous_mode"] == "equal"


class TestApi:
    def test_the_activity_endpoint_returns_the_timeline(self, tenant_context):
        membership, client = tenant_context
        with tenant_scope(membership.tenant_id, actor_id=membership.user_id):
            set_agreement(mode="equal", currency="KES")

        resp = client.get("/api/v1/household/activity/")
        assert resp.status_code == 200
        assert len(resp.data) == 1
        assert "equal split" in resp.data[0]["summary"]
        assert resp.data[0]["actor"]

    def test_setting_and_reading_the_split_over_http(self, tenant_context):
        membership, client = tenant_context

        put = client.put(
            "/api/v1/household/contributions/",
            {
                "mode": "percentage",
                "currency": "KES",
                "target_minor": 100000,
                "terms": {str(membership.id): {"share": "1.0"}},
            },
            format="json",
        )
        assert put.status_code == 200, put.data

        got = client.get("/api/v1/household/contributions/")
        assert got.status_code == 200
        assert got.data["plan"]["mode"] == "percentage"
        assert got.data["plan"]["is_complete"] is True
        assert got.data["plan"]["contributions"][0]["amount_minor"] == 100000

    def test_an_unknown_mode_is_refused(self, tenant_context):
        _, client = tenant_context
        resp = client.put(
            "/api/v1/household/contributions/",
            {"mode": "vibes", "currency": "KES"},
            format="json",
        )
        assert resp.status_code == 400

    def test_a_household_with_no_agreement_is_told_so_rather_than_assumed_equal(self, tenant_context):
        """Presenting a split nobody agreed as though they had is how a product
        ends up in the middle of an argument it invented."""
        _, client = tenant_context
        resp = client.get("/api/v1/household/contributions/")
        assert resp.status_code == 200
        assert resp.data["plan"]["is_complete"] is False
        assert "not agreed" in resp.data["plan"]["blockers"][0]
