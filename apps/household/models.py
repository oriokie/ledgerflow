"""Households: two people, one set of finances, and the parts they keep apart.

The product already had multi-tenancy. What it did not have — and what a
household genuinely needs — is a *second* axis of access control, **inside** a
workspace. Row-level security isolates one tenant from another; within a
tenant, every member with a role can see everything. For an accountant and a
business that is correct. For two partners it is not, and the difference is not
cosmetic:

    People do not put their whole financial life into a shared workspace that
    shows their partner everything. They put in the joint account and keep the
    rest somewhere the product cannot see — at which point every projection,
    every affordability answer and every risk figure is computed on a fraction
    of the picture and is quietly wrong.

Privacy is therefore not a feature that competes with the intelligence layer.
It is the precondition for the intelligence layer having complete data to work
from. That is why this phase exists.

**Four sharing policies**, as the brief specifies, and each means something
precise about what the *other* members of the household can do:

``PRIVATE``             invisible. Not greyed out, not "hidden" — absent from
                        every query, exactly as another tenant's rows are.
``SHARED``              visible and editable, like any workspace record today.
``READ_ONLY``           visible, not editable. "This is mine, but you should
                        know it exists" — the common case for a salary account.
``APPROVAL_REQUIRED``   visible; changes by anyone other than the owner are
                        recorded as requests rather than applied.

**The default is PRIVATE**, and that is a deliberate cost. It means adopting
households have to opt each account into sharing, which is friction. The
alternative — defaulting to shared — would, on the day this ships, expose
accounts that existing members added when "workspace" meant "only me". A
migration that discloses somebody's finances to their spouse is not a
migration anyone gets to make on their behalf.

Enforcement lives in `visibility.py` and rides the same ambient-context
mechanism the tenant scoping already uses, so it fails closed the same way.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import SoftDeletableModel, TenantOwnedModel


class SharingPolicy(models.TextChoices):
    PRIVATE = "private", "Only me"
    SHARED = "shared", "Shared with the household"
    READ_ONLY = "read_only", "Household can see, only I can change"
    APPROVAL_REQUIRED = "approval_required", "Changes need my approval"


#: Policies under which a record is visible to household members who do not
#: own it. `PRIVATE` is deliberately absent — that is the whole point.
VISIBLE_TO_HOUSEHOLD = (
    SharingPolicy.SHARED,
    SharingPolicy.READ_ONLY,
    SharingPolicy.APPROVAL_REQUIRED,
)

#: Policies under which a non-owner may write directly.
WRITABLE_BY_HOUSEHOLD = (SharingPolicy.SHARED,)


class RelationshipKind(models.TextChoices):
    """How a member relates to the household. Distinct from their *role*, which
    is about permissions: an adult child helping with a parent's finances may be
    an ADMIN by role and a CHILD by relationship, and the two answer different
    questions."""

    SELF = "self", "Me"
    PARTNER = "partner", "Partner or spouse"
    CHILD = "child", "Child"
    PARENT = "parent", "Parent"
    OTHER = "other", "Other"


class HouseholdProfile(SoftDeletableModel):
    """Household-specific facts about one membership.

    A sibling of `Membership` rather than columns on it, because membership is
    tenancy's concern and belongs to every workspace type, while this is only
    meaningful for a household. An organization workspace should not grow a
    "contribution share" column it will never use.
    """

    membership = models.OneToOneField(
        "tenancy.Membership", on_delete=models.CASCADE, related_name="household_profile"
    )
    display_name = models.CharField(max_length=120, blank=True, default="")
    relationship = models.CharField(
        max_length=16, choices=RelationshipKind.choices, default=RelationshipKind.SELF
    )
    #: Agreed share of joint costs, as a fraction. Nullable because the honest
    #: default is "not agreed yet" — and a household that has not had the
    #: conversation should see that reflected rather than an invented 50/50.
    contribution_share = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "relationship"], name="household_rel_idx")]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.display_name or str(self.membership_id)


class Dependant(SoftDeletableModel):
    """Someone the household supports who does not hold a login.

    Children, and increasingly parents. Modelled because a dependant changes
    the arithmetic — costs now, and a cost that ends on a knowable date — not
    because the product wants a family tree.
    """

    name = models.CharField(max_length=120)
    relationship = models.CharField(
        max_length=16, choices=RelationshipKind.choices, default=RelationshipKind.CHILD
    )
    #: Year of birth rather than a full date: the month rarely changes a
    #: projection and a full birthdate is one more piece of a child's identity
    #: the product would be holding for no gain.
    birth_year = models.PositiveSmallIntegerField(null=True, blank=True)
    #: Monthly cost attributable to this dependant, when the household has a
    #: figure. Left null rather than estimated.
    monthly_cost_minor = models.BigIntegerField(null=True, blank=True)
    #: The year support is expected to end — school leaving, graduation. Drives
    #: the end of the cost in a projection.
    support_until_year = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(monthly_cost_minor__isnull=True) | models.Q(monthly_cost_minor__gte=0),
                name="dependant_cost_non_negative",
            ),
        ]
        indexes = [models.Index(fields=["tenant_id", "relationship"], name="dependant_rel_idx")]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name


class AccountSharing(SoftDeletableModel):
    """Who owns a financial account, and who else may see it.

    Deliberately a side table keyed to `finance.FinancialAccount` rather than
    two new columns on that model. The finance context is shared by personal,
    household and organization workspaces, and only one of those has an opinion
    about intra-workspace ownership; pushing household semantics into the
    ledger's neighbour would make every other workspace type carry them.

    The cost of that choice is real and worth naming: a side table can be
    *forgotten*. A query that does not consult it sees every account. That is
    why `visibility.py` exposes one filter used everywhere rather than leaving
    each call site to remember, and why the tests assert absence from listings,
    from lookups by id, and from the aggregate figures — three different ways
    the same leak shows up.
    """

    financial_account = models.OneToOneField(
        "finance.FinancialAccount", on_delete=models.CASCADE, related_name="sharing"
    )
    owner = models.ForeignKey(
        "tenancy.Membership",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_accounts",
    )
    policy = models.CharField(max_length=24, choices=SharingPolicy.choices, default=SharingPolicy.PRIVATE)
    #: True for the joint account — owned by nobody in particular and visible
    #: to all. Kept separate from `policy` because "shared" and "joint" are
    #: different claims: a shared account still has an owner who could take it
    #: private again, and a joint one does not.
    is_joint = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "owner"], name="sharing_owner_idx"),
            models.Index(fields=["tenant_id", "policy"], name="sharing_policy_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.financial_account_id} ({self.policy})"

    @property
    def visible_to_household(self) -> bool:
        return self.is_joint or self.policy in VISIBLE_TO_HOUSEHOLD

    @property
    def writable_by_household(self) -> bool:
        return self.is_joint or self.policy in WRITABLE_BY_HOUSEHOLD


class ContributionAgreement(SoftDeletableModel):
    """How this household has agreed to divide its shared costs.

    One live agreement per household, superseded rather than edited: the terms
    a couple were on last March is a fact about last March, and a fairness
    figure computed against today's split would silently rewrite it. Superseding
    keeps `effective_from` meaningful and makes "we changed this in June" a
    thing the timeline can show.

    `target_minor` is the monthly pot being funded. Nullable, and the null is
    load-bearing: a household that has agreed *how* to split without agreeing
    *how much* is a real state, and the engine derives the figure from shared
    costs rather than inventing one.
    """

    mode = models.CharField(max_length=16, default="equal")
    currency = models.CharField(max_length=3)
    #: The monthly shared cost being funded. Null means "derive it".
    target_minor = models.BigIntegerField(null=True, blank=True)
    effective_from = models.DateField()
    #: When the household wants to revisit this. Couples' incomes change and a
    #: split agreed once tends to outlive its own fairness.
    review_on = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=500, blank=True, default="")
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "superseded_at"], name="contrib_agreement_live_idx"),
        ]
        ordering = ["-effective_from"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.mode} from {self.effective_from}"


class ContributionTerm(SoftDeletableModel):
    """One member's side of an agreement.

    Holds the per-mode inputs that have nowhere else to live: a stated amount
    for FIXED, an agreed fraction for PERCENTAGE. EQUAL and INCOME_BASED need
    neither — the first by definition, the second because it reads real income.

    This supersedes `HouseholdProfile.contribution_share`, which predates it and
    could only express a percentage. The read path falls back to that field when
    no term exists, so existing households keep working and are migrated by use
    rather than by a migration that would have to guess at intent.
    """

    agreement = models.ForeignKey(ContributionAgreement, on_delete=models.CASCADE, related_name="terms")
    membership = models.ForeignKey(
        "tenancy.Membership", on_delete=models.CASCADE, related_name="contribution_terms"
    )
    fixed_minor = models.BigIntegerField(null=True, blank=True)
    share = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["agreement", "membership"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_term_per_member",
            ),
            models.CheckConstraint(
                condition=models.Q(fixed_minor__isnull=True) | models.Q(fixed_minor__gte=0),
                name="contribution_fixed_non_negative",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.membership_id}: {self.share or self.fixed_minor}"


class AuditAction(models.TextChoices):
    CREATED = "created", "Created"
    UPDATED = "updated", "Updated"
    DELETED = "deleted", "Deleted"
    APPROVED = "approved", "Approved"
    DECLINED = "declined", "Declined"
    SHARED = "shared", "Sharing changed"
    CONTRIBUTED = "contributed", "Contributed"
    PAID = "paid", "Paid"
    INVITED = "invited", "Invited"
    JOINED = "joined", "Joined"


class AuditEvent(TenantOwnedModel):
    """What happened in this household, who did it, and when.

    "Nothing should happen silently" is a promise about trust, and trust needs
    a record that cannot be tidied. So this is append-only in the strongest
    sense the ORM allows: `save()` refuses to update an existing row and
    `delete()` refuses outright. A log somebody can quietly edit after an
    argument is worth less than no log, because it carries the authority of one
    without the property that earns it.

    Deliberately *not* soft-deletable for the same reason `ChangeRequest` is
    not. Retention is a separate, explicit, tenant-wide operation — not
    something a disagreement can reach.

    `subject_type`/`subject_id` are a loose reference rather than a real FK: the
    log outlives what it describes, and a cascade that deleted the record of a
    deletion would be self-defeating.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="household_audit_events",
    )
    #: Kept alongside the FK so the log still names a person after the account
    #: is closed and the FK nulls out.
    actor_label = models.CharField(max_length=120, blank=True, default="")
    action = models.CharField(max_length=16, choices=AuditAction.choices)
    subject_type = models.CharField(max_length=40)
    subject_id = models.UUIDField(null=True, blank=True)
    #: A complete sentence, written at write time. Rendering it later from the
    #: parts would mean the log's wording drifts with the code, and an audit
    #: entry that reads differently than when it was made is not much of one.
    summary = models.CharField(max_length=255)
    #: Before/after, amounts, whatever the action needs. Never secrets.
    detail = models.JSONField(default=dict, blank=True)
    #: True when this touched something not everyone in the household can see.
    #: The event still exists — its existence is not the secret — but the
    #: summary is written without the private specifics.
    is_private = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "-created_at"], name="audit_recent_idx"),
            models.Index(fields=["tenant_id", "subject_type", "subject_id"], name="audit_subject_idx"),
            models.Index(fields=["tenant_id", "action"], name="audit_action_idx"),
        ]
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise ValueError(
                "Audit events are append-only. Record a new event describing the "
                "correction instead of editing the record of what happened."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "Audit events cannot be deleted. Retention is a tenant-wide policy "
            "operation, not a per-record one."
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.summary


class ChangeRequestStatus(models.TextChoices):
    PENDING = "pending", "Waiting for approval"
    APPROVED = "approved", "Approved"
    DECLINED = "declined", "Declined"


class ChangeRequest(TenantOwnedModel):
    """A change somebody wants to make to a record they do not control.

    The `APPROVAL_REQUIRED` policy's teeth. Recorded rather than applied, and
    deliberately *not* soft-deletable: a declined request is part of the record
    of what was asked, and quietly removable approval history would make the
    mechanism worth less than not having it. `TenantOwnedModel` is exactly that
    shape — the base the codebase already uses for immutable records — and it
    also brings the tenant-scoped manager and the auto-populated `tenant_id`
    this model originally lacked, which is why nothing could be written to it.
    """

    account_sharing = models.ForeignKey(
        AccountSharing, on_delete=models.CASCADE, related_name="change_requests"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="household_change_requests"
    )
    summary = models.CharField(max_length=255)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=12, choices=ChangeRequestStatus.choices, default=ChangeRequestStatus.PENDING
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="household_change_resolutions",
    )

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "status"], name="change_request_status_idx")]
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.summary} ({self.status})"
