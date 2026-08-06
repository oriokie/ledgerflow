"""Who pays what into the shared pot — the arithmetic, with no database.

Split from `contributions.py` so the rules can be read and tested without a
household, a tenant or a migration. Everything here is a pure function over
plain values.

The four modes exist because couples genuinely divide costs four different
ways, and a product that offers one is telling three-quarters of its users
they are doing it wrong:

``EQUAL``          down the middle, regardless of what anyone earns. Common
                   among partners with similar incomes, and the mode people
                   reach for first because it needs no conversation.
``PERCENTAGE``     an agreed split — 60/40, 70/30. The mode couples land on
                   after having the conversation once.
``FIXED``          each person pays a stated amount. Used when one partner's
                   income is irregular and a percentage would swing month to
                   month, and by people who simply prefer a standing order.
``INCOME_BASED``   shares derived from what each person actually earns, so the
                   split re-balances itself when a salary changes. The fairest
                   in principle and the one nobody maintains by hand, which is
                   precisely why it should be computed.

Two rules run through all of them.

**The parts must sum to the whole.** Three people splitting 100.00 equally is
not 33.33 each; that is 99.99 and a shared pot that is quietly one cent short
every month. Allocation uses the largest-remainder method so the total is
always exact, and the cent goes somewhere deterministic rather than to whoever
the floating-point gods favour.

**Unknowable is not zero.** If a partner's income is unknown, an income-based
split cannot be computed — and saying so is the correct output. Substituting
zero would silently hand the entire bill to the other person and present it as
arithmetic. Every mode can return an incomplete plan, and incomplete plans
carry the reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class ContributionMode(StrEnum):
    EQUAL = "equal"
    PERCENTAGE = "percentage"
    FIXED = "fixed"
    INCOME_BASED = "income_based"


@dataclass(frozen=True, slots=True)
class Contributor:
    """One person's inputs to the split.

    Every field beyond the identity is optional, because which ones matter
    depends on the mode — and a contributor missing the field their mode needs
    is the case that produces an honest incomplete plan rather than a wrong
    complete one.
    """

    membership_id: str
    display_name: str
    #: Normalised to a month. None means "we do not know", never "nothing".
    monthly_income_minor: int | None = None
    #: The stated amount, for FIXED.
    fixed_minor: int | None = None
    #: The agreed fraction, for PERCENTAGE. 0.6 for 60%.
    share: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Contribution:
    membership_id: str
    display_name: str
    amount_minor: int
    #: This person's fraction of the total, as actually allocated. Derived
    #: rather than echoed back, so rounding is visible in it.
    share_of_total: float
    #: Plain-language reason this figure is what it is. Shown in the UI, because
    #: "why am I paying 62%" is the question the number always provokes.
    basis: str


@dataclass(frozen=True, slots=True)
class ContributionPlan:
    mode: ContributionMode
    currency: str
    target_minor: int
    contributions: tuple[Contribution, ...] = ()
    #: Target minus the sum of contributions. Non-zero only for FIXED, where
    #: the stated amounts need not add up to the bill — and where the gap is
    #: the single most useful thing the plan can tell you.
    shortfall_minor: int = 0
    #: Why the plan could not be completed. Empty when it could.
    blockers: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        return not self.blockers

    @property
    def allocated_minor(self) -> int:
        return sum(c.amount_minor for c in self.contributions)


def compute_plan(
    *,
    mode: ContributionMode,
    target_minor: int,
    currency: str,
    contributors: list[Contributor],
) -> ContributionPlan:
    """Work out what each person puts in.

    `target_minor` is the monthly cost being funded. A plan is always returned;
    an unfulfillable one carries `blockers` and no contributions, because a
    caller that has to distinguish "nobody pays anything" from "we cannot say"
    should not have to infer it from an empty list.
    """
    if not contributors:
        return ContributionPlan(
            mode=mode,
            currency=currency,
            target_minor=target_minor,
            blockers=("The household has no members to split between.",),
        )
    if target_minor < 0:
        return ContributionPlan(
            mode=mode,
            currency=currency,
            target_minor=target_minor,
            blockers=("A shared cost cannot be negative.",),
        )

    match mode:
        case ContributionMode.EQUAL:
            return _equal(target_minor, currency, contributors)
        case ContributionMode.PERCENTAGE:
            return _percentage(target_minor, currency, contributors)
        case ContributionMode.FIXED:
            return _fixed(target_minor, currency, contributors)
        case ContributionMode.INCOME_BASED:
            return _income_based(target_minor, currency, contributors)

    raise ValueError(f"Unknown contribution mode: {mode}")  # pragma: no cover


# --------------------------------------------------------------------- modes
def _equal(target: int, currency: str, people: list[Contributor]) -> ContributionPlan:
    weights = [Decimal(1)] * len(people)
    amounts = allocate(target, weights)
    share = f"1/{len(people)}"
    return _plan(
        ContributionMode.EQUAL,
        currency,
        target,
        people,
        amounts,
        basis=lambda _p, _a: f"An equal {share} of the shared costs.",
    )


def _percentage(target: int, currency: str, people: list[Contributor]) -> ContributionPlan:
    missing = [p.display_name for p in people if p.share is None]
    if missing:
        return ContributionPlan(
            mode=ContributionMode.PERCENTAGE,
            currency=currency,
            target_minor=target,
            blockers=(
                f"No agreed share for {', '.join(missing)}. "
                "A percentage split needs a figure for everyone, and inventing "
                "one would put words in somebody's mouth.",
            ),
        )

    total_share = sum((p.share or Decimal(0)) for p in people)
    notes: list[str] = []
    if total_share <= 0:
        return ContributionPlan(
            mode=ContributionMode.PERCENTAGE,
            currency=currency,
            target_minor=target,
            blockers=("The agreed shares add up to nothing.",),
        )
    if abs(total_share - Decimal(1)) > Decimal("0.0001"):
        # Normalised rather than refused: 55/40 is a household that has agreed
        # roughly and wants the pot funded, not a validation error. The note is
        # how they find out the figures drifted.
        notes.append(
            f"The agreed shares add up to {total_share * 100:.1f}%, not 100%. "
            "They have been scaled proportionally so the total is covered."
        )

    amounts = allocate(target, [(p.share or Decimal(0)) for p in people])
    return _plan(
        ContributionMode.PERCENTAGE,
        currency,
        target,
        people,
        amounts,
        basis=lambda p, _a: f"The agreed {float(p.share or 0) * 100:.0f}% share.",
        notes=notes,
    )


def _fixed(target: int, currency: str, people: list[Contributor]) -> ContributionPlan:
    missing = [p.display_name for p in people if p.fixed_minor is None]
    if missing:
        return ContributionPlan(
            mode=ContributionMode.FIXED,
            currency=currency,
            target_minor=target,
            blockers=(f"No fixed amount set for {', '.join(missing)}.",),
        )

    amounts = [int(p.fixed_minor or 0) for p in people]
    total = sum(amounts)
    shortfall = target - total

    notes: list[str] = []
    if shortfall > 0:
        notes.append(
            f"The fixed amounts cover {_money(total)} of {_money(target)}. "
            f"{_money(shortfall)} a month is unfunded."
        )
    elif shortfall < 0:
        notes.append(
            f"The fixed amounts come to {_money(total)}, which is "
            f"{_money(-shortfall)} more than the shared costs — the surplus "
            "builds up in the shared wallet."
        )

    return _plan(
        ContributionMode.FIXED,
        currency,
        target,
        people,
        amounts,
        basis=lambda _p, a: f"A standing {_money(a)} a month.",
        shortfall=shortfall,
        notes=notes,
    )


def _income_based(target: int, currency: str, people: list[Contributor]) -> ContributionPlan:
    missing = [p.display_name for p in people if p.monthly_income_minor is None]
    if missing:
        return ContributionPlan(
            mode=ContributionMode.INCOME_BASED,
            currency=currency,
            target_minor=target,
            blockers=(
                f"No income recorded for {', '.join(missing)}. "
                "Splitting by income needs both figures — treating an unknown "
                "income as zero would hand the whole bill to the other person.",
            ),
        )

    incomes = [int(p.monthly_income_minor or 0) for p in people]
    total_income = sum(incomes)
    if total_income <= 0:
        return ContributionPlan(
            mode=ContributionMode.INCOME_BASED,
            currency=currency,
            target_minor=target,
            blockers=("The household has no recorded income to split by.",),
        )

    amounts = allocate(target, [Decimal(i) for i in incomes])
    return _plan(
        ContributionMode.INCOME_BASED,
        currency,
        target,
        people,
        amounts,
        basis=lambda p, _a: (
            f"{(p.monthly_income_minor or 0) / total_income * 100:.0f}% of household income."
        ),
        notes=[
            "Shares follow income, so they change by themselves when a salary does.",
        ],
    )


# ----------------------------------------------------------------- machinery
def allocate(total: int, weights: list[Decimal]) -> list[int]:
    """Divide `total` by `weights` so the parts sum to exactly `total`.

    Largest-remainder: floor every share, then hand the leftover units out one
    at a time to whoever was rounded down hardest. Ties break on position, so
    the same inputs always produce the same answer — a split that moved a cent
    between partners depending on dict ordering would be a bug reported as a
    fairness complaint.

    Naive rounding is the thing this exists to avoid: three ways of 100.00 is
    33.33 each and a pot a cent short, every month, for ever.
    """
    weight_total = sum(weights)
    if weight_total <= 0:
        return [0] * len(weights)

    exact = [Decimal(total) * w / weight_total for w in weights]
    floors = [int(e) for e in exact]
    remainder = total - sum(floors)

    if remainder:
        order = sorted(
            range(len(weights)),
            key=lambda i: (-(exact[i] - floors[i]), i),
        )
        step = 1 if remainder > 0 else -1
        for k in range(abs(remainder)):
            floors[order[k % len(order)]] += step

    return floors


def _plan(
    mode: ContributionMode,
    currency: str,
    target: int,
    people: list[Contributor],
    amounts: list[int],
    *,
    basis,
    shortfall: int = 0,
    notes: list[str] | None = None,
) -> ContributionPlan:
    allocated = sum(amounts) or 1  # guard the division only
    contributions = tuple(
        Contribution(
            membership_id=p.membership_id,
            display_name=p.display_name,
            amount_minor=a,
            share_of_total=round(a / allocated, 4),
            basis=basis(p, a),
        )
        for p, a in zip(people, amounts, strict=True)
    )
    return ContributionPlan(
        mode=mode,
        currency=currency,
        target_minor=target,
        contributions=contributions,
        shortfall_minor=shortfall,
        notes=tuple(notes or ()),
    )


def _money(minor: int) -> str:
    return f"{minor / 100:,.2f}"


# ------------------------------------------------------------------ fairness
@dataclass(frozen=True, slots=True)
class FairnessLine:
    membership_id: str
    display_name: str
    expected_minor: int
    actual_minor: int

    @property
    def delta_minor(self) -> int:
        """Positive means they put in more than agreed."""
        return self.actual_minor - self.expected_minor


@dataclass(frozen=True, slots=True)
class Fairness:
    lines: tuple[FairnessLine, ...]
    #: The largest gap in either direction, which is what makes it worth
    #: raising at all.
    worst_gap_minor: int
    #: True when every gap is inside the tolerance — worth stating positively,
    #: because a household that is square deserves to be told so rather than
    #: shown a silent screen.
    is_balanced: bool
    summary: str


def assess_fairness(
    *,
    plan: ContributionPlan,
    actuals_minor: dict[str, int],
    tolerance_minor: int = 50_00,
) -> Fairness:
    """Compare what was agreed against what actually went in.

    `tolerance_minor` exists because nobody transfers an exact share every
    month, and a product that flags a 3-shilling discrepancy as an imbalance
    will be muted within a week. The default is deliberately generous.

    This never apportions blame. It reports two numbers per person and their
    difference; what that means is the household's business, and the wording
    below is careful to describe rather than judge.
    """
    lines = tuple(
        FairnessLine(
            membership_id=c.membership_id,
            display_name=c.display_name,
            expected_minor=c.amount_minor,
            actual_minor=int(actuals_minor.get(c.membership_id, 0)),
        )
        for c in plan.contributions
    )
    if not lines:
        return Fairness(lines=(), worst_gap_minor=0, is_balanced=True, summary="Nothing to compare yet.")

    worst = max(lines, key=lambda line: abs(line.delta_minor))
    balanced = abs(worst.delta_minor) <= tolerance_minor

    if balanced:
        summary = "Contributions match what you agreed."
    else:
        over = [line for line in lines if line.delta_minor > tolerance_minor]
        under = [line for line in lines if line.delta_minor < -tolerance_minor]
        parts = []
        if under:
            parts.append(
                ", ".join(f"{line.display_name} is {_money(-line.delta_minor)} under" for line in under)
            )
        if over:
            parts.append(
                ", ".join(f"{line.display_name} is {_money(line.delta_minor)} over" for line in over)
            )
        summary = "; ".join(parts) + " against the agreed split this period."

    return Fairness(
        lines=lines,
        worst_gap_minor=worst.delta_minor,
        is_balanced=balanced,
        summary=summary,
    )
