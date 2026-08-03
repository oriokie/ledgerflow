# `users` — Identity & Authentication

Owns everything about *who* is making a request, independent of *which
workspace* they're acting in (that's `tenancy`). Email/password + MFA (TOTP)
+ WebAuthn/passkeys + OAuth social login, all issuing the same JWT tokens.

## Domain model

| Model | Purpose |
|---|---|
| `User` | Custom user model (`AUTH_USER_MODEL`), email as the login identifier, no username |
| `UserProfile` | Per-user, cross-workspace preferences: `locale`, `timezone`, `preferred_currency`, `last_active_tenant_id` |
| `TOTPDevice` | One per user; `encrypted_secret` (Fernet, via `apps.common.crypto`); `confirmed_at IS NULL` means enrollment in progress and unusable to satisfy a challenge |
| `MFABackupCode` | Single-use recovery codes, hashed with Argon2 (`make_password`/`check_password`) — function exactly like single-use passwords |
| `WebAuthnCredential` | A passkey: `credential_id`, `public_key` (COSE bytes), `sign_count` (clone-detection counter), `transports`, `backup_eligible`/`backup_state` |
| `SocialAccount` | Links a `User` to an OAuth provider's stable `sub` claim; a user may link several providers |
| `LoginEvent` | Auth audit trail — every login attempt (success or failure), `user` nullable since a failed attempt against a nonexistent email is still worth recording |

`User.is_verified` gates actions behind email verification (see
`apps.common.permissions.IsVerifiedUser`). Password hashing is Argon2 first,
PBKDF2 as fallback for pre-migration hashes (`PASSWORD_HASHERS` in settings)
— already-hashed passwords upgrade transparently on next successful login.

## Service layer

### `services/auth.py` — login orchestration

The core rule: **a user with a confirmed MFA method never gets real tokens
from a password check alone.**

- `authenticate_with_password(email, password, request)` → returns a `User`
  on full success, or raises `MFARequiredError` (carrying a signed,
  stateless challenge token) if the user has confirmed TOTP, or
  `InvalidCredentialsError` — deliberately the *same* exception whether the
  email doesn't exist or the password is wrong, to avoid leaking account
  existence.
- `issue_mfa_challenge(user)` / `resolve_mfa_challenge(mfa_token)` — the
  challenge is a `django.core.signing` payload (`{"user_id": ...}`,
  `MFA_CHALLENGE_TTL_SECONDS` max age), not a database row — stateless, works
  identically across any number of API replicas.
- `issue_tokens(user, request)` → `{"access", "refresh"}` via SimpleJWT,
  stamps `last_login_at`/`last_login_ip` (honoring `X-Forwarded-For`).

### `services/mfa.py` — TOTP enrollment & verification

Enroll → confirm → (optionally) disable, plus backup-code generation/
regeneration/consumption. A `TOTPDevice` only counts toward "MFA required" at
login once `confirmed_at` is set — enrollment alone (secret generated, QR
shown) doesn't lock anyone out if the user never finishes setup.

### `services/webauthn_service.py` — passkeys

Registration and authentication ceremonies (options → verify), backed by the
`webauthn` library. Challenges are cached (`cache.set`/`cache.get`, single-use,
`WEBAUTHN_CHALLENGE_TTL_SECONDS`) rather than stored in the DB. Clone detection:
`sign_count` must never *decrease* from a nonzero value — a persistently-zero
counter is treated as normal (common for platform authenticators using
synced/discoverable passkeys), but any decrease from nonzero rejects the
assertion outright.

### `services/oauth.py` — social login

Authorization-code flow with PKCE, provider config entirely from
`OAUTH_PROVIDERS` in settings (empty client_id/secret ⇒ that provider's
endpoints 404 gracefully). State is signed + cached (`OAUTH_STATE_TTL_SECONDS`)
to prevent CSRF on the callback. A successful callback still routes through
the same MFA-required check as password login if the linked user has
confirmed TOTP.

### `services/audit.py` — `record_login_event`

Called by every auth path (password, OAuth, WebAuthn) on both success and
failure — this is what populates `LoginEvent`.

