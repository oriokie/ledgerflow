"""Amount-triggered spend approvals.

The property this suite exists to protect is the one a naive implementation
blurs: **a request and a flag are not the same event.** A request is asked
before the money moves and approving it is a decision; a flag is raised after
and approving it is a review. If the two collapse, the interface can claim it
blocked a purchase it merely noticed — a claim the product cannot support and
would be caught making at the worst possible moment.

The second property is that silence is not consent, and also not refusal.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.finance import services as finance_services
from apps.finance.models import AccountType
from apps.household import approvals, audit
from apps.household.models import (
    AccountSharing,
    ApprovalKind,
    ApprovalRule,
    ApprovalScope,
    ApprovalStatus,
    SharingPolicy,
    SpendApproval,
)
from tests.factories import MembershipFactory, TenantFactory
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


def _couple():
    """A household of two, which is the only shape any of this matters in."""
    tenant = TenantFactory()
    amina = MembershipFactory(tenant=tenant)
    brian = MembershipFactory(tenant=tenant)
    return tenant, amina, brian


def _joint_account(owner=None, *, joint=True, policy=SharingPolicy.SHARED):
    account = finance_services.create_financial_account(
        name="Joint current",
        account_type=AccountType.CHECKING,
        currency="KES",
        # Funded: the overdraft guard is right to refuse a 50,000 purchase from
        # an empty account, and an unfunded fixture would be testing that guard
        # rather than the approval engine.
        opening_balance_minor=500_000_00,
    )
    AccountSharing.objects.create(financial_account=account, owner=owner, policy=policy, is_joint=joint)
    return account


def _rule(**kwargs):
    defaults = {
        "scope": ApprovalScope.JOINT,
        "currency": "KES",
        "min_amount_minor": 20_000_00,
        "expires_after_hours": 48,
    }
    return ApprovalRule.objects.create(**{**defaults, **kwargs})


class TestMatching:
    def test_below_the_threshold_needs_nobody(self):
        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            _rule(min_amount_minor=20_000_00)
            verdict = approvals.require_approval_for(amount_minor=19_999_00, account_id=account.id)
            assert verdict.required is False

    def test_at_the_threshold_needs_approval(self):
        """ "Above 20,000" is read inclusively at the boundary; a rule that
        fires at 20,000.01 but not 20,000.00 is a rule people think is broken."""
        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            _rule(min_amount_minor=20_000_00)
            assert approvals.require_approval_for(amount_minor=20_000_00, account_id=account.id).required

    def test_the_sign_of_the_amount_does_not_matter(self):
        """Callers pass ledger amounts, where spending is negative. They should
        not have to remember that."""
        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            _rule(min_amount_minor=20_000_00)
            assert approvals.require_approval_for(amount_minor=-50_000_00, account_id=account.id).required

    def test_the_highest_matching_threshold_wins(self):
        """So "tell me over 20k" and "give us longer over 100k" do not fight."""
        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            _rule(min_amount_minor=20_000_00, expires_after_hours=48)
            big = _rule(min_amount_minor=100_000_00, expires_after_hours=168)
            verdict = approvals.require_approval_for(amount_minor=150_000_00, account_id=account.id)
            assert verdict.rule.id == big.id

    def test_a_rule_never_reaches_a_private_account(self):
        """Making somebody approve spending on an account they cannot even see
        would be surveillance wearing a governance hat."""
        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            private = _joint_account(owner=amina, joint=False, policy=SharingPolicy.PRIVATE)
            _rule(scope=ApprovalScope.JOINT, min_amount_minor=20_000_00)
            assert not approvals.require_approval_for(amount_minor=999_999_00, account_id=private.id).required

    def test_a_workspace_of_one_is_never_interrogated(self):
        """There is nobody to ask. Without this, enabling a rule in a personal
        workspace would make the product interview its only user."""
        tenant = TenantFactory()
        solo = MembershipFactory(tenant=tenant)
        with tenant_scope(tenant.id, actor_id=solo.user_id):
            account = _joint_account()
            _rule(min_amount_minor=1_00)
            assert not approvals.require_approval_for(amount_minor=500_000_00, account_id=account.id).required


class TestRequestVersusFlag:
    """The distinction the whole module is built around."""

    def test_a_request_reads_as_a_decision_and_a_flag_as_a_review(self):
        tenant, amina, brian = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            rule = _rule()
            asked = approvals.request_approval(
                amount_minor=50_000_00,
                currency="KES",
                description="A sofa",
                account_id=account.id,
                rule=rule,
            )
            assert asked.kind == ApprovalKind.REQUESTED

        with tenant_scope(tenant.id, actor_id=brian.user_id):
            approvals.approve(approval=asked)
            entry = audit.timeline(subject_type="spend_approval")[0].summary
            assert "approved" in entry

    def test_flagging_an_existing_transaction_says_it_already_happened(self):
        tenant, amina, brian = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            _rule()
            category = finance_services.create_category(name="Home", kind="expense", currency="KES")
            txn = finance_services.record_expense(
                financial_account=account,
                category=category,
                amount_minor=50_000_00,
                occurred_at=timezone.now(),
                memo="A sofa",
            )
            flagged = approvals.flag_transaction(txn=txn)
            assert flagged is not None
            assert flagged.kind == ApprovalKind.FLAGGED

        with tenant_scope(tenant.id, actor_id=brian.user_id):
            approvals.approve(approval=flagged)
            entry = audit.timeline(subject_type="spend_approval")[0].summary
            assert "reviewed and accepted" in entry, "a flag is reviewed, never 'approved'"

    def test_flagging_the_same_transaction_twice_does_not_ask_twice(self):
        """Re-running an import must not re-interrogate the household."""
        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            _rule()
            category = finance_services.create_category(name="Home", kind="expense", currency="KES")
            txn = finance_services.record_expense(
                financial_account=account,
                category=category,
                amount_minor=50_000_00,
                occurred_at=timezone.now(),
                memo="A sofa",
            )
            first = approvals.flag_transaction(txn=txn)
            second = approvals.flag_transaction(txn=txn)
            assert first.id == second.id
            assert SpendApproval.objects.count() == 1

    def test_a_small_transaction_is_not_flagged_at_all(self):
        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            _rule(min_amount_minor=20_000_00)
            category = finance_services.create_category(name="Home", kind="expense", currency="KES")
            txn = finance_services.record_expense(
                financial_account=account,
                category=category,
                amount_minor=500_00,
                occurred_at=timezone.now(),
                memo="Milk",
            )
            assert approvals.flag_transaction(txn=txn) is None


class TestResolving:
    def _asked(self, tenant, amina):
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            rule = _rule()
            return approvals.request_approval(
                amount_minor=50_000_00,
                currency="KES",
                description="A sofa",
                account_id=account.id,
                rule=rule,
            )

    def test_you_cannot_approve_your_own_request(self):
        """A second pair of eyes you supply yourself is decoration."""
        tenant, amina, _ = _couple()
        approval = self._asked(tenant, amina)
        with (
            tenant_scope(tenant.id, actor_id=amina.user_id),
            pytest.raises(approvals.ApprovalError, match="defeat the point"),
        ):
            approvals.approve(approval=approval)

    def test_you_may_review_your_own_flagged_spending(self):
        """A flag is a notification. Marking it seen is not a decision about
        anybody else's money."""
        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            _rule()
            category = finance_services.create_category(name="Home", kind="expense", currency="KES")
            txn = finance_services.record_expense(
                financial_account=account,
                category=category,
                amount_minor=50_000_00,
                occurred_at=timezone.now(),
                memo="A sofa",
            )
            flagged = approvals.flag_transaction(txn=txn)
            approvals.approve(approval=flagged)
            flagged.refresh_from_db()
            assert flagged.status == ApprovalStatus.APPROVED

    def test_a_partner_can_approve(self):
        tenant, amina, brian = _couple()
        approval = self._asked(tenant, amina)
        with tenant_scope(tenant.id, actor_id=brian.user_id):
            approvals.approve(approval=approval, note="Go for it.")
            approval.refresh_from_db()
            assert approval.status == ApprovalStatus.APPROVED
            assert approval.resolved_by_label
            assert approval.comments.count() == 1

    def test_a_partner_can_decline(self):
        tenant, amina, brian = _couple()
        approval = self._asked(tenant, amina)
        with tenant_scope(tenant.id, actor_id=brian.user_id):
            approvals.decline(approval=approval, note="Not this month.")
            approval.refresh_from_db()
            assert approval.status == ApprovalStatus.DECLINED

    def test_resolving_twice_is_refused(self):
        tenant, amina, brian = _couple()
        approval = self._asked(tenant, amina)
        with tenant_scope(tenant.id, actor_id=brian.user_id):
            approvals.approve(approval=approval)
            with pytest.raises(approvals.ApprovalError, match="already"):
                approvals.decline(approval=approval)

    def test_only_the_requester_may_withdraw(self):
        tenant, amina, brian = _couple()
        approval = self._asked(tenant, amina)
        with (
            tenant_scope(tenant.id, actor_id=brian.user_id),
            pytest.raises(approvals.ApprovalError, match="who asked"),
        ):
            approvals.withdraw(approval=approval)
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            approvals.withdraw(approval=approval)
            approval.refresh_from_db()
            assert approval.status == ApprovalStatus.WITHDRAWN


