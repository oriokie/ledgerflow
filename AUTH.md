# LedgerFlow — Authentication & SaaS foundations

Covers: email auth, OAuth, passkeys, MFA, user profiles, organizations/
households, RBAC, invitations, tenant isolation. Every claim below was run
against real PostgreSQL 16 + Redis 7 — see "Verification" at the bottom.

## Identity model

`apps/users` owns identity (a person), `apps/tenancy` owns workspaces (where
they act). A `User` authenticates once; a `Membership` links them to zero or
more `Tenant`s, each with a `Role`. `UserProfile` (locale/timezone/currency/
avatar/phone) lives in `users`, not `tenancy` — it describes the person, not
a workspace, and doesn't vary per-tenant. This DDD boundary was actually
wrong in the previous iteration (`UserProfile` sat in `tenancy`) and is
corrected here.

## Password authentication

- Argon2id first in `PASSWORD_HASHERS` (memory-hard, GPU-crack-resistant),
  PBKDF2 kept only as a fallback verifier for pre-migration hashes — Django
  transparently re-hashes to Argon2 on next successful login.
- Minimum 12-character passwords, Django's standard validator stack
  (similarity, common-password, numeric-only) plus the length floor.
- Login and registration errors are deliberately identical
  ("Invalid email or password") whether the account doesn't exist or the
  password is wrong — no account-enumeration oracle.
- Every login attempt — success or failure, and by which method — is
  recorded in `LoginEvent` (email attempted, IP, user agent, reason), even
  for emails that don't match any account.

## MFA (TOTP + backup codes)

`apps/users/mfa_models.py`, `apps/users/services/mfa.py`.

- RFC 6238 TOTP. The shared secret is **encrypted at rest** with Fernet
  (`apps/common/crypto.py`), keyed by `FIELD_ENCRYPTION_KEY` — deliberately
  **not** `SECRET_KEY`, so rotating one can never silently corrupt the other.
  Verified: `test_totp_secret_is_encrypted_at_rest`.
- Enrollment requires confirmation: `TOTPDevice.confirmed_at IS NULL` means
  "in progress, not yet trusted" — a code must be verified against it before
  it can ever gate a login. Prevents a UI bug or race from activating an MFA
  device the user never actually saw.
- 10 single-use backup codes (Argon2-hashed, same as passwords) are issued on
  confirmation and on explicit regeneration; each is destroyed on use.
- **Login is a two-step exchange, not a boolean check.** `POST /auth/login/`
  with a correct password for an MFA-enabled account returns **no usable
  tokens** — only a short-lived (`MFA_CHALLENGE_TTL_SECONDS`, default 300s),
  HMAC-signed challenge token (`django.core.signing`, stateless — no DB row,
  works identically across any number of API replicas). That token must be
  exchanged at `POST /auth/mfa/verify/` with a TOTP or backup code before
  real tokens are issued. Verified: `test_login_with_mfa_enabled_requires_second_step`
  asserts `"access" not in login.data` on the first call.
- `mfa/totp/disable/` and `backup-codes/regenerate/` both require a **fresh**
  valid code — a hijacked session can't silently strip MFA protection.
- The MFA-verify endpoint has its own tight throttle scope (`mfa_verify`,
  default 5/min) — separate from general auth throttling, since a 6-digit
  TOTP code is a realistic brute-force target (1,000,000 space, but only
  ~2 valid codes at any moment given the validity window).

## Passkeys (WebAuthn)

`apps/users/webauthn_models.py`, `apps/users/services/webauthn_service.py`.

Built on `webauthn` (py_webauthn) doing real COSE/CBOR parsing and ECDSA
signature verification — not a stub. Passkey login is **passwordless and
bypasses the MFA step entirely**: a verified assertion already proves
possession (the private key never left the authenticator) plus, when
`userVerification` succeeds, inherence/knowledge (biometric or PIN) — it's
phishing-resistant by construction, which password+TOTP is not (both are
phishable).

- Challenge state is ephemeral, stored in **Redis**, never a server session
  (the API is stateless JWT auth). Registration ceremonies key by user id
  (already authenticated both times); authentication ceremonies key by an
  opaque `state` token returned from the options call and echoed back on
  verify, since the caller isn't authenticated yet.
- Supports both constrained (`allow_credentials`, email supplied) and
  discoverable/usernameless (`resident_key=PREFERRED`, no email) ceremonies.
- **Clone detection**: a genuine authenticator's sign counter only
  increases. A persistently-zero counter (common for synced/platform
  passkeys) is treated as normal; any *decrease* from a nonzero value raises
  `CloneDetectedError` and the login is rejected.
- Every challenge is single-use — deleted from cache on first verification
  attempt, success or failure, so a captured request can't be replayed.

