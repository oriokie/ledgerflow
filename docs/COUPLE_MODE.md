# Couple Mode

How two people run their money together in LedgerFlow without either of them
giving up the right to a private financial life.

This document is the reference the implementation phases work from. It records
what exists, what is being built, and — more importantly — *why* each decision
went the way it did, because most of the hard choices here are not technical.

---

## 1. The thesis

Shared-finance features usually fail in one of two directions.

**Too shared.** The product asks a couple to pool everything. What actually
happens is that they put the joint account in and keep the rest somewhere the
product cannot see — at which point every projection, affordability answer and
risk figure is computed on a fraction of the picture and is quietly wrong. The
product does not know it is wrong, so it says wrong things confidently.

**Too separate.** The product gives each person a silo and a read-only view of
the other. Nothing is jointly *owned*, so there is nothing to plan with, and
the couple goes back to a spreadsheet.

LedgerFlow's position is that **privacy is the precondition for completeness,
not its opposite.** People will put their whole financial life into a system
that lets them keep parts of it to themselves. They will not put it into one
that does not. Every design decision below follows from that.

The second principle is narrower and just as load-bearing: **the product does
not take sides.** It reports figures and their differences. It does not decide
whose spending was frivolous, whose share is fair, or who is behind. Wording is
tested for this (`test_household_contributions.py::test_the_wording_describes_rather_than_blames`).

---

## 2. Two axes of access

The system has two independent boundaries, and conflating them is the single
easiest way to build a serious leak.

| | Protects | Enforced by | Backstop |
|---|---|---|---|
| **Tenant** | one household from another | `TenantScopedManager` + Postgres RLS | database |
| **Member** | one partner from the other | `household/visibility.py` | **none** |

RLS binds a *tenant*, and two partners share a tenant. So there is no database
policy standing between Amina's private savings account and Brian — everything
protecting it is Python, in one module, and that asymmetry is why that module
is written the way it is:

- **One filter, used everywhere.** `visible_account_ids()` is the only sanctioned
  answer to "what may this person see". A predicate assembled twice is a
  predicate that will differ once.
- **Fail closed on an unknown actor.** No actor bound (a Celery task, a
  misconfigured view) resolves to "joint and explicitly shared only", not
  "everything". Code that legitimately needs the whole workspace calls
  `all_account_ids()`, which is greppable.
- **Inert for one person.** A single-member workspace has nothing to hide from
  itself; every account resolves visible regardless of policy. Without this,
  shipping the feature would have made every existing solo workspace's accounts
  vanish.

### Sharing policies

Set per account, defaulting to `PRIVATE`.

| Policy | Partner sees | Partner edits |
|---|---|---|
| `PRIVATE` | nothing — absent from every query | no |
| `READ_ONLY` | yes | no |
| `APPROVAL_REQUIRED` | yes | via `ChangeRequest` only |
| `SHARED` | yes | yes |

`is_joint` is separate from `policy` on purpose: "shared" and "joint" are
different claims. A shared account still has an owner who could take it private
again; a joint one does not.

**Why `PRIVATE` is the default, despite the friction.** The alternative would,
on the day it ships, expose accounts that members added when "workspace" meant
"only me". A migration that discloses somebody's finances to their spouse is
not one anybody gets to make on their behalf.

**The one deliberate fail-open:** accounts with no `AccountSharing` row are
treated as visible. Hiding data a household already relies on is a worse failure
than showing an account whose policy nobody has set. The fix is
`ensure_sharing_rows()`, run when a second member joins — not a different rule.

---

## 3. Information architecture

```
My Finances  ← personal tenant, sole member, unchanged product
Our Finances ← household tenant, ≥2 members, member boundary active
  ├── Dashboard        combined position, goals, bills, health
  ├── Shared wallet    joint accounts + the contribution agreement
  ├── Goals            shared, with per-member contribution
  ├── Bills            shared, with split and ownership
  ├── Investments      joint, with ownership percentages
  ├── Approvals        pending change requests + threshold approvals
  ├── Meeting          the monthly financial meeting
  ├── Activity         the audit trail
  └── Settings         members, sharing policies, dependants
```

Switching between them is workspace switching, which already exists — a couple
are two tenants plus a shared one, not a new primitive.

---

## 4. Schema

Existing (`apps/household/models.py`):

| Model | Purpose |
|---|---|
| `HouseholdProfile` | per-membership: display name, relationship, legacy contribution share |
| `Dependant` | someone supported who has no login; drives projections |
| `AccountSharing` | owner + policy + `is_joint` for one financial account |
| `ChangeRequest` | a change to a record you do not control; append-only |