class TestSuggestion:
    def test_a_suggestion_leaves_the_request_open(self):
        """ "Could you make it 30,000?" is a step in a negotiation, not a
        verdict. Resolving it would end a conversation that has not finished."""
        tenant, amina, brian = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            approval = approvals.request_approval(
                amount_minor=50_000_00,
                currency="KES",
                description="A sofa",
                account_id=account.id,
                rule=_rule(),
            )
        with tenant_scope(tenant.id, actor_id=brian.user_id):
            approvals.suggest(approval=approval, amount_minor=30_000_00)
            approval.refresh_from_db()
            assert approval.status == ApprovalStatus.PENDING
            assert approval.suggested_amount_minor == 30_000_00
            assert approval.comments.count() == 1

    def test_the_original_amount_is_kept_beside_the_suggestion(self):
        """The thread has to show what was asked as well as what came back."""
        tenant, amina, brian = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            approval = approvals.request_approval(
                amount_minor=50_000_00,
                currency="KES",
                description="A sofa",
                account_id=account.id,
                rule=_rule(),
            )
        with tenant_scope(tenant.id, actor_id=brian.user_id):
            approvals.suggest(approval=approval, amount_minor=30_000_00)
            approval.refresh_from_db()
            assert approval.amount_minor == 50_000_00


