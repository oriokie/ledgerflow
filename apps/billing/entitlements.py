"""Plan entitlements and their enforcement.

Limits live on the `Plan` (max_accounts, max_members, ai_insights). They are
enforced only for tenants on an *active* subscription; a tenant with no active
subscription is treated as unmetered (the pre-billing / grandfathered state),
which is also what keeps the platform's own fixtures unconstrained.

Services call the `ensure_can_*` guards at the point a seat/account is consumed
and raise `PlanLimitExceeded`, which the API maps to 402 Payment Required.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import OperationalError, ProgrammingError
from django.utils import timezone

from .models import Subscription, SubscriptionStatus

logger = logging.getLogger(__name__)


class PlanLimitExceeded(Exception):
    """A workspace action would exceed its plan's entitlements."""


# Subscription states that actually grant a plan's entitlements.
_ENTITLED_STATUSES = frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING})


@dataclass(frozen=True)
class Entitlements:
    #: None means "no limit".
    max_accounts: int | None
    max_members: int | None
    ai_insights: bool
    #: False when there's no active subscription (limits don't apply).
    metered: bool
    #: Named capabilities this plan includes. Empty on an unmetered tenant,
    #: which is fine because `has_feature` short-circuits on `metered`.
    features: frozenset = frozenset()
    tier: str = ""


UNMETERED = Entitlements(max_accounts=None, max_members=None, ai_insights=True, metered=False)

#: A workspace whose trial ran out (or whose subscription lapsed) without a
#: plan being chosen. Reading and exporting stay open — data is never held
#: hostage — but every gated feature answers 402, and recording new activity
#: is paused (see ensure_workspace_active). Distinct from UNMETERED on
#: purpose: "never had billing" is a legacy deployment, "had a trial and let
#: it end" is a customer mid-decision.
LAPSED = Entitlements(
    max_accounts=None, max_members=None, ai_insights=False, metered=True, features=frozenset(), tier="lapsed"
)


def resolve_entitlements(*, tenant_id) -> Entitlements:
    try:
        sub = Subscription.objects.filter(tenant_id=tenant_id).select_related("plan").first()
    except (ProgrammingError, OperationalError):
        # Billing tables not migrated / temporarily unreachable. Entitlement
        # enforcement must never take down core finance operations, so fall
        # back to unmetered rather than surfacing a 500 on account creation.
        logger.warning("Entitlements unavailable for tenant %s; treating as unmetered.", tenant_id)
        return UNMETERED
    if sub is None:
        return UNMETERED
    if sub.status not in _ENTITLED_STATUSES:
        return LAPSED
    # The trial clock is authoritative, not the status field: correctness must
    # not depend on a scheduled job having flipped TRIALING to something else.
    if (
        sub.status == SubscriptionStatus.TRIALING
        and sub.trial_end is not None
        and sub.trial_end < timezone.now()
    ):
        return LAPSED
    plan = sub.plan
    # `Plan.features` is an explicit override for one-off deals; the tier map is
    # what a plan gets by default, so a new tier does not need every existing
    # plan row edited.
    from .plan_catalogue import features_for

    declared = {str(f) for f in (plan.features or [])}
    inherited = {str(f) for f in features_for(plan.tier)}
    return Entitlements(
        max_accounts=plan.max_accounts,
        max_members=plan.max_members,
        ai_insights=plan.ai_insights,
        metered=True,
        features=frozenset(declared | inherited),
        tier=plan.tier,
    )


def ensure_can_add_account(*, tenant_id, current_count: int) -> None:
    ent = resolve_entitlements(tenant_id=tenant_id)
    if ent.max_accounts is not None and current_count >= ent.max_accounts:
        raise PlanLimitExceeded(
            f"Your plan includes up to {ent.max_accounts} "
            f"account{'s' if ent.max_accounts != 1 else ''}. Upgrade your plan to add more."
        )


def ensure_can_add_member(*, tenant_id, current_count: int) -> None:
    ent = resolve_entitlements(tenant_id=tenant_id)
    if ent.max_members is not None and current_count >= ent.max_members:
        raise PlanLimitExceeded(
            f"Your plan includes up to {ent.max_members} "
            f"member{'s' if ent.max_members != 1 else ''}. Upgrade your plan to add more."
        )


def ensure_ai_insights(*, tenant_id) -> None:
    """Gate AI-powered features. Unmetered tenants (no active subscription) keep
    access; metered tenants only get it when their plan includes `ai_insights`."""
    if not resolve_entitlements(tenant_id=tenant_id).ai_insights:
        raise PlanLimitExceeded("AI insights aren't included in your plan. Upgrade to unlock them.")


def has_feature(*, tenant_id, feature) -> bool:
    """Whether a workspace's plan includes a named capability.

    Universal features are always true, and an unmetered tenant (no active
    subscription — self-hosted, comped, or mid-migration) gets everything. The
    same reasoning as the existing limit checks: entitlement enforcement must
    never be the reason a workspace cannot use the product it is not being
    billed for.
    """
    from .plan_catalogue import UNIVERSAL

    if str(feature) in UNIVERSAL:
        return True
    ent = resolve_entitlements(tenant_id=tenant_id)
    if not ent.metered:
        return True
    return str(feature) in ent.features


def ensure_feature(*, tenant_id, feature, label: str = "") -> None:
    """Gate a capability, with a message that names what is missing.

    The label exists because "this feature isn't in your plan" tells the reader
    nothing they can act on — they need to know *which* feature and *which*
    plan has it.
    """
    if has_feature(tenant_id=tenant_id, feature=feature):
        return

    ent = resolve_entitlements(tenant_id=tenant_id)
    if ent.tier == "lapsed":
        # "Upgrade to Plus" to someone whose trial ended is the wrong
        # sentence — they have no plan at all, and the message must say so.
        raise PlanLimitExceeded(
            "Your trial has ended — choose a plan to keep going. "
            "Your data is untouched and always exportable."
        )

    from .plan_catalogue import TIER_FEATURES

    cheapest = next(
        (
            tier
            for tier in ("plus", "family", "business")
            if str(feature) in {str(f) for f in TIER_FEATURES[tier]}
        ),
        None,
    )
    name = label or str(feature).replace("_", " ")
    suffix = f" It's included from {cheapest.title()}." if cheapest else ""
    raise PlanLimitExceeded(f"{name.capitalize()} isn't included in your plan.{suffix}")


def lock_tenant_for_limit_check(tenant_id) -> None:
    """Serialise a plan-limit check against concurrent ones for the same tenant.

    Entitlement checks are count-then-decide: they read the current member or
    account count, compare it to the plan, and commit. Two requests arriving
    together both read the pre-change count, both pass, and a 3-seat workspace
    ends up with 4 members. Taking a row lock on the tenant first makes the
    check-and-insert pair serial per workspace, which is the only granularity
    that matters — this never contends across tenants.
    """
    from apps.tenancy.models import Tenant

    Tenant.objects.select_for_update().filter(id=tenant_id).exists()


def ensure_workspace_active(*, tenant_id) -> None:
    """Raise PlanLimitExceeded when a lapsed workspace tries to record activity.

    The teeth of the trial: reading, reports over existing data and export all
    stay open, but new postings pause until a plan is chosen. Data hostage
    situations are the line — pausing *new* work is commerce, blocking access
    to what someone already recorded would be extortion.
    """
    ent = resolve_entitlements(tenant_id=tenant_id)
    if ent.metered and ent.tier == "lapsed":
        raise PlanLimitExceeded(
            "Your trial has ended — choose a plan to keep recording. "
            "Everything you've already recorded is safe and always exportable."
        )