Added in this phase:

| Model | Purpose |
|---|---|
| `ContributionAgreement` | how shared costs are divided; superseded, never edited |
| `ApprovalRule` | an amount threshold above which the household checks with each other |
| `SpendApproval` | one request to spend, or one flag on spending that already happened |
| `ApprovalComment` | the thread on an approval; append-only |
| `TransactionPrivacy` | a deliberate privacy choice about one line; rows exist only for exceptions |
| `ContributionTerm` | one member's side — fixed amount or agreed share |
| `AuditEvent` | append-only household activity log |

`ContributionAgreement` is **superseded rather than edited** because the terms a
couple were on last March is a fact about last March. A fairness figure computed
against today's split would silently rewrite it, and "we changed this in June"
is exactly the entry that settles an argument.

`ContributionTerm` supersedes `HouseholdProfile.contribution_share`, which could
only express a percentage. The read path falls back to it when no term exists,
so existing households migrate by use rather than by a migration that would
have to guess at intent.

---

## 5. The contribution engine

Four modes, because couples genuinely divide costs four ways and a product that
offers one tells three-quarters of its users they are doing it wrong.

| Mode | Needs | Notes |
|---|---|---|
| `EQUAL` | nothing | the mode people start on |
| `PERCENTAGE` | agreed share per person | shares that don't total 100% are scaled *and flagged* |
| `FIXED` | stated amount per person | reports the shortfall or surplus against real costs |
| `INCOME_BASED` | income per person | re-balances itself when a salary changes |

Two rules run through all of them.

**The parts sum to the whole.** Three people splitting 100.00 is not 33.33 each
— that is a pot a cent short, every month, for ever. `allocate()` uses the
largest-remainder method with deterministic tie-breaking, so the same inputs
always produce the same answer. A cent that moved between partners depending on
dict ordering would be reported as a fairness bug.

**Unknowable is never zero.** An unknown income blocks an income-based split
rather than being treated as nothing — because zero silently hands the entire
bill to the other person and presents it as arithmetic. Every mode can return an
incomplete plan, and incomplete plans carry the reason in words.

### Derivations

- **Income → member** via `IncomeSource.deposit_account` → `AccountSharing.owner`.
  Reuses existing structure; the alternative was an owner column on income,
  which is a second place to keep the same fact correct and a second place for
  it to go stale. Income landing in an unowned account is reported as
  *unattributed*, never distributed.
- **Actual contributions** are transfers into joint accounts, matched through
  `transfer_group` to the account they came from and thence to its owner. The
  money already moved and the ledger already knows; asking somebody to log it
  again is how the figure ends up wrong.
- **Shared cost** is a three-month mean of spending from joint accounts, so one
  unusual month does not set the figure.

### Fairness

`assess_fairness()` compares agreed against actual with a generous default
tolerance (KSh 500). Nobody transfers an exact share, and a product that flags a
three-shilling discrepancy gets muted within a week. A balanced household is
told so explicitly rather than shown a blank screen.

---

## 6. The audit trail

`AuditEvent` is append-only in the strongest sense the ORM allows: `save()`
refuses to update an existing row and `delete()` refuses outright. A log
somebody can quietly edit after an argument carries the authority of an audit
trail without the property that earns it — which is worse than not having one.

Three decisions worth recording:

- **Called explicitly, not via signals.** A signal knows a `Goal` was updated
  and nothing about why. "Amina raised the house deposit target from 2m to 2.5m"
  is the entry worth having; `goal.updated` is noise that trains people to
  ignore the log.
- **Summaries are stored, not re-rendered.** An entry that reads differently
  than when it was made is not much of an audit entry.
- **Failure never breaks the caller.** Wrapped in a savepoint *and* guarded —
  catching the exception alone is insufficient, because a failed INSERT poisons
  the surrounding transaction and the caller's next query dies for a reason
  unrelated to what they were doing. The actor FK is resolved to a real user or
  `None` before writing, because Django FKs are `DEFERRABLE INITIALLY DEFERRED`
  and a dangling one raises at *commit*, where no `except` can reach it.

Private events are recorded and shown, with specifics omitted from the summary.
Their existence is not the secret, and a timeline with silent gaps is itself
informative — and worse than one that says "something happened".

---

## 6a. Amount-triggered approvals

