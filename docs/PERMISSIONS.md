# Permissions

Three layers, checked in order on every tenant-scoped request: **who are
you** (JWT auth) → **are you in this workspace, with a sufficient role**
(RBAC, at the DRF permission layer) → **can the database prove it** (RLS, at
the Postgres layer). The first two determine what a request is *allowed* to
attempt; the third is the backstop that holds even if the first two have a bug.

## Authentication

JWT via `djangorestframework-simplejwt`. Access tokens are short-lived
(`JWT_ACCESS_MINUTES`, default 15 min); refresh tokens rotate on use and are
blacklisted after rotation (`ROTATE_REFRESH_TOKENS` + `BLACKLIST_AFTER_ROTATION`
in `SIMPLE_JWT`), so a stolen refresh token is single-use. See
[`modules/users.md`](./modules/users.md) for the full login/MFA/passkey flow.

Every request needing tenant data also carries an **`X-Tenant-ID` header** —
JWT identity and workspace context are independent; a user can be a member of
several workspaces and picks one per request.

## RBAC: roles and capabilities

`apps/tenancy/models.py` defines a **fixed role hierarchy** (not fully custom
per-tenant roles — a deliberate scope decision, see
[`EXTENSION_POINTS.md`](./EXTENSION_POINTS.md#adding-a-custom-per-tenant-role)):

| Role | Order | Typical holder |
|---|---|---|
| `VIEWER` | 0 | An accountant with read-only access |
| `MEMBER` | 1 | A household member who can log spending |
| `ADMIN` | 2 | Manages members, invitations, workspace settings |
| `OWNER` | 3 | Billing, can delete the workspace; every workspace needs ≥1 |

`apps/tenancy/rbac.py` maps each role to a `Capability` set:

| Capability | Viewer | Member | Admin | Owner |
|---|:-:|:-:|:-:|:-:|
| `ledger.read` | ✓ | ✓ | ✓ | ✓ |
| `ledger.write` | | ✓ | ✓ | ✓ |
| `workspace.read` | ✓ | ✓ | ✓ | ✓ |
| `workspace.manage_members` | | | ✓ | ✓ |
| `workspace.manage_invitations` | | | ✓ | ✓ |
| `workspace.manage_settings` | | | ✓ | ✓ |
| `workspace.manage_billing` | | | | ✓ |
| `workspace.delete` | | | | ✓ |

A view declares **either** `required_role` (simple ≥ hierarchy check via
`has_role_at_least`) **or** `required_capability` (fine-grained, via
`has_capability`); if neither is set, any member (VIEWER+) may proceed. Most
financial views use `WriteRequiresMemberMixin`
(`apps/common/api_base.py`), which derives the requirement from the HTTP
method: safe methods (GET/HEAD/OPTIONS) need VIEWER, anything that mutates
needs MEMBER — so one view class serves both without declaring two.

Seniority-relative actions (removing a member, changing someone's role) use
`outranks()` instead of a fixed capability: an admin can act on anyone with
strictly lower rank; owners may act on each other; nobody can grant a role
higher than their own; the last `OWNER` of a workspace can never be
demoted/removed (`LastOwnerError`).

**Resolution mechanics** (`apps/tenancy/permissions.py::IsTenantMember`):
reads `X-Tenant-ID`, looks up the caller's `Membership`, checks the role/
capability requirement, and — if authorized — sets `request.tenant_id` and
`request.membership` for the view and for `TenantScopedAPIView` to consume.
An unauthenticated request, a missing/malformed header, or an insufficient
role all fail this permission (403), before any tenant data is touched.

## Row-Level Security (the database backstop)

Full mechanics in [`ARCHITECTURE.md`](./ARCHITECTURE.md#multi-tenancy--row-level-security).
The short version for permission purposes: even if a view's RBAC check were
buggy, the database itself will not return rows for any tenant other than
the one bound to the current transaction via `SET LOCAL app.current_tenant`
— and an unbound connection gets zero rows, never all of them.

`bind_db_tenant()` is called automatically by `TenantScopedAPIView.initial()`
for every view that mixes it in. A view that needs tenant isolation and
forgets the mixin gets caught by pattern (all financial views do), and the
fail-closed RLS policy means a missed binding produces empty results rather
than a leak — visible immediately in testing, not a silent security hole.

## Non-RLS-protected data

`tenancy` (`Tenant`, `Membership`, `Invitation`) and `common`
(`OutboxEvent`, `AuditLog`) are deliberately outside RLS — see the "Not every
table is RLS-protected" note in `ARCHITECTURE.md`. Their isolation is
enforced by explicit `tenant=`/`tenant_id=` filters in `tenancy/selectors.py`
and service functions, checked by tests in `tests/test_tenancy.py` and
`tests/test_organizations.py`.

## Object-level checks beyond role

A sufficient role is necessary but not always sufficient — some endpoints
also check the object belongs to the caller's own workspace (e.g.
`change_member_role` raises `TenancyError` if the target membership's
`tenant_id` doesn't match the actor's) or that a resource is in an editable
state (e.g. `update_transaction` refuses to edit a voided transaction). These
checks live in the service layer, not the permission class, because they
depend on the specific object being acted on.

## Testing permissions

`tests/test_review_fixes.py` carries the adversarial cases every new
tenant-scoped endpoint should have an equivalent of:
`test_api_cross_tenant_isolation` (tenant B cannot see tenant A's data over
HTTP), `test_api_requires_tenant_membership` (a user with no membership in
the requested tenant is refused), `test_rls_fails_closed_without_tenant`
(direct-DB proof that an unbound tenant context yields zero rows). See
[`TESTING.md`](./TESTING.md).
