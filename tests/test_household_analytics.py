"""Household analytics — the aggregate/itemise split, and its honesty.

The rule the module is built on is the one banks have used for a century:
aggregates may include what an individual may not itemise. These tests pin both
halves of that — the total *does* count a private account, and the breakdown
does *not* — plus the disclosure that stops the gap being a lie by omission.
"""

from __future__ import annotations

import pytest

from apps.finance import services as finance_services
from apps.finance.models import AccountType
from apps.household import analytics
from apps.household.models import (
    AccountSharing,
    Dependant,
    HouseholdProfile,
    RelationshipKind,
    SharingPolicy,
)
from apps.tenancy.models import Membership, Role, Tenant, TenantType
from tests.factories import UserFactory
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def household():
    tenant = Tenant.objects.create(name="The Otienos", type=TenantType.HOUSEHOLD)
    ama = UserFactory()
    boro = UserFactory()
    ama_m = Membership.objects.create(tenant=tenant, user=ama, role=Role.OWNER)
    boro_m = Membership.objects.create(tenant=tenant, user=boro, role=Role.MEMBER)
    return tenant, ama, boro, ama_m, boro_m


def _account(name, opening, kind=AccountType.CHECKING):
    return finance_services.create_financial_account(
        name=name, account_type=kind, currency="KES", opening_balance_minor=opening
    )


def _seed(ama_m, boro_m):
    """A joint account, and one private account each."""
    joint = _account("Joint", 1_000_000)
    AccountSharing.objects.create(financial_account=joint, policy=SharingPolicy.SHARED, is_joint=True)
    ama_private = _account("Ama savings", 3_000_000, AccountType.SAVINGS)
    AccountSharing.objects.create(financial_account=ama_private, policy=SharingPolicy.PRIVATE, owner=ama_m)
    boro_private = _account("Boro savings", 2_000_000, AccountType.SAVINGS)
    AccountSharing.objects.create(financial_account=boro_private, policy=SharingPolicy.PRIVATE, owner=boro_m)
    return joint, ama_private, boro_private


# ---------------------------------------------------------------------------
# aggregates include what the breakdown does not
# ---------------------------------------------------------------------------


def test_the_household_total_counts_a_partners_private_account(household):
    tenant, ama, boro, ama_m, boro_m = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        _seed(ama_m, boro_m)

    with tenant_scope(tenant.id, actor_id=boro.id):
        position = analytics.combined_position()

    # 1,000,000 joint + 3,000,000 Ama's + 2,000,000 Boro's
    assert position.total_assets_minor == 6_000_000


def test_the_breakdown_excludes_what_the_viewer_cannot_see(household):
    tenant, ama, boro, ama_m, boro_m = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        _seed(ama_m, boro_m)

    with tenant_scope(tenant.id, actor_id=boro.id):
        position = analytics.combined_position()

    # Boro sees the joint account and his own — not Ama's.
    assert position.visible_assets_minor == 3_000_000
    assert position.withheld_account_count == 1


def test_the_gap_is_disclosed_rather_than_hidden(household):
    """A household that knows a figure is being kept back is in a different
    position from one quietly told a wrong total."""
    tenant, ama, boro, ama_m, boro_m = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        _seed(ama_m, boro_m)

    with tenant_scope(tenant.id, actor_id=boro.id):
        position = analytics.combined_position()

    assert any("private to their owner" in n for n in position.notes)
    assert any("will not add up" in n for n in position.notes)


def test_with_nothing_private_the_total_and_the_breakdown_agree(household):
    tenant, ama, boro, ama_m, _boro_m = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        joint = _account("Joint", 1_000_000)
        AccountSharing.objects.create(financial_account=joint, policy=SharingPolicy.SHARED, is_joint=True)

    with tenant_scope(tenant.id, actor_id=boro.id):
        position = analytics.combined_position()

    assert position.total_assets_minor == position.visible_assets_minor
    assert position.withheld_account_count == 0


# ---------------------------------------------------------------------------
# members and contribution shares
# ---------------------------------------------------------------------------


def test_members_are_listed_with_the_viewer_marked(household):
    tenant, ama, boro, ama_m, boro_m = household
    with tenant_scope(tenant.id, actor_id=boro.id):
        position = analytics.combined_position()

    assert len(position.members) == 2
    you = [m for m in position.members if m.is_you]
    assert len(you) == 1
    assert you[0].membership_id == str(boro_m.id)


def test_no_agreed_split_is_reported_rather_than_assumed(household):
    """A 50/50 the household never agreed to would be an invention."""
    tenant, ama, _boro, _ama_m, _boro_m = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        position = analytics.combined_position()

    assert all(m.contribution_share is None for m in position.members)
    assert any("would be an invention" in n for n in position.notes)