class TestExpiry:
    def test_silence_is_neither_approval_nor_refusal(self):
        """Auto-approving defeats the mechanism; auto-declining lets one
        partner veto by saying nothing. Silence means silence."""
        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            approval = approvals.request_approval(
                amount_minor=50_000_00,
                currency="KES",
                description="A sofa",
                account_id=account.id,
                rule=_rule(expires_after_hours=1),
            )
            moved = approvals.expire_pending(now=timezone.now() + timedelta(hours=2))
            assert moved == 1
            approval.refresh_from_db()
            assert approval.status == ApprovalStatus.EXPIRED
            assert approval.status not in (ApprovalStatus.APPROVED, ApprovalStatus.DECLINED)

    def test_an_expiry_is_recorded_so_nobody_wonders_if_it_was_lost(self):
        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            approvals.request_approval(
                amount_minor=50_000_00,
                currency="KES",
                description="A sofa",
                account_id=account.id,
                rule=_rule(expires_after_hours=1),
            )
            approvals.expire_pending(now=timezone.now() + timedelta(hours=2))
            assert any("Nobody answered" in e.summary for e in audit.timeline(subject_type="spend_approval"))

    def test_an_expired_request_cannot_then_be_approved(self):
        tenant, amina, brian = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            approval = approvals.request_approval(
                amount_minor=50_000_00,
                currency="KES",
                description="A sofa",
                account_id=account.id,
                rule=_rule(expires_after_hours=1),
            )
            approval.expires_at = timezone.now() - timedelta(minutes=1)
            approval.save(update_fields=["expires_at"])
        with (
            tenant_scope(tenant.id, actor_id=brian.user_id),
            pytest.raises(approvals.ApprovalError, match="expired"),
        ):
            approvals.approve(approval=approval)

    def test_a_request_within_its_window_is_untouched(self):
        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            approvals.request_approval(
                amount_minor=50_000_00,
                currency="KES",
                description="A sofa",
                account_id=account.id,
                rule=_rule(expires_after_hours=48),
            )
            assert approvals.expire_pending() == 0


class TestHistory:
    def test_every_step_lands_in_the_audit_trail(self):
        """ "Complete approval history" is the requirement. Each step is a
        separate entry, because "who agreed to this and when" is the question
        the log gets asked."""
        tenant, amina, brian = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            approval = approvals.request_approval(
                amount_minor=50_000_00,
                currency="KES",
                description="A sofa",
                account_id=account.id,
                rule=_rule(),
            )
        with tenant_scope(tenant.id, actor_id=brian.user_id):
            approvals.suggest(approval=approval, amount_minor=30_000_00)
            approvals.approve(approval=approval)
            entries = audit.timeline(subject_type="spend_approval")
            assert len(entries) == 3  # asked, suggested, approved

    def test_a_declined_request_stays_in_the_record(self):
        tenant, amina, brian = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            approval = approvals.request_approval(
                amount_minor=50_000_00,
                currency="KES",
                description="A sofa",
                account_id=account.id,
                rule=_rule(),
            )
        with tenant_scope(tenant.id, actor_id=brian.user_id):
            approvals.decline(approval=approval)
            assert len(approvals.history()) == 1