**Verified with a real cryptographic authenticator, not a mock**:
`tests/webauthn_fixtures.py::SoftAuthenticator` generates a genuine ECDSA
P-256 keypair, builds real CBOR attestation objects and ASN.1 DER signatures
— exactly what a hardware key does. Tests prove: registration + login
round-trip, wrong-origin rejection, replayed-challenge rejection,
**forged-signature rejection** (a credential ID that matches a real
registration but signed by a *different* private key is rejected — the core
security property of WebAuthn), and clone detection via sign-count
regression.

## OAuth / social login

`apps/users/services/oauth.py`. Hand-rolled against the standard
authorization-code + PKCE flow rather than a heavy SDK — small,
security-critical surface, worth owning directly. Providers
(`OAUTH_PROVIDERS`) are entirely config-driven; an unconfigured provider's
endpoints fail closed with a clear error rather than a broken redirect.

- **PKCE** (S256) on every authorization request — `code_verifier` generated
  and cached server-side, `code_challenge` sent to the provider, verifier
  sent back on token exchange. Prevents authorization-code interception.
- **State** is the CSRF defense: generated per-authorize-call, stored in
  Redis with the PKCE verifier, single-use (deleted on first callback
  regardless of outcome), and validated before any provider call is made.
- **Account linking is deliberately conservative**: linking to an existing
  LedgerFlow account by email only happens if the provider asserts
  `email_verified: true`. An unverified email claim that matches an existing
  account is **rejected outright** (`EmailAlreadyRegisteredError`), not
  silently linked and not silently duplicated (impossible anyway — email is
  globally unique) — this is exactly the class of OAuth account-takeover bug
  where an attacker with an unverified email at a lenient provider could
  otherwise hijack an existing account. This was caught by testing against
  the real database's unique constraint, not designed in from the start —
  see "Verification" below.
- OAuth login still respects an existing MFA enrollment (defense in depth):
  if the resulting user has confirmed TOTP, the callback returns an MFA
  challenge instead of tokens, same as password login.

## Organizations & households

A single `Tenant` model with a `type` (`personal` / `household` /
`organization`) rather than parallel schemas per kind. They differ in policy
and presentation, not in the isolation mechanism — duplicating the
substantial RLS + service-layer isolation machinery per tenant "kind" would
be pure cost with no corresponding benefit. `billing_email` and future
org-specific fields live on the same model, nullable/blank for personal use.

## RBAC

`apps/tenancy/rbac.py`. Fixed role hierarchy (VIEWER < MEMBER < ADMIN <
OWNER) with an explicit **capability** mapping (`ledger.write`,
`workspace.manage_members`, `workspace.manage_billing`, ...) rather than
scattering `role == "admin"` checks through the codebase. `has_capability`
is the seam a future custom-roles system would plug into without touching
call sites — deliberately not built now: custom per-tenant roles are a real
feature but a materially bigger one (role CRUD, migrating existing
memberships on role edit/delete, a UI for building permission sets).

Two authorization rules that only became visible under real testing:
- **Self-service actions bypass the manage-members capability.** A VIEWER
  can always remove themselves from a workspace — leaving shouldn't require
  a permission you don't have. (Caught by `test_member_can_remove_self`.)
- **Owners can act on peer owners**, an explicit exception to "only
  strictly-senior actors may act on someone" — co-owners need to be able to
  manage each other (e.g. incident response), and OWNER is the ceiling of
  the hierarchy so "strictly senior" is otherwise unsatisfiable between two
  owners. (Caught by `test_can_demote_owner_if_another_owner_exists`.)
- **A workspace can never be left without an owner** — `LastOwnerError` on
  the last owner's removal or demotion attempt, checked inside the same
  atomic transaction as the mutation.

## Invitations

`apps/tenancy/models.py::Invitation`, `apps/tenancy/services.py`. Adding a
member is **always** invite-then-accept, never a direct "add this existing
user" action — nobody joins a financial workspace without consenting.

- The raw invitation token is returned to the caller (and emailed) exactly
  **once**, at creation; only its SHA-256 hash is persisted. A leaked DB
  dump is not enough to accept someone else's invitation — same at-rest
  discipline as passwords and MFA backup codes.
  Verified: `test_invitation_token_is_hashed_at_rest`.
- An inviter can never grant a role higher than their own
  (`test_admin_cannot_invite_someone_as_owner`), and only ADMIN+ may invite
  at all.
- Acceptance validates: not expired, not already accepted/revoked, the
  accepting user's email matches the invited email exactly, and the user
  isn't already a member — each independently tested.