Separate from `AccountSharing`'s `APPROVAL_REQUIRED` policy, and deliberately
so: that one asks *"may you touch this account"*, this one asks *"is this amount
large enough that we should both know"*. A household can want either, both or
neither.

### The distinction that shapes everything

LedgerFlow records money that has **already moved** — a statement import is
history — and it also lets a partner ask **before** spending. These are
different events:

| Kind | Money moved? | Approving it means |
|---|---|---|
| `REQUESTED` | not yet | a decision: permits or prevents a purchase |
| `FLAGGED` | already | a review: "I have seen this and I am content" |

Collapsing them would let the interface claim it *blocked* a purchase it merely
*noticed afterwards* — a claim the product cannot support and would be caught
making at the worst possible moment. The wording generated for the audit trail
differs by kind for exactly this reason: a request is "approved", a flag is
"reviewed and accepted".

### Rules

Several may exist; the highest threshold at or below the amount wins, so "tell
me over 20,000" and "give us longer over 100,000" do not fight. Amounts are
compared as magnitudes, so a caller passing a signed ledger amount does not have
to remember which sign spending has.

**A rule never reaches a private account.** Making somebody approve spending on
an account they cannot even see would be surveillance wearing a governance hat.

**A workspace of one is never interrogated.** There is nobody to ask.

### What silence means

An unanswered request expires to `EXPIRED`, which is neither approved nor
declined. Auto-approving defeats the mechanism; auto-declining lets one partner
veto the other by saying nothing, turning an absence into a decision. Every
expiry is audited, so the requester can tell "nobody answered" from "the product
lost it".

### What it does not do

It does not stand between a user and their own ledger. `require_approval_for()`
answers a question; acting on the answer is the caller's job. Nothing here
posts, reverses or holds a transaction — a household rule that could silently
prevent somebody accessing their own money is a bigger hazard than the
overspending it guards against.

### Other rules

- Nobody approves their own **request** — a second pair of eyes you supply
  yourself is decoration. Reviewing your own **flagged** spending is allowed,
  because a flag is a notification and marking it seen decides nothing about
  anybody else's money.
- A suggestion (`"could you make it 30,000?"`) leaves the request **open**. It
  is a step in a negotiation, not a verdict.
- Only the requester may withdraw.

---

## 6b. Transaction-level privacy

Account privacy decides whether a partner sees an account. This decides how much
of a *line* they see inside an account they can already see. They compose,
account first — a line in a private account is invisible whatever its own
setting says.

| Level | They see |
|---|---|
| `PRIVATE` | nothing; omitted from itemised listings |
| `CATEGORY_ONLY` | the category, not the amount — the gift case |
| `AMOUNT_ONLY` | the amount, not what it was — the hobby case |
| `FULL` | everything (clears the mark) |

**A row exists only for exceptions.** Accounts number in dozens; transactions in
hundreds of thousands — one M-Pesa import adds 866. Storing only deliberate
choices keeps the id set small enough to filter with, and means shipping this is
inert: no existing transaction has a row.

**Redaction happens at one choke point.** `_txn_out()` in the finance API is the
single function every transaction response passes through, and it redacts there
rather than in each of its nine call sites. The `levels` argument is an
optimisation, not a switch — omitting it costs a query and redacts anyway, so
forgetting makes an endpoint slower, never more revealing.

**Your own marks never hide anything from you**, or marking a purchase private
would make it vanish from your own ledger and read as data loss. **A partner
cannot lift your mark** — a privacy setting the other party can remove is not
one — and this is the single rule role seniority does not override.

**Totals still include hidden lines.** A partner who cannot itemise a purchase
must still see it in the month's outgoings, or the figures they *are* shown are
wrong and they will act on them. Aggregate truth, itemised privacy — the same
trade `all_account_ids()` makes.

### The limitation, stated rather than hidden

Hiding a line inside an account whose **balance** the partner can see does not
hide its amount from anybody willing to subtract: the balance moved and the
visible lines do not account for the difference.

`PRIVATE` reliably conceals **what** something was. It conceals **how much**
only on an account whose balance the partner cannot see. Genuinely private
spending belongs on a private account; this feature is for keeping the *nature*
of a purchase to yourself within shared money.

This is asserted as a test
(`test_hiding_a_line_does_not_hide_the_amount_from_arithmetic`) so that nobody
later reads the feature as stronger than it is and builds a promise on it. The
UI must not describe `PRIVATE` as "hidden completely" on a shared account.

---

## 7. Permission model