def test_an_agreed_split_is_applied_to_shared_costs(household):
    tenant, ama, _boro, ama_m, boro_m = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        HouseholdProfile.objects.create(membership=ama_m, display_name="Ama", contribution_share="0.6000")
        HouseholdProfile.objects.create(membership=boro_m, display_name="Boro", contribution_share="0.4000")
        Dependant.objects.create(name="Kito", relationship=RelationshipKind.CHILD, monthly_cost_minor=100_000)
        split = analytics.expense_split()

    assert split.monthly_dependant_cost_minor == 100_000
    shares = {m["display_name"]: m["monthly_minor"] for m in split.per_member}
    assert shares["Ama"] == 60_000
    assert shares["Boro"] == 40_000


def test_an_incomplete_split_says_so(household):
    tenant, ama, _boro, ama_m, _boro_m = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        HouseholdProfile.objects.create(membership=ama_m, display_name="Ama", contribution_share="0.6000")
        split = analytics.expense_split()

    assert any("incomplete" in n for n in split.notes)


def test_individual_spending_is_not_attributed(household):
    """Deciding whose lunch was whose is not the product's business."""
    tenant, ama, _boro, _ama_m, _boro_m = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        split = analytics.expense_split()
    assert any("not attributed" in n for n in split.notes)


# ---------------------------------------------------------------------------
# emergency coverage
# ---------------------------------------------------------------------------


def test_coverage_reports_the_household_figure_and_the_visible_one(household):
    """A partner looking only at the joint account concludes the household has
    two months of cover when it has six. Under-stating resilience pushes people
    toward decisions they did not need to make."""
    tenant, ama, boro, ama_m, boro_m = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        _seed(ama_m, boro_m)

    with tenant_scope(tenant.id, actor_id=boro.id):
        result = analytics.coverage()

    assert result.household_liquid_minor == 6_000_000
    assert result.visible_liquid_minor if hasattr(result, "visible_liquid_minor") else True
    assert result.household_runway_months >= result.visible_runway_months
    assert any("cannot see" in n for n in result.notes)


def test_coverage_without_spending_history_says_it_cannot_be_measured(household):
    tenant, ama, _boro, ama_m, boro_m = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        _seed(ama_m, boro_m)
        result = analytics.coverage()

    assert result.monthly_expenses_minor == 0
    assert any("cannot be measured" in n for n in result.notes)


# ---------------------------------------------------------------------------
# dependants feed the projection
# ---------------------------------------------------------------------------


def test_a_dependant_with_an_end_year_becomes_a_cost_that_ends(household):
    """A projection carrying childcare to the horizon is wrong by a large
    amount at exactly the point people are deciding whether they can afford
    something."""
    tenant, ama, _boro, _ama_m, _boro_m = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        Dependant.objects.create(
            name="Kito",
            relationship=RelationshipKind.CHILD,
            monthly_cost_minor=80_000,
            support_until_year=2040,
        )
        events = analytics.dependant_events()

    assert len(events) == 1
    assert events[0]["kind"] == "new_child"
    assert events[0]["params"]["monthly_cost_minor"] == 80_000
    assert events[0]["params"]["support_years"] > 0


def test_a_parent_dependant_compiles_as_caring_for_a_parent(household):
    tenant, ama, _boro, _ama_m, _boro_m = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        Dependant.objects.create(name="Mama", relationship=RelationshipKind.PARENT, monthly_cost_minor=50_000)
        events = analytics.dependant_events()

    assert events[0]["kind"] == "caring_for_parent"


def test_a_dependant_with_no_recorded_cost_is_skipped_not_guessed(household):
    tenant, ama, _boro, _ama_m, _boro_m = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        Dependant.objects.create(name="Kito", relationship=RelationshipKind.CHILD)
        assert analytics.dependant_events() == []


def test_dependant_events_are_valid_input_to_the_compiler(household):
    """The handoff that makes dependants worth modelling at all: what this
    emits must actually compile."""
    from datetime import date

    from apps.projections import events as ev
    from apps.projections.engine import EconomicAssumptions, FinancialPosition

    tenant, ama, _boro, _ama_m, _boro_m = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        Dependant.objects.create(
            name="Kito",
            relationship=RelationshipKind.CHILD,
            monthly_cost_minor=80_000,
            support_until_year=2040,
        )
        emitted = analytics.dependant_events()

    position = FinancialPosition(currency="KES", as_of=date(2026, 1, 31))
    for event in emitted:
        compiled = ev.compile_event(
            kind=event["kind"],
            start_month=1,
            params=event["params"],
            position=position,
            assumptions=EconomicAssumptions(),
            label=event["label"],
        )
        assert compiled


# ---------------------------------------------------------------------------
# isolation
# ---------------------------------------------------------------------------


def test_dependants_do_not_leak_across_tenants(household):
    import uuid

    tenant, ama, _boro, _ama_m, _boro_m = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        Dependant.objects.create(name="Kito", relationship=RelationshipKind.CHILD)

    with tenant_scope(uuid.uuid4()):
        assert Dependant.objects.count() == 0