- Invitation emails send **asynchronously via Celery** (`apps/tenancy/tasks.py`)
  so a slow mail provider never blocks the API request; verified against a
  real Celery worker connected to real Redis (see "Verification").
- `Invitation` (like `Membership`/`Tenant`) is **not** RLS-protected — it's
  tenancy control-plane data written and read around the edges of a tenant
  context (an invitee has no membership yet), not user financial data.
  Isolation is enforced at the service/permission layer instead, same
  reasoning as documented in `apps/ledger/migrations/0002_financial_integrity.py`.

## Tenant isolation

Unchanged from the existing foundation, extended to cover every new
RLS-eligible table: Postgres Row-Level Security, bound per-request via
`TenantScopedAPIView` (`SET LOCAL app.current_tenant` inside
`transaction.atomic()`, so it's guaranteed to unwind even on an exception).
MFA devices, WebAuthn credentials, and OAuth links are **not** tenant-scoped
at all — they belong to a `User`, not a `Tenant`, and are the same across
every workspace that user belongs to.

## Global scalability & security summary

| Concern | Approach |
|---|---|
| No server-side session state | JWT bearer tokens; ephemeral ceremony state (WebAuthn challenges, OAuth PKCE/state) in Redis, not process memory — works identically behind any number of stateless API replicas |
| Horizontal scaling | UUIDv7 PKs (index-friendly under high concurrent insert), stateless auth, Redis-backed rate limiting |
| Secrets at rest | Argon2 passwords, Argon2 backup codes, Fernet-encrypted TOTP secrets, hashed invitation tokens — nothing sensitive stored reversibly-plaintext except by deliberate, documented exception |
| Brute-force resistance | Scoped throttles: `auth` (10/min), `mfa_verify` (5/min), tighter than general `write`/`read` |
| Account takeover via OAuth | Verified-email-only auto-linking; unverified claims against an existing account rejected outright |
| Credential replay | Every WebAuthn/OAuth challenge and state value is single-use, deleted on first use regardless of outcome |
| Audit trail | `LoginEvent` for every auth attempt (any method, success or failure); existing `OutboxEvent`/`AuditLog` for workspace/membership/invitation changes |

## Verification

Run against real PostgreSQL 16 and Redis 7 in the environment building this:

- **93 tests passed**, 91% coverage (`pytest -q`), including:
  - 12 MFA tests (real `pyotp` codes, real Argon2-hashed backup codes)
  - 12 WebAuthn tests using a **real synthetic ECDSA P-256 authenticator** —
    genuine `verify_registration_response`/`verify_authentication_response`
    crypto, including a forged-signature rejection test and clone detection
  - 12 OAuth tests (real PKCE/state logic, mocked provider HTTP)
  - 23 organizations/RBAC tests (the full capability table, parametrized)
  - 15 invitation lifecycle tests
  - plus the pre-existing ledger, tenancy, and auth suites, updated where
    the API surface intentionally changed (direct member-add replaced by
    invite-then-accept)
- **Three real bugs found and fixed by testing against real infrastructure**,
  not by inspection:
  1. An unverified-email OAuth callback for an already-registered address
     crashed on the DB unique constraint instead of being cleanly rejected
     → `EmailAlreadyRegisteredError`.
  2. Self-removal from a workspace was blocked by the manage-members
     capability check, contradicting the intended "you can always leave"
     rule → self-service actions now bypass that check.
  3. An owner couldn't demote a peer owner (no one strictly outranks an
     owner) → owners now have an explicit peer-management exception.
- `ruff check` and `black --check`: clean.
- `manage.py check --deploy` against production settings: **zero issues**.
- `manage.py makemigrations --check`: no drift.
- A real Celery worker, connected to real Redis, executed
  `apps.tenancy.tasks.send_invitation_email` end-to-end (console-rendered
  email with correct recipient, workspace name, role, and accept URL).
- `requirements/development.txt` installs cleanly in an isolated venv.

## Known follow-ups (deliberately deferred, not forgotten)

- Custom per-tenant roles (beyond the fixed VIEWER/MEMBER/ADMIN/OWNER
  hierarchy) — `has_capability` is the designed seam, not built.
- Live OAuth round-trip against real Google/Apple requires real client
  credentials, which don't exist in this environment; the service layer is
  tested against realistic mocked provider responses instead.
- Phone-based MFA (SMS/WhatsApp OTP) — `UserProfile.phone_number` and
  `phone_verified` exist as fields but no send/verify flow is wired yet;
  SMS OTP is also weaker than TOTP/WebAuthn (SIM-swap risk), so it's a
  deliberately lower priority.
- Invitation auto-surfacing at registration time (detecting a pending
  invite for the email being registered) is not implemented; acceptance is
  a separate authenticated step.
