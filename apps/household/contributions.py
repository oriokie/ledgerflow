"""The contribution engine, wired to a real household.

`contribution_math.py` decides how a pot is divided. This decides what the pot
is, who is in it, and what each person actually earns and actually paid — the
parts that need a database.

Two derivations are worth reading before trusting the numbers.

**Income is attributed through the account it lands in.** `IncomeSource` has a
`deposit_account`, and `AccountSharing` records who owns an account, so a
salary paid into Amina's current account is Amina's income without anybody
having to say so twice. That reuse matters: the alternative was an
`owner` column on income, which would have been a second place to keep the same
fact correct and a second place for it to go stale. Income whose deposit
account has no owner is *unattributed*, not split — see `member_incomes`.

**Actual contributions are transfers into the shared wallet.** A transfer
carries a `transfer_group` linking both legs, so money leaving a member-owned
account and arriving in a joint one is that member's contribution, at the
amount and on the date the ledger already records. Nothing new is written and
nothing is inferred from memos.

Both derivations fail *visibly*. A household that cannot be assessed gets told
why, in words, rather than being shown a confident 50/50 that is arithmetic
performed on absences.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.common.tenant_context import require_current_tenant_id
from apps.tenancy.models import Membership

from . import audit
from .contribution_math import (
    Contribution,
    ContributionMode,
    ContributionPlan,
    Contributor,
    Fairness,
    assess_fairness,
    compute_plan,
)
from .models import (
    AccountSharing,
    AuditAction,
    ContributionAgreement,
    ContributionTerm,
    HouseholdProfile,
)


class ContributionError(ValueError):
    """A change that would produce an agreement the household cannot act on."""


# --------------------------------------------------------------- the members
def _members() -> list[Membership]:
    return list(Membership.objects.filter(tenant_id=require_current_tenant_id()).select_related("user"))


def _display_name(membership: Membership, profiles: dict) -> str:
    profile = profiles.get(membership.id)
    if profile and profile.display_name:
        return profile.display_name
    email = getattr(membership.user, "email", "") or ""
    return email.split("@")[0] or "Member"


# ---------------------------------------------------------------- the income
def member_incomes() -> tuple[dict[uuid.UUID, int], int]:
    """Monthly income per member, and the unattributed remainder.

    The remainder is returned rather than distributed. Income arriving in an
    account nobody owns is a real and common state — a joint account, or an
    account added before ownership was set — and folding it into somebody's
    total would make an income-based split quietly wrong in the direction of
    whoever happened to be picked.
    """
    from apps.income.models import IncomeSource
    from apps.income.selectors import monthly_equivalent_minor

    owner_by_account = dict(
        AccountSharing.objects.exclude(owner__isnull=True).values_list("financial_account_id", "owner_id")
    )

    per_member: dict[uuid.UUID, int] = {}
    unattributed = 0
    today = timezone.localdate()

    for source in IncomeSource.objects.all():
        if source.ends_on and source.ends_on < today:
            continue
        monthly = monthly_equivalent_minor(source.net_minor, source.frequency)
        if not monthly:
            continue
        owner_id = owner_by_account.get(source.deposit_account_id)
        if owner_id is None:
            unattributed += monthly
        else:
            per_member[owner_id] = per_member.get(owner_id, 0) + monthly

    return per_member, unattributed


# -------------------------------------------------------------- the shared pot
def shared_monthly_cost_minor() -> int:
    """What the household jointly spends in a month.

    Derived from the accounts marked joint, not from every expense: deciding
    that one partner's supermarket run was a household cost and the other's was
    personal is exactly the argument the product should stay out of. If it
    comes out of the joint account, it is joint.
    """
    from apps.finance.models import Transaction

    joint_ids = set(
        AccountSharing.objects.filter(is_joint=True).values_list("financial_account_id", flat=True)
    )
    if not joint_ids:
        return 0

    since = timezone.localdate().replace(day=1)
    # Three whole months back, so one unusual month does not set the figure.
    for _ in range(3):
        since = (since - timezone.timedelta(days=1)).replace(day=1)

    spend = Transaction.objects.filter(
        financial_account_id__in=joint_ids,
        occurred_at__date__gte=since,
        amount_minor__lt=0,
        transfer_group__isnull=True,  # a transfer in is funding, not cost
    ).values_list("amount_minor", flat=True)
    total = -sum(spend)
    return round(total / 3) if total else 0


# ------------------------------------------------------------- the agreement
def live_agreement() -> ContributionAgreement | None:
    return ContributionAgreement.objects.filter(superseded_at__isnull=True).first()


@transaction.atomic
def set_agreement(
    *,
    mode: str,
    currency: str,
    target_minor: int | None = None,
    effective_from: date | None = None,
    review_on: date | None = None,
    notes: str = "",
    terms: dict[str, dict] | None = None,
) -> ContributionAgreement:
    """Agree (or re-agree) how shared costs are divided.

    Supersedes rather than edits. `terms` maps membership id to
    ``{"share": Decimal, "fixed_minor": int}`` — only the key the mode needs is
    read, so a household switching between modes keeps the figures it set for
    both and does not have to re-enter them when it switches back.
    """
    if mode not in set(ContributionMode):
        raise ContributionError(f"{mode!r} is not a way of splitting costs.")
    if target_minor is not None and target_minor < 0:
        raise ContributionError("A shared cost cannot be negative.")

    now = timezone.now()
    previous = live_agreement()
    if previous is not None:
        previous.superseded_at = now
        previous.save(update_fields=["superseded_at", "updated_at"])

    agreement = ContributionAgreement.objects.create(
        mode=mode,
        currency=currency.upper(),
        target_minor=target_minor,
        effective_from=effective_from or timezone.localdate(),
        review_on=review_on,
        notes=notes,
    )

    # Carry forward the previous terms, then apply the changes on top, so
    # switching modes does not silently discard figures the household agreed.
    carried: dict[str, dict] = {}
    if previous is not None:
        for term in ContributionTerm.objects.filter(agreement=previous):
            carried[str(term.membership_id)] = {"share": term.share, "fixed_minor": term.fixed_minor}
    for membership_id, values in (terms or {}).items():
        carried.setdefault(str(membership_id), {}).update(values)

    for membership_id, values in carried.items():
        ContributionTerm.objects.create(
            agreement=agreement,
            membership_id=membership_id,
            share=values.get("share"),
            fixed_minor=values.get("fixed_minor"),
        )

    audit.record(
        action=AuditAction.UPDATED if previous else AuditAction.CREATED,
        subject_type="contribution_agreement",
        subject_id=agreement.id,
        summary=_describe_agreement(agreement, previous),
        detail={
            "mode": mode,
            "target_minor": target_minor,
            "previous_mode": previous.mode if previous else None,
        },
    )
    return agreement


def _describe_agreement(agreement, previous) -> str:
    labels = {
        ContributionMode.EQUAL: "an equal split",
        ContributionMode.PERCENTAGE: "an agreed percentage split",
        ContributionMode.FIXED: "fixed monthly amounts",
        ContributionMode.INCOME_BASED: "a split that follows income",
    }
    now = labels.get(agreement.mode, agreement.mode)
    if previous is None:
        return f"Set the household split to {now}."
    was = labels.get(previous.mode, previous.mode)
    if previous.mode == agreement.mode:
        return f"Updated the terms of {now}."
    return f"Changed the household split from {was} to {now}."


# ------------------------------------------------------------------- the plan
def current_plan(*, target_minor: int | None = None) -> ContributionPlan:
    """What each member should be putting in each month.

    With no agreement on file the household is *not* assumed to split equally.
    An equal split is a decision, and presenting one nobody made as though they
    had is how a product ends up in the middle of an argument it invented.
    """
    from apps.finance import selectors as finance_selectors

    agreement = live_agreement()
    currency = agreement.currency if agreement else (finance_selectors._dominant_liquid_currency() or "USD")

    if agreement is None:
        return ContributionPlan(
            mode=ContributionMode.EQUAL,
            currency=currency,
            target_minor=target_minor or shared_monthly_cost_minor(),
            blockers=(
                "This household has not agreed how to split shared costs yet. "
                "Choosing a split is a conversation, not a default.",
            ),
        )

    pot = target_minor
    if pot is None:
        pot = agreement.target_minor
    if pot is None:
        pot = shared_monthly_cost_minor()

    incomes, _unattributed = member_incomes()
    profiles = {p.membership_id: p for p in HouseholdProfile.objects.all()}
    term_by_member = {t.membership_id: t for t in ContributionTerm.objects.filter(agreement=agreement)}

    contributors = []
    for membership in _members():
        term = term_by_member.get(membership.id)
        profile = profiles.get(membership.id)
        # Falls back to the pre-existing profile field so households that set a
        # share before this engine existed keep working. See ContributionTerm.
        share = term.share if term and term.share is not None else None
        if share is None and profile and profile.contribution_share is not None:
            share = profile.contribution_share

        contributors.append(
            Contributor(
                membership_id=str(membership.id),
                display_name=_display_name(membership, profiles),
                monthly_income_minor=incomes.get(membership.id),
                fixed_minor=term.fixed_minor if term else None,
                share=Decimal(share) if share is not None else None,
            )
        )

    return compute_plan(
        mode=ContributionMode(agreement.mode),
        target_minor=pot,
        currency=currency,
        contributors=contributors,
    )


# --------------------------------------------------------------- the fairness
def actual_contributions_minor(*, since: date, until: date | None = None) -> dict[str, int]:
    """What each member actually transferred into the shared wallet.

    Read from real transfers rather than a separate "contribution" record the
    user would have to remember to create. The money already moved and the
    ledger already knows; asking somebody to log it again is how the figure
    ends up wrong.
    """
    from apps.finance.models import Transaction

    joint_ids = set(
        AccountSharing.objects.filter(is_joint=True).values_list("financial_account_id", flat=True)
    )
    owner_by_account = dict(
        AccountSharing.objects.exclude(owner__isnull=True).values_list("financial_account_id", "owner_id")
    )
    if not joint_ids or not owner_by_account:
        return {}

    until = until or timezone.localdate()
    incoming = Transaction.objects.filter(
        financial_account_id__in=joint_ids,
        transfer_group__isnull=False,
        amount_minor__gt=0,
        occurred_at__date__gte=since,
        occurred_at__date__lte=until,
    ).values_list("transfer_group", "amount_minor")

    groups = {group: amount for group, amount in incoming}
    if not groups:
        return {}

    # The other leg names the account the money came from, and its owner is the
    # contributor. Done in one query rather than per transfer.
    out_legs = Transaction.objects.filter(
        transfer_group__in=list(groups),
        amount_minor__lt=0,
    ).values_list("transfer_group", "financial_account_id")

    totals: dict[str, int] = {}
    for group, account_id in out_legs:
        owner_id = owner_by_account.get(account_id)
        if owner_id is None:
            continue  # from a joint account to itself, or an unowned source
        key = str(owner_id)
        totals[key] = totals.get(key, 0) + groups.get(group, 0)
    return totals


def fairness(*, months: int = 1) -> Fairness:
    """How the last `months` of real contributions compare with the agreement."""
    plan = current_plan()
    start = timezone.localdate().replace(day=1)
    for _ in range(months - 1):
        start = (start - timezone.timedelta(days=1)).replace(day=1)

    actuals = actual_contributions_minor(since=start)
    if months > 1:
        # Compare like with like: the plan is monthly, the window is not.
        plan = ContributionPlan(
            mode=plan.mode,
            currency=plan.currency,
            target_minor=plan.target_minor * months,
            contributions=tuple(
                Contribution(
                    membership_id=c.membership_id,
                    display_name=c.display_name,
                    amount_minor=c.amount_minor * months,
                    share_of_total=c.share_of_total,
                    basis=c.basis,
                )
                for c in plan.contributions
            ),
            blockers=plan.blockers,
            notes=plan.notes,
        )
    return assess_fairness(plan=plan, actuals_minor=actuals)


@dataclass(frozen=True)
class ContributionOverview:
    plan: ContributionPlan
    fairness: Fairness
    derived_target_minor: int
    unattributed_income_minor: int
    agreement_id: str | None
    review_on: date | None


def overview() -> ContributionOverview:
    """Everything the contributions screen needs, in one call."""
    agreement = live_agreement()
    _incomes, unattributed = member_incomes()
    return ContributionOverview(
        plan=current_plan(),
        fairness=fairness(),
        derived_target_minor=shared_monthly_cost_minor(),
        unattributed_income_minor=unattributed,
        agreement_id=str(agreement.id) if agreement else None,
        review_on=agreement.review_on if agreement else None,
    )
