# `tenancy` — Workspaces, Membership, RBAC

Owns the concept of a shared financial workspace ("tenant") and who belongs
to it with what role. Every other module's data hangs off a `tenant_id` that
originates here.

## Domain model

| Model | Purpose | Key fields |
|---|---|---|
| `Tenant` | A shared workspace — personal, household, or organization | `type` (`TenantType`), `base_currency`, `default_locale`, `default_timezone`, `billing_email`, `is_active` |
| `Membership` | A user's role within one tenant | `tenant`, `user`, `role` (`Role`); unique on `(tenant, user)` |
| `Invitation` | A pending invite to join a workspace by email | `tenant`, `email`, `role`, `status`, `token_hash` (raw token never stored — see below), `expires_at` |

`TenantType`: `personal` / `household` / `organization` — one schema for all
three; they differ in policy and presentation, not isolation mechanics.

`Role` (fixed hierarchy, `VIEWER < MEMBER < ADMIN < OWNER`) — see
[`../PERMISSIONS.md`](../PERMISSIONS.md) for the full capability matrix.

**`Tenant`, `Membership`, and `Invitation` are deliberately NOT RLS-protected.**
They're control-plane data written/read around the edges of a tenant context
(you have no membership yet when accepting an invitation; workspace creation
happens before any tenant context exists). Isolation is enforced at the
service/selector layer instead — every read filters by the actor's own
`user`/`tenant`, never a raw unscoped query.

**Invitation tokens are hashed, never stored raw** — same discipline as
passwords and MFA backup codes. The raw token is returned to the caller
exactly once, at creation; a leaked database dump can't be used to accept
someone else's invitation.

## Service layer (`services.py`)

| Function | Does |
|---|---|
| `create_workspace(name, owner, type, base_currency, locale, timezone)` | Creates a `Tenant` + an `OWNER` `Membership` for the creator, atomically |
| `add_member(tenant, user, role)` | Creates a `Membership` directly (used by invitation acceptance) |
| `change_member_role(actor_membership, target_membership, new_role)` | Enforces: actor has `WORKSPACE_MANAGE_MEMBERS` (or is acting on themselves), actor outranks target (or both are owners), actor can't grant a role above their own, and the change can't leave the workspace with zero owners (`LastOwnerError`) |
| `remove_member(actor_membership, target_membership)` | Same seniority/last-owner rules as role change |
| `create_invitation(tenant, invited_by_membership, email, role)` | Generates + hashes a token, persists the `Invitation`, enqueues `send_invitation_email`. Returns `(invitation, raw_token)` |
| `accept_invitation(raw_token, user)` | Validates the token (pending, not expired, email matches), creates the `Membership`, marks the invitation accepted |
| `revoke_invitation(invitation, actor_membership)` | Requires `WORKSPACE_MANAGE_INVITATIONS` |

All are `@transaction.atomic` and emit an `OutboxEvent`
(`tenancy.workspace.created`, `tenancy.member.added`, `tenancy.member.role_changed`,
`tenancy.member.removed`, `tenancy.invitation.created`).

## Selectors (`selectors.py`)

`workspaces_for_user(user)`, `memberships_for_user(user)` (one query,
`select_related("tenant")` — what the workspace switcher needs),
`membership_for(user, tenant_id)`, `members_of(tenant)`.

## Key workflow: invite → accept

1. An ADMIN/OWNER calls `create_invitation` → an `Invitation` row + a raw
   token (shown once) → `send_invitation_email` task fires asynchronously
   (Celery, `bind=True, max_retries=3` — a slow mail provider never blocks
   the request).
2. The invitee clicks the emailed link, `POST /api/v1/tenancy/invitations/accept/`
   with the token.
3. `accept_invitation` validates and creates the `Membership`. The invitee is
   now a member with the invited role, without ever having had a tenant
   context before this call.

## API

Base path `/api/v1/tenancy/`. Note the auth model differs from every other
module: these views check `IsAuthenticated` + resolve membership manually
(`_TenantScopedControlPlaneView._require_membership`), **not**
`TenantScopedAPIView` — because `tenancy` itself isn't RLS-protected, binding
the RLS GUC here would be a no-op.

| Method | Path | Purpose | Auth |
|---|---|---|---|
| `GET` | `/workspaces/` | List the caller's workspaces + role in each | `IsAuthenticated` only (spans tenants by definition) |
| `POST` | `/workspaces/` | Create a new workspace (caller becomes OWNER) | `IsAuthenticated` only |
| `GET` | `/workspaces/members/` | List members of the current workspace | `X-Tenant-ID` + membership |
| `PATCH` | `/workspaces/members/<id>/` | Change a member's role | + `WORKSPACE_MANAGE_MEMBERS` |
| `DELETE` | `/workspaces/members/<id>/` | Remove a member | + `WORKSPACE_MANAGE_MEMBERS` |
| `GET` | `/workspaces/invitations/` | List pending invitations | + `X-Tenant-ID` + membership |
| `POST` | `/workspaces/invitations/` | Create an invitation | + `WORKSPACE_MANAGE_INVITATIONS` |
| `DELETE` | `/workspaces/invitations/<id>/` | Revoke a pending invitation | + `WORKSPACE_MANAGE_INVITATIONS` |
| `POST` | `/invitations/accept/` | Accept an invitation by token | `IsAuthenticated` only (no membership yet — that's the point) |

All mutating endpoints use `throttle_scope = "write"`.

## Permissions

See [`../PERMISSIONS.md`](../PERMISSIONS.md) for the full role/capability
matrix. `tenancy` is where `Role` and `Capability` are defined
(`rbac.py`) and consumed by `IsTenantMember`
(`permissions.py`) — every other module's `required_role`/
`required_capability` references these same enums.

## Configuration

`INVITATION_TTL_DAYS` (default 7) — see [`../CONFIGURATION.md`](../CONFIGURATION.md).

## Extension points

- **Custom per-tenant roles** — the fixed hierarchy is a deliberate scope
  decision; see [`../EXTENSION_POINTS.md`](../EXTENSION_POINTS.md#adding-a-custom-per-tenant-role)
  for the seam (`has_capability` callers never check role directly).
- **New tenant types** — `TenantType` is just a `TextChoices`; a new value
  plus whatever policy you attach to it (e.g. a seat limit in `add_member`)
  doesn't require schema changes.

## Testing

`tests/test_tenancy.py`, `tests/test_organizations.py`, `tests/test_invitations.py`.
Covers: role hierarchy enforcement, last-owner protection, invitation
expiry/single-use/email-matching, and cross-tenant membership isolation at
the selector layer (since these models aren't RLS-protected, the selectors
themselves are the isolation boundary being tested).