## Key workflow: password login with MFA

```
POST /auth/login/  {email, password}
  -> authenticate_with_password()
     -> TOTP confirmed?  raise MFARequiredError(mfa_token, methods=["totp", ...])
        response: 401 {"mfa_token": "...", "methods": [...]}   (no real tokens yet)
     -> not confirmed?  issue_tokens()  ->  200 {"access", "refresh"}

POST /auth/mfa/verify/  {mfa_token, code}
  -> resolve_mfa_challenge(mfa_token)  -> User
  -> verify TOTP code (or backup code)
  -> issue_tokens()  ->  200 {"access", "refresh"}
```

## API

Base path `/api/v1/auth/`.

| Method | Path | Purpose | Throttle scope |
|---|---|---|---|
| `POST` | `/register/` | Create account | `auth` |
| `POST` | `/login/` | Password login (may return an MFA challenge instead of tokens) | `auth` |
| `POST` | `/refresh/` | Rotate access token (SimpleJWT `TokenRefreshView`) | — |
| `POST` | `/logout/` | Blacklist the refresh token | — |
| `GET` | `/me/` | Current user + profile | — |
| `POST` | `/mfa/verify/` | Exchange an MFA challenge + code for real tokens | `mfa_verify` |
| `POST` | `/mfa/totp/enroll/` | Generate a TOTP secret + provisioning URI | — |
| `POST` | `/mfa/totp/confirm/` | Confirm enrollment with a valid code; issues backup codes | — |
| `POST` | `/mfa/totp/disable/` | Requires a valid code to disable | — |
| `POST` | `/mfa/backup-codes/regenerate/` | Invalidates old codes, issues new ones | — |
| `POST` | `/webauthn/register/options/` | Begin passkey registration | — |
| `POST` | `/webauthn/register/verify/` | Complete passkey registration | — |
| `GET` | `/webauthn/credentials/` | List the user's passkeys | — |
| `DELETE` | `/webauthn/credentials/<id>/` | Remove a passkey | — |
| `POST` | `/webauthn/authenticate/options/` | Begin passwordless login | — |
| `POST` | `/webauthn/authenticate/verify/` | Complete passwordless login → tokens | — |
| `GET` | `/oauth/<provider>/authorize/` | Redirect to provider | — |
| `GET` | `/oauth/<provider>/callback/` | Exchange code for tokens → LedgerFlow tokens | — |

## Permissions

`users` endpoints are not tenant-scoped (identity predates workspace
selection) — they use plain `IsAuthenticated`/`AllowAny`, not `IsTenantMember`.
Throttling is the primary defense here: `THROTTLE_AUTH` (10/min default) on
login/register/refresh, `THROTTLE_MFA_VERIFY` (5/min default, tighter — the
brute-force target) on MFA code verification.

## Configuration

`FIELD_ENCRYPTION_KEY` (required for TOTP), `JWT_ACCESS_MINUTES`,
`JWT_REFRESH_DAYS`, `MFA_*`, `WEBAUTHN_*`, `OAUTH_*` — see
[`../CONFIGURATION.md`](../CONFIGURATION.md).

## Extension points

- **New OAuth provider**: add an entry to `OAUTH_PROVIDERS`, no code change
  — see [`../EXTENSION_POINTS.md`](../EXTENSION_POINTS.md).
- **SMS MFA**: documented as a deferred extension — would add a new
  `LoginMethod` choice and a service module mirroring `services/mfa.py`'s
  shape (challenge issue/verify), reusing the same `MFARequiredError` flow.

## Testing

`tests/test_auth.py`, `tests/test_mfa.py`, `tests/test_webauthn.py`,
`tests/test_oauth.py`. Covers: password auth, MFA-required gating, backup
code single-use, TOTP disable requiring a valid code, WebAuthn registration/
authentication including forged-signature rejection and clone detection
(stale sign-count), OAuth login still gating on existing MFA. See
[`../TESTING.md`](../TESTING.md#a-note-on-flakiness-and-its-real-cause) for
why these tests depend on the autouse cache-clearing fixture.
