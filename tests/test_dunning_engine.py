"""The dunning engine: scheduling, execution, recovery, suspension.

Time is driven explicitly through the `now` parameter rather than by patching
the clock — the engine's whole job is to do things on a schedule, so a test
that cannot move time cannot test it.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.billing import dunning
from apps.billing.dunning_models import (
    DunningAttempt,
    DunningAttemptKind,
    DunningAttemptOutcome,
    DunningCase,
    DunningCaseStatus,
    DunningPolicy,
)
from apps.billing.models import (
    BillingInterval,
    Payment,
    PaymentMethod,
    PaymentMethodKind,
    PaymentStatus,
    Plan,
    PlanTier,
    Subscription,
    SubscriptionStatus,
)
from apps.tenancy.models import Tenant
from tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


def _paid_plan(price=1000) -> Plan:
    return Plan.objects.create(
        tier=PlanTier.PLUS,
        name="Plus",
        price_minor=price,
        currency="USD",
        interval=BillingInterval.MONTHLY,
    )


def _subscription(tenant_id, plan=None, status=SubscriptionStatus.ACTIVE) -> Subscription:
    return Subscription.objects.create(
        tenant_id=tenant_id, plan=plan or _paid_plan(), status=status, provider="stripe"
    )


def _method(tenant_id) -> PaymentMethod:
    return PaymentMethod.objects.create(
        tenant_id=tenant_id,
        kind=PaymentMethodKind.CARD,
        is_default=True,
        brand="visa",
        last4="4242",
        provider="stripe",
        provider_ref="pm_test",
    )


def _policy(**kwargs) -> DunningPolicy:
    defaults = dict(
        name="Test policy",
        retry_offsets_days=[1, 3],
        reminder_offsets_days=[1],
        grace_period_days=5,
        suspend_after_days=7,
        abandon_after_days=14,
        is_default=True,
    )
    defaults.update(kwargs)
    return DunningPolicy.objects.create(**defaults)


# -------------------------------------------------------------------- policies
def test_default_policy_is_created_on_demand():
    """A fresh install must recover payments without anyone configuring it."""
    policy = dunning.ensure_default_policy()
    assert policy.is_default
    assert policy.retries


def test_only_one_policy_can_be_the_default():
    from django.db import IntegrityError

    _policy()
    with pytest.raises(IntegrityError):
        _policy(name="Second default")


def test_plan_specific_policy_beats_the_default():
    plan = _paid_plan()
    _policy()
    specific = DunningPolicy.objects.create(name="Enterprise patience", grace_period_days=30)
    specific.applies_to_plans.add(plan)

    sub = _subscription(uuid.uuid4(), plan=plan)
    assert dunning.resolve_policy(subscription=sub) == specific


def test_suspension_before_grace_ends_is_rejected():
    policy = DunningPolicy(name="Impossible", grace_period_days=14, suspend_after_days=7)
    with pytest.raises(dunning.DunningError):
        dunning.validate_policy(policy)


def test_abandonment_before_suspension_is_rejected():
    policy = DunningPolicy(
        name="Impossible", grace_period_days=5, suspend_after_days=10, abandon_after_days=8
    )
    with pytest.raises(dunning.DunningError):
        dunning.validate_policy(policy)


# ----------------------------------------------------------------------- cases
def test_opening_a_case_writes_the_whole_schedule_up_front():
    """The schedule must be inspectable: 'what happens next, and when'."""
    _policy()
    sub = _subscription(uuid.uuid4())
    case = dunning.open_case(subscription=sub, failure_reason="card_declined")

    kinds = list(DunningAttempt.objects.filter(case=case).values_list("kind", flat=True).order_by("kind"))
    assert kinds.count(DunningAttemptKind.RETRY) == 2
    assert kinds.count(DunningAttemptKind.REMINDER_EMAIL) == 1
    assert kinds.count(DunningAttemptKind.SUSPEND) == 1
    assert kinds.count(DunningAttemptKind.ABANDON) == 1


def test_opening_a_case_twice_returns_the_same_case():
    """Two failure webhooks must not start two reminder sequences."""
    _policy()
    sub = _subscription(uuid.uuid4())
    first = dunning.open_case(subscription=sub)
    second = dunning.open_case(subscription=sub)

    assert first.id == second.id
    assert DunningCase.objects.filter(subscription=sub).count() == 1


def test_a_case_records_the_grace_and_suspension_deadlines():
    _policy(grace_period_days=5, suspend_after_days=7)
    sub = _subscription(uuid.uuid4())
    now = timezone.now()
    case = dunning.open_case(subscription=sub, now=now)

    assert abs((case.grace_ends_at - (now + timedelta(days=5))).total_seconds()) < 2
    assert abs((case.suspend_at - (now + timedelta(days=7))).total_seconds()) < 2


def test_policy_change_does_not_rewrite_an_open_case():
    """A customer keeps the terms they entered dunning under."""
    policy = _policy(suspend_after_days=7)
    sub = _subscription(uuid.uuid4())
    case = dunning.open_case(subscription=sub)
    original = case.suspend_at

    policy.suspend_after_days = 60
    policy.save(update_fields=["suspend_after_days"])

    case.refresh_from_db()
    assert case.suspend_at == original


# ------------------------------------------------------------------- execution
def test_nothing_runs_before_it_is_due():
    _policy()
    sub = _subscription(uuid.uuid4())
    dunning.open_case(subscription=sub)
    assert list(dunning.due_attempts(now=timezone.now())) == []


def test_a_successful_retry_recovers_the_case_and_restores_access():
    membership = MembershipFactory()
    tenant_id = membership.tenant_id
    _policy()
    _method(tenant_id)
    sub = _subscription(tenant_id, status=SubscriptionStatus.PAST_DUE)
    case = dunning.open_case(subscription=sub)

    dunning.run_due_attempts(now=timezone.now() + timedelta(days=1, hours=1))

    case.refresh_from_db()
    sub.refresh_from_db()
    assert case.status == DunningCaseStatus.RECOVERED
    assert sub.status == SubscriptionStatus.ACTIVE
    assert Tenant.objects.get(id=tenant_id).is_active


def test_recovery_cancels_the_remaining_schedule():
    """A customer who paid on day 1 must not be suspended on day 7."""
    membership = MembershipFactory()
    _policy()
    _method(membership.tenant_id)
    sub = _subscription(membership.tenant_id)
    case = dunning.open_case(subscription=sub)

    dunning.run_due_attempts(now=timezone.now() + timedelta(days=1, hours=1))

    remaining = DunningAttempt.objects.filter(case=case, outcome=DunningAttemptOutcome.SCHEDULED).count()
    assert remaining == 0


def test_a_retry_without_a_payment_method_is_skipped_not_failed():
    _policy()
    sub = _subscription(uuid.uuid4())
    case = dunning.open_case(subscription=sub)

    summary = dunning.run_due_attempts(now=timezone.now() + timedelta(days=1, hours=1))

    assert summary["skipped"] >= 1
    case.refresh_from_db()
    assert case.status == DunningCaseStatus.OPEN


def test_suspension_deactivates_the_workspace_without_deleting_anything():
    membership = MembershipFactory()
    tenant_id = membership.tenant_id
    _policy()
    sub = _subscription(tenant_id)
    case = dunning.open_case(subscription=sub)

    dunning.run_due_attempts(now=timezone.now() + timedelta(days=7, hours=1))

    case.refresh_from_db()
    sub.refresh_from_db()
    assert case.status == DunningCaseStatus.SUSPENDED
    assert sub.status == SubscriptionStatus.PAST_DUE
    assert not Tenant.objects.get(id=tenant_id).is_active
    # The workspace itself survives — a customer who pays on day 30 gets it back.
    assert Tenant.objects.filter(id=tenant_id).exists()


def test_abandonment_cancels_the_subscription():
    membership = MembershipFactory()
    _policy()
    sub = _subscription(membership.tenant_id)
    case = dunning.open_case(subscription=sub)

    dunning.run_due_attempts(now=timezone.now() + timedelta(days=14, hours=1))

    case.refresh_from_db()
    sub.refresh_from_db()
    assert case.status == DunningCaseStatus.ABANDONED
    assert sub.status == SubscriptionStatus.CANCELED


def test_executing_an_attempt_twice_is_a_no_op():
    """Two workers on the same sweep must not send two reminders."""
    _policy()
    sub = _subscription(uuid.uuid4())
    case = dunning.open_case(subscription=sub)
    attempt = DunningAttempt.objects.filter(case=case, kind=DunningAttemptKind.REMINDER_EMAIL).first()
    later = timezone.now() + timedelta(days=1, hours=1)

    first = dunning.execute_attempt(attempt=attempt, now=later)
    executed_at = first.executed_at
    second = dunning.execute_attempt(attempt=attempt, now=later + timedelta(hours=1))

    assert second.executed_at == executed_at


def test_attempts_on_a_closed_case_are_cancelled_not_run():
    _policy()
    sub = _subscription(uuid.uuid4())
    case = dunning.open_case(subscription=sub)
    attempt = DunningAttempt.objects.filter(case=case, kind=DunningAttemptKind.SUSPEND).first()

    dunning.close_case(case=case, status=DunningCaseStatus.CANCELLED, note="Refunded instead")
    case.refresh_from_db()
    result = dunning.execute_attempt(attempt=attempt, now=timezone.now() + timedelta(days=8))

    assert result.outcome == DunningAttemptOutcome.CANCELLED
    sub.refresh_from_db()
    assert sub.status == SubscriptionStatus.ACTIVE


# -------------------------------------------------------------------- webhooks
def test_a_failed_payment_opens_a_case():
    _policy()
    tenant_id = uuid.uuid4()
    sub = _subscription(tenant_id)
    payment = Payment.objects.create(
        tenant_id=tenant_id,
        subscription=sub,
        amount_minor=1000,
        currency="USD",
        status=PaymentStatus.FAILED,
        provider="stripe",
        failure_reason="card_declined",
    )

    case = dunning.on_payment_failed(payment=payment)
    assert case is not None
    assert case.last_failure_reason == "card_declined"


def test_a_free_plan_failure_opens_no_case():
    """There is nothing to collect, so there is nothing to chase."""
    _policy()
    free = Plan.objects.create(
        tier=PlanTier.FREE,
        name="Free",
        price_minor=0,
        currency="USD",
        interval=BillingInterval.MONTHLY,
    )
    tenant_id = uuid.uuid4()
    sub = _subscription(tenant_id, plan=free)
    payment = Payment.objects.create(
        tenant_id=tenant_id,
        subscription=sub,
        amount_minor=0,
        currency="USD",
        status=PaymentStatus.FAILED,
        provider="stripe",
    )
    assert dunning.on_payment_failed(payment=payment) is None


def test_self_service_payment_closes_an_open_case():
    """Recovery is not only something the retry schedule can achieve."""
    membership = MembershipFactory()
    tenant_id = membership.tenant_id
    _policy()
    sub = _subscription(tenant_id, status=SubscriptionStatus.PAST_DUE)
    case = dunning.open_case(subscription=sub)

    payment = Payment.objects.create(
        tenant_id=tenant_id,
        subscription=sub,
        amount_minor=1000,
        currency="USD",
        status=PaymentStatus.SUCCEEDED,
        provider="stripe",
    )
    dunning.on_payment_succeeded(payment=payment)

    case.refresh_from_db()
    sub.refresh_from_db()
    assert case.status == DunningCaseStatus.RECOVERED
    assert sub.status == SubscriptionStatus.ACTIVE
    assert Tenant.objects.get(id=tenant_id).is_active


def test_payment_on_a_suspended_case_restores_access():
    membership = MembershipFactory()
    tenant_id = membership.tenant_id
    _policy()
    sub = _subscription(tenant_id)
    dunning.open_case(subscription=sub)
    dunning.run_due_attempts(now=timezone.now() + timedelta(days=7, hours=1))
    assert not Tenant.objects.get(id=tenant_id).is_active

    payment = Payment.objects.create(
        tenant_id=tenant_id,
        subscription=sub,
        amount_minor=1000,
        currency="USD",
        status=PaymentStatus.SUCCEEDED,
        provider="stripe",
    )
    dunning.on_payment_succeeded(payment=payment)

    assert Tenant.objects.get(id=tenant_id).is_active


def test_a_suspended_case_still_progresses_to_abandonment():
    """Regression: suspension is a step in recovery, not the end of it.

    An earlier version filtered the due-attempt sweep on status == OPEN, so
    setting a case to SUSPENDED stranded it forever — the account lost access
    but the subscription was never cancelled and the case never resolved.
    """
    membership = MembershipFactory()
    _policy()
    sub = _subscription(membership.tenant_id)
    case = dunning.open_case(subscription=sub)

    dunning.run_due_attempts(now=timezone.now() + timedelta(days=7, hours=1))
    case.refresh_from_db()
    assert case.status == DunningCaseStatus.SUSPENDED

    dunning.run_due_attempts(now=timezone.now() + timedelta(days=14, hours=1))
    case.refresh_from_db()
    assert case.status == DunningCaseStatus.ABANDONED


def test_no_second_case_opens_while_one_is_suspended():
    _policy()
    sub = _subscription(MembershipFactory().tenant_id)
    first = dunning.open_case(subscription=sub)
    dunning.run_due_attempts(now=timezone.now() + timedelta(days=7, hours=1))

    assert dunning.open_case(subscription=sub).id == first.id
    assert DunningCase.objects.filter(subscription=sub).count() == 1
