"""Household analytics — the combined picture, and who is carrying it.

Two questions a shared workspace has to answer that a personal one never does:
*where does the household stand together*, and *who put in what*. They pull in
opposite directions on privacy, and the resolution is the same one banks have
used for a century:

    Aggregates may include what an individual may not itemise.

The household's combined net worth counts a partner's private savings account.
It does not tell you the balance, the institution, or that the account exists.
That is `all_account_ids()` for the total and `visible_account_ids()` for the
breakdown — two different calls, deliberately, so a rendering that shows the
breakdown can never accidentally be handed the total's dataset.

The uncomfortable case is a two-member household where one member has exactly
one private account: the aggregate minus the visible breakdown discloses its
balance by subtraction. That is not fixable by arithmetic, so it is handled by
disclosure instead — `combined_position()` reports how many accounts are
excluded from the breakdown, and the UI says so. A household that knows a
figure is being kept back is in a different position from one that has been
quietly told a wrong total.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db.models import Sum
from django.utils import timezone

from apps.common.tenant_context import require_current_tenant_id
from apps.finance.models import AccountType
from apps.ledger.models import AccountBalance
from apps.tenancy.models import Membership

from . import visibility
from .models import AccountSharing, Dependant, HouseholdProfile


def _household_memberships():
    """This workspace's memberships, and only this workspace's.

    `Membership` is exempt from the tenant-scoped manager and from RLS by
    design (workspace discovery happens before a tenant is bound), so it is
    one of the very few models where a query must scope itself. Iterating it
    bare listed every member of every workspace on the platform — with display
    names derived from their email addresses — to anyone who opened the
    household summary.
    """
    return Membership.objects.filter(tenant_id=require_current_tenant_id()).select_related("user")


@dataclass(frozen=True)
class MemberView:
    membership_id: str
    display_name: str
    relationship: str
    contribution_share: float | None
    #: Accounts this member owns that the viewer may see.
    visible_account_count: int
    is_you: bool


@dataclass(frozen=True)
class CombinedPosition:
    currency: str
    as_of: date
    #: Every account, including ones the viewer cannot itemise.
    total_assets_minor: int
    total_liabilities_minor: int
    net_worth_minor: int
    #: Only what the viewer may see, so a breakdown can be rendered from it.
    visible_assets_minor: int
    visible_liabilities_minor: int
    #: How much of the total is not itemisable by this viewer. Disclosed rather
    #: than hidden — see the module docstring.
    withheld_account_count: int
    members: list[MemberView] = field(default_factory=list)
    dependants: int = 0
    notes: list[str] = field(default_factory=list)


def _balances_for(account_ids: set, currency: str) -> tuple[int, int]:
    """(assets, liabilities) in minor units for a set of accounts."""
    rows = (
        AccountBalance.objects.filter(
            currency=currency,
            account__financial_account__id__in=account_ids,
            account__financial_account__is_active=True,
        )
        .values("account__financial_account__account_type")
        .annotate(total=Sum("balance_minor"))
    )
    liability_types = {AccountType.CREDIT_CARD, AccountType.LOAN}
    assets = 0
    liabilities = 0
    for row in rows:
        total = row["total"] or 0
        if row["account__financial_account__account_type"] in liability_types:
            liabilities += abs(total)
        else:
            assets += total
    return assets, liabilities


def combined_position(*, as_of: date | None = None) -> CombinedPosition:
    """Where the household stands together, and how much of it is itemisable."""
    as_of = as_of or timezone.localdate()

    from apps.finance import selectors as finance_selectors

    currency = finance_selectors._dominant_liquid_currency() or "USD"

    every = visibility.all_account_ids()
    allowed = visibility.visible_account_ids()
    visible = every if allowed is None else allowed

    total_assets, total_liabilities = _balances_for(every, currency)
    visible_assets, visible_liabilities = _balances_for(visible, currency)

    members = []
    current = visibility.current_membership()
    profiles = {p.membership_id: p for p in HouseholdProfile.objects.all()}
    for membership in _household_memberships():
        profile = profiles.get(membership.id)
        owned_visible = AccountSharing.objects.filter(
            owner_id=membership.id, financial_account_id__in=visible
        ).count()
        members.append(
            MemberView(
                membership_id=str(membership.id),
                display_name=(profile.display_name if profile else "")
                or getattr(membership.user, "email", "").split("@")[0],
                relationship=profile.relationship if profile else "other",
                contribution_share=(
                    float(profile.contribution_share)
                    if profile and profile.contribution_share is not None
                    else None
                ),
                visible_account_count=owned_visible,
                is_you=current is not None and membership.id == current.id,
            )
        )

    withheld = len(every - visible)
    notes = [
        "The household total counts every account. The breakdown only counts the ones "
        "you can see, so the two will not add up when a member keeps something private.",
    ]
    if withheld:
        notes.append(
            f"{withheld} account{'s' if withheld != 1 else ''} in this household "
            "are private to their owner and are counted in the total but not itemised."
        )
    if any(m.contribution_share is None for m in members) and len(members) > 1:
        notes.append(
            "No agreed contribution split is recorded. Nothing is assumed — a 50/50 "
            "the household never agreed to would be an invention, not a default."
        )

    return CombinedPosition(
        currency=currency,
        as_of=as_of,
        total_assets_minor=total_assets,
        total_liabilities_minor=total_liabilities,
        net_worth_minor=total_assets - total_liabilities,
        visible_assets_minor=visible_assets,
        visible_liabilities_minor=visible_liabilities,
        withheld_account_count=withheld,
        members=members,
        dependants=Dependant.objects.count(),
        notes=notes,
    )


@dataclass(frozen=True)
class ExpenseSplit:
    currency: str
    #: Monthly cost the household carries jointly, from dependants and shared
    #: accounts. Deliberately not a share of every expense: attributing a
    #: grocery shop to one partner is a fight the product should not start.
    monthly_dependant_cost_minor: int
    #: What each member's agreed share of that would be. Empty when no split
    #: has been agreed.
    per_member: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def expense_split() -> ExpenseSplit:
    """What the household jointly costs, and each member's agreed share.

    Only shared costs are split. Attributing individual spending to individual
    people would require the product to take a view on whose lunch was whose,
    which is a fight it should not start and could not win.
    """
    from apps.finance import selectors as finance_selectors

    currency = finance_selectors._dominant_liquid_currency() or "USD"
    dependant_cost = sum(d.monthly_cost_minor or 0 for d in Dependant.objects.all())

    profiles = {p.membership_id: p for p in HouseholdProfile.objects.all()}
    per_member = []
    shares_known = True
    for membership in _household_memberships():
        profile = profiles.get(membership.id)
        share = (
            float(profile.contribution_share) if profile and profile.contribution_share is not None else None
        )
        if share is None:
            shares_known = False
        per_member.append(
            {
                "membership_id": str(membership.id),
                "display_name": (profile.display_name if profile else "")
                or getattr(membership.user, "email", "").split("@")[0],
                "share": share,
                "monthly_minor": round(dependant_cost * share) if share is not None else None,
            }
        )

    notes = [
        "Only jointly-borne costs are split. Individual spending is not attributed, "
        "because deciding whose lunch was whose is not the product's business.",
    ]
    if not shares_known:
        notes.append("At least one member has no agreed share, so the split is incomplete.")

    return ExpenseSplit(
        currency=currency,
        monthly_dependant_cost_minor=dependant_cost,
        per_member=per_member,
        notes=notes,
    )


@dataclass(frozen=True)
class HouseholdCoverage:
    currency: str
    monthly_expenses_minor: int
    #: Liquid cash across the whole household, private accounts included.
    household_liquid_minor: int
    #: Months the household could cover — the figure that actually matters in
    #: an emergency, because in one the private accounts get spent too.
    household_runway_months: float
    #: The same figure using only what the viewer can see, which is what they
    #: would otherwise wrongly conclude.
    visible_runway_months: float
    notes: list[str] = field(default_factory=list)


def coverage() -> HouseholdCoverage:
    """Emergency-fund coverage for the household as a unit.

    Reported at household level *and* at what-you-can-see level, because those
    differ whenever anything is private and the gap is the point: a partner
    looking only at the joint account concludes the household has two months of
    cover when it has six. Under-stating resilience pushes people toward
    decisions they did not need to make.
    """
    from apps.finance import selectors as finance_selectors

    currency = finance_selectors._dominant_liquid_currency() or "USD"
    statement = finance_selectors.cashflow_statement(months=7)
    monthly_expenses = 0
    if statement and statement.rows:
        # Complete months with activity only. The statement pads its window
        # with empty rows and includes the in-progress month; a median over
        # either understates spending and overstates the runway.
        from django.utils import timezone as _tz

        current = _tz.localdate().replace(day=1)
        outflows = sorted(
            r.outflow_minor for r in statement.rows if r.period_start < current and r.outflow_minor > 0
        )
        if outflows:
            monthly_expenses = outflows[len(outflows) // 2]

    liquid_types = {AccountType.CHECKING, AccountType.SAVINGS, AccountType.CASH}
    every = visibility.all_account_ids()
    allowed = visibility.visible_account_ids()
    visible = every if allowed is None else allowed

    def liquid(ids: set) -> int:
        return (
            AccountBalance.objects.filter(
                currency=currency,
                account__financial_account__id__in=ids,
                account__financial_account__is_active=True,
                account__financial_account__account_type__in=liquid_types,
            ).aggregate(total=Sum("balance_minor"))["total"]
            or 0
        )

    household_liquid = liquid(every)
    visible_liquid = liquid(visible)

    def months(amount: int) -> float:
        return round(amount / monthly_expenses, 1) if monthly_expenses > 0 else 0.0

    notes = []
    if household_liquid != visible_liquid:
        notes.append(
            "The household figure includes cash held in accounts you cannot see. "
            "It is the one that matters in an emergency, because in one those "
            "accounts get spent too."
        )
    if monthly_expenses <= 0:
        notes.append("No recorded spending yet, so coverage cannot be measured in months.")

    return HouseholdCoverage(
        currency=currency,
        monthly_expenses_minor=monthly_expenses,
        household_liquid_minor=household_liquid,
        household_runway_months=months(household_liquid),
        visible_runway_months=months(visible_liquid),
        notes=notes,
    )


def dependant_events(*, as_of: date | None = None) -> list[dict]:
    """Dependants as projection events, ready for the scenario engine.

    A dependant with a known end year becomes a cost with an end date, which is
    the whole reason to record the year: a projection that carries childcare to
    the horizon is wrong by a large amount at exactly the point people are
    deciding whether they can afford something.
    """
    as_of = as_of or timezone.localdate()
    out = []
    for dependant in Dependant.objects.all():
        if not dependant.monthly_cost_minor:
            continue
        support_years = None
        if dependant.support_until_year:
            # Floor of one: support ending *this* year still costs something
            # this year. The compiler treats the year count the same way.
            support_years = max(1, dependant.support_until_year - as_of.year)
        out.append(
            {
                "kind": "new_child" if dependant.relationship == "child" else "caring_for_parent",
                "label": dependant.name,
                "params": {
                    "monthly_cost_minor": dependant.monthly_cost_minor,
                    # `is not None`, not truthiness: a support window that has
                    # nearly closed must not fall through to the compiler's
                    # 18-year default — that projected a dependant whose
                    # support ends this year as eighteen more years of cost.
                    **(
                        {"support_years": support_years}
                        if dependant.relationship == "child" and support_years is not None
                        else {}
                    ),
                    **(
                        {"years": support_years}
                        if dependant.relationship != "child" and support_years is not None
                        else {}
                    ),
                },
            }
        )
    return out


__all__ = [
    "CombinedPosition",
    "ExpenseSplit",
    "HouseholdCoverage",
    "MemberView",
    "combined_position",
    "coverage",
    "dependant_events",
    "expense_split",
]