class TestComments:
    def test_a_comment_cannot_be_edited(self):
        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            approval = approvals.request_approval(
                amount_minor=50_000_00,
                currency="KES",
                description="A sofa",
                account_id=account.id,
                rule=_rule(),
            )
            note = approvals.comment(approval=approval, body="What colour?")
            note.body = "Something else"
            with pytest.raises(ValueError, match="append-only"):
                note.save()

    def test_an_empty_comment_is_refused(self):
        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _joint_account()
            approval = approvals.request_approval(
                amount_minor=50_000_00,
                currency="KES",
                description="A sofa",
                account_id=account.id,
                rule=_rule(),
            )
            with pytest.raises(approvals.ApprovalError):
                approvals.comment(approval=approval, body="   ")


class TestIsolation:
    def test_one_household_cannot_see_another_s_approvals(self):
        first, amina, _ = _couple()
        second, other, _ = _couple()
        with tenant_scope(first.id, actor_id=amina.user_id):
            approvals.request_approval(
                amount_minor=50_000_00,
                currency="KES",
                description="Ours",
                account_id=_joint_account().id,
                rule=_rule(),
            )
        with tenant_scope(second.id, actor_id=other.user_id):
            assert approvals.history() == []


class TestApi:
    def test_the_full_conversation_over_http(self, tenant_context):
        """Ask, suggest, comment, approve — the thread a couple actually has."""
        membership, client = tenant_context
        partner = MembershipFactory(tenant_id=membership.tenant_id)
        with tenant_scope(membership.tenant_id, actor_id=membership.user_id):
            account = _joint_account()
            _rule(min_amount_minor=20_000_00)

        created = client.post(
            "/api/v1/household/approvals/",
            {
                "amount_minor": 50_000_00,
                "currency": "KES",
                "description": "A sofa",
                "financial_account_id": str(account.id),
            },
            format="json",
        )
        assert created.status_code == 201, created.data
        assert created.data["kind"] == "requested"
        approval_id = created.data["id"]

        # The requester cannot approve their own.
        self_approve = client.post(
            f"/api/v1/household/approvals/{approval_id}/", {"action": "approve"}, format="json"
        )
        assert self_approve.status_code == 400
        assert "defeat the point" in self_approve.data["detail"]

        with tenant_scope(membership.tenant_id, actor_id=partner.user_id):
            from apps.household.models import SpendApproval

            approvals.suggest(approval=SpendApproval.objects.get(id=approval_id), amount_minor=30_000_00)
            approvals.approve(approval=SpendApproval.objects.get(id=approval_id))

        listed = client.get("/api/v1/household/approvals/")
        assert listed.status_code == 200
        row = listed.data[0]
        assert row["status"] == "approved"
        assert row["suggested_amount_minor"] == 30_000_00
        assert len(row["comments"]) == 1

    def test_creating_a_threshold_over_http(self, tenant_context):
        _, client = tenant_context
        resp = client.post(
            "/api/v1/household/approval-rules/",
            {"min_amount_minor": 20_000_00, "currency": "KES"},
            format="json",
        )
        assert resp.status_code == 201
        assert client.get("/api/v1/household/approval-rules/").data[0]["min_amount_minor"] == 20_000_00

    def test_a_zero_threshold_is_refused(self, tenant_context):
        _, client = tenant_context
        resp = client.post("/api/v1/household/approval-rules/", {"min_amount_minor": 0}, format="json")
        assert resp.status_code == 400

    def test_an_unknown_action_is_refused(self, tenant_context):
        membership, client = tenant_context
        with tenant_scope(membership.tenant_id, actor_id=membership.user_id):
            MembershipFactory(tenant_id=membership.tenant_id)
            account = _joint_account()
            approval = approvals.request_approval(
                amount_minor=50_000_00,
                currency="KES",
                description="A sofa",
                account_id=account.id,
                rule=_rule(),
            )
        resp = client.post(f"/api/v1/household/approvals/{approval.id}/", {"action": "vibes"}, format="json")
        assert resp.status_code == 400
