"""The contribution engine.

Two properties carry the weight, and both are the kind that produce a complaint
about fairness rather than a stack trace:

  * the parts always sum to the whole — a split that loses a cent a month is
    a shared pot that is quietly short for ever;
  * an unknown input never becomes zero — treating a missing income as nothing
    hands the entire bill to the other partner and presents it as arithmetic.

The maths is tested without a database, because it does not need one.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.household.contribution_math import (
    ContributionMode,
    Contributor,
    allocate,
    assess_fairness,
    compute_plan,
)

# --------------------------------------------------------------------- maths
# No database: these are pure functions and should stay that way.


def _who(name, **kwargs):
    return Contributor(membership_id=name, display_name=name, **kwargs)


class TestAllocation:
    """`allocate` is the reason the totals are trustworthy."""

    def test_parts_sum_to_the_whole_when_it_does_not_divide(self):
        # 100.00 three ways. Naive rounding gives 33.33 each and loses a cent.
        parts = allocate(10000, [Decimal(1), Decimal(1), Decimal(1)])
        assert sum(parts) == 10000
        assert sorted(parts) == [3333, 3333, 3334]

    @pytest.mark.parametrize("total", [1, 7, 99, 100, 3333, 999999, 1_000_000_01])
    @pytest.mark.parametrize("n", [2, 3, 4, 7])
    def test_never_loses_or_invents_a_unit(self, total, n):
        assert sum(allocate(total, [Decimal(1)] * n)) == total

    def test_uneven_weights_still_sum_exactly(self):
        parts = allocate(10000, [Decimal("0.6"), Decimal("0.4")])
        assert sum(parts) == 10000
        assert parts == [6000, 4000]

    def test_the_leftover_goes_somewhere_deterministic(self):
        """Same inputs, same answer. A cent that moves between partners
        depending on dict ordering is reported as a fairness bug."""
        weights = [Decimal(1), Decimal(1), Decimal(1)]
        assert allocate(10000, weights) == allocate(10000, weights) == allocate(10000, weights)

    def test_zero_weights_do_not_divide_by_zero(self):
        assert allocate(1000, [Decimal(0), Decimal(0)]) == [0, 0]


class TestEqual:
    def test_splits_down_the_middle(self):
        plan = compute_plan(
            mode=ContributionMode.EQUAL,
            target_minor=200000,
            currency="KES",
            contributors=[_who("amina"), _who("brian")],
        )
        assert plan.is_complete
        assert [c.amount_minor for c in plan.contributions] == [100000, 100000]
        assert plan.allocated_minor == plan.target_minor

    def test_needs_no_other_information(self):
        """Equal is the mode that works before a household has told us
        anything, which is why it is the one people start on."""
        plan = compute_plan(
            mode=ContributionMode.EQUAL,
            target_minor=99999,
            currency="KES",
            contributors=[_who("a"), _who("b"), _who("c")],
        )
        assert plan.is_complete
        assert plan.allocated_minor == 99999


class TestPercentage:
    def test_uses_the_agreed_shares(self):
        plan = compute_plan(
            mode=ContributionMode.PERCENTAGE,
            target_minor=100000,
            currency="KES",
            contributors=[
                _who("amina", share=Decimal("0.6")),
                _who("brian", share=Decimal("0.4")),
            ],
        )
        assert [c.amount_minor for c in plan.contributions] == [60000, 40000]

    def test_refuses_rather_than_inventing_a_missing_share(self):
        plan = compute_plan(
            mode=ContributionMode.PERCENTAGE,
            target_minor=100000,
            currency="KES",
            contributors=[_who("amina", share=Decimal("0.6")), _who("brian")],
        )
        assert not plan.is_complete
        assert "brian" in plan.blockers[0]
        assert plan.contributions == ()

    def test_shares_that_do_not_total_100_are_scaled_and_flagged(self):
        """55/40 is a household that agreed roughly and wants the pot funded,
        not a validation error — but they should be told."""
        plan = compute_plan(
            mode=ContributionMode.PERCENTAGE,
            target_minor=100000,
            currency="KES",
            contributors=[
                _who("amina", share=Decimal("0.55")),
                _who("brian", share=Decimal("0.40")),
            ],
        )
        assert plan.is_complete
        assert plan.allocated_minor == 100000, "the pot is still fully funded"
        assert any("not 100%" in n for n in plan.notes)


class TestFixed:
    def test_uses_the_stated_amounts(self):
        plan = compute_plan(
            mode=ContributionMode.FIXED,
            target_minor=100000,
            currency="KES",
            contributors=[
                _who("amina", fixed_minor=70000),
                _who("brian", fixed_minor=30000),
            ],
        )
        assert plan.is_complete
        assert plan.shortfall_minor == 0

    def test_reports_the_gap_when_the_amounts_do_not_cover_the_costs(self):
        """The single most useful thing this mode can tell a household."""
        plan = compute_plan(
            mode=ContributionMode.FIXED,
            target_minor=100000,
            currency="KES",
            contributors=[
                _who("amina", fixed_minor=40000),
                _who("brian", fixed_minor=30000),
            ],
        )
        assert plan.shortfall_minor == 30000
        assert any("unfunded" in n for n in plan.notes)

    def test_reports_a_surplus_too(self):
        plan = compute_plan(
            mode=ContributionMode.FIXED,
            target_minor=50000,
            currency="KES",
            contributors=[_who("a", fixed_minor=40000), _who("b", fixed_minor=30000)],
        )
        assert plan.shortfall_minor == -20000
        assert any("surplus" in n for n in plan.notes)


class TestIncomeBased:
    def test_splits_in_proportion_to_income(self):
        plan = compute_plan(
            mode=ContributionMode.INCOME_BASED,
            target_minor=100000,
            currency="KES",
            contributors=[
                _who("amina", monthly_income_minor=750000),
                _who("brian", monthly_income_minor=250000),
            ],
        )
        assert [c.amount_minor for c in plan.contributions] == [75000, 25000]

    def test_an_unknown_income_blocks_rather_than_counting_as_zero(self):
        """The property this whole design exists to protect. Zero would hand
        the entire bill to the other partner and call it fair."""
        plan = compute_plan(
            mode=ContributionMode.INCOME_BASED,
            target_minor=100000,
            currency="KES",
            contributors=[
                _who("amina", monthly_income_minor=750000),
                _who("brian"),  # income unknown
            ],
        )
        assert not plan.is_complete
        assert plan.contributions == ()
        assert "brian" in plan.blockers[0]

    def test_a_household_with_no_income_is_blocked_not_divided_by_zero(self):
        plan = compute_plan(
            mode=ContributionMode.INCOME_BASED,
            target_minor=100000,
            currency="KES",
            contributors=[
                _who("a", monthly_income_minor=0),
                _who("b", monthly_income_minor=0),
            ],
        )
        assert not plan.is_complete

    def test_the_basis_explains_the_number(self):
        """ "Why am I paying 75%" is the question the figure always provokes."""
        plan = compute_plan(
            mode=ContributionMode.INCOME_BASED,
            target_minor=100000,
            currency="KES",
            contributors=[
                _who("amina", monthly_income_minor=750000),
                _who("brian", monthly_income_minor=250000),
            ],
        )
        assert "75% of household income" in plan.contributions[0].basis


class TestGuards:
    def test_a_household_of_nobody_is_blocked(self):
        plan = compute_plan(mode=ContributionMode.EQUAL, target_minor=1000, currency="KES", contributors=[])
        assert not plan.is_complete

    def test_a_negative_pot_is_refused(self):
        plan = compute_plan(
            mode=ContributionMode.EQUAL,
            target_minor=-5000,
            currency="KES",
            contributors=[_who("a"), _who("b")],
        )
        assert not plan.is_complete

    def test_a_zero_pot_is_a_valid_answer_not_an_error(self):
        """A household with no shared costs yet still has a valid split."""
        plan = compute_plan(
            mode=ContributionMode.EQUAL,
            target_minor=0,
            currency="KES",
            contributors=[_who("a"), _who("b")],
        )
        assert plan.is_complete
        assert plan.allocated_minor == 0


class TestFairness:
    def _plan(self):
        return compute_plan(
            mode=ContributionMode.EQUAL,
            target_minor=100000,
            currency="KES",
            contributors=[_who("amina"), _who("brian")],
        )

    def test_says_so_when_the_household_is_square(self):
        """A household that is balanced deserves to be told, not shown a
        blank screen."""
        result = assess_fairness(plan=self._plan(), actuals_minor={"amina": 50000, "brian": 50000})
        assert result.is_balanced
        assert "match" in result.summary

    def test_small_differences_are_not_flagged(self):
        """Nobody transfers an exact share. A product that flags three
        shillings gets muted within a week."""
        result = assess_fairness(plan=self._plan(), actuals_minor={"amina": 50000, "brian": 49800})
        assert result.is_balanced

    def test_a_real_gap_is_reported_with_both_directions(self):
        result = assess_fairness(plan=self._plan(), actuals_minor={"amina": 80000, "brian": 20000})
        assert not result.is_balanced
        assert "brian is 300.00 under" in result.summary
        assert "amina is 300.00 over" in result.summary

    def test_a_missing_contributor_reads_as_zero_paid_not_as_absent(self):
        result = assess_fairness(plan=self._plan(), actuals_minor={"amina": 100000})
        brian = next(line for line in result.lines if line.membership_id == "brian")
        assert brian.actual_minor == 0
        assert brian.delta_minor == -50000

    def test_the_wording_describes_rather_than_blames(self):
        """This text lands in the middle of somebody's relationship. It reports
        two numbers and their difference; what that means is theirs to decide."""
        summary = assess_fairness(plan=self._plan(), actuals_minor={"amina": 80000, "brian": 20000}).summary
        for loaded in ("should", "failed", "owes", "must", "unfair", "behind"):
            assert loaded not in summary.lower()