| Action | Minimum role | Extra rule |
|---|---|---|
| Read household aggregates | `VIEWER` | — |
| Read the activity log | `VIEWER` | an audit only one party can read is not a trust mechanism |
| Itemise an account | `VIEWER` | **and** account visible per `visibility.py` |
| Change an account's sharing policy | `MEMBER` | **owner only** — see below |
| Agree the contribution split | `MEMBER` | not admin — see below |
| Approve a change request | `MEMBER` | owner of the affected account only |
| Manage members, dependants | `ADMIN` | — |

Two of these deliberately break with role seniority:

- **Only an owner changes their account's policy.** Role governs the workspace;
  it does not confer the right to expose somebody else's account. A household
  where whoever set up billing can un-private their partner's savings is not one
  either of them should trust.
- **Any member agrees the split.** How two people divide their own costs is not
  a permission the billing owner should hold over the other.

---

## 8. API

Existing: `summary/`, `members/`, `dependants/`, `sharing/`, `sharing/backfill/`,
`change-requests/`.

Added: 

| Endpoint | Method | Returns |
|---|---|---|
| `/api/v1/household/contributions/` | `GET` | plan + fairness + derived figures, in one response |
| `/api/v1/household/contributions/` | `PUT` | re-agrees the split, supersedes the previous |
| `/api/v1/household/activity/` | `GET` | the audit timeline, filterable by subject |
| `/api/v1/household/approval-rules/` | `GET` `POST` | spending thresholds |
| `/api/v1/household/approvals/` | `GET` `POST` | open approvals and history; ask before spending |
| `/api/v1/household/approvals/{id}/` | `POST` | approve, decline, suggest, withdraw or comment |

Plan and fairness come back together because they are meaningless apart: a plan
without actuals is an aspiration, and actuals without a plan are a list of
transfers.

---

## 9. Testing strategy

| Layer | Approach |
|---|---|
| Contribution maths | pure functions, no database; property-style tests that allocation never loses or invents a unit across many totals and party counts |
| Privacy | absence asserted three ways — from listings, from lookup by id, and from aggregates — because that is three different ways the same leak surfaces |
| Audit | immutability (edit and delete both refused), resilience (a logging failure returns `None` and leaves the caller's transaction usable), isolation |
| Cross-tenant | `test_household_cross_tenant.py` — one household cannot reach another's anything |
| Wording | asserted directly: fairness summaries must not contain *should*, *failed*, *owes*, *must*, *unfair*, *behind* |

The wording test is not whimsy. This text lands in the middle of somebody's
relationship, and a product that editorialises there will be uninstalled.

---

## 10. Security and privacy

- Member-boundary enforcement has **no database backstop** and therefore no
  second chance. Every new query touching accounts must go through
  `restrict_accounts()`; the perimeter test (`test_household_finance_perimeter.py`)
  exists to catch call sites that forget.
- Audit retention is a tenant-wide policy operation, never a per-record one — so
  a disagreement cannot reach it.
- Approval authentication, biometric confirmation and device management are
  **not built**; they belong with the threshold-approval phase.

---

## 11. Extensibility

- **Children and dependants** — `Dependant` exists and drives projections. A
  dependant who later gets a login becomes a `Membership` with
  `RelationshipKind.CHILD` and, presumably, tightly scoped visibility.
- **Financial advisors** — `Role.VIEWER` already models read-only access for a
  third party. What is missing is time-boxing and per-account grants.
- **More than two adults** — nothing in the contribution engine assumes two
  people; `allocate()` is tested to 7.

---

## 12. Status

| Deliverable | State |
|---|---|
| Workspace split, personal + household | **built** (pre-existing) |
| Privacy / sharing policies | **built** (pre-existing) |
| Change-request approvals | **built** (pre-existing, policy-triggered) |
| Dependants | **built** (pre-existing) |
| Contribution engine, 4 modes + fairness | **built, this phase** |
| Audit trail | **built, this phase** |
| Approval thresholds, comments, expiry, suggestions | **built, this phase** |
| Transaction-level privacy | **built, this phase** |
| Monthly financial meeting | designed, not built |
| Per-member health scores | not built |
| Couple AI coach, calendar, gamification | not built |
| Joint-investment ownership % | not built |

Nothing above claims to be finished that is not. The sequencing is deliberate:
the contribution engine and the audit trail are the two things everything else
reads from, and the audit trail specifically cannot be retrofitted — you cannot
reconstruct a history you never recorded.
