# LedgerFlow — Security Review

**Method.** Attacks, not configuration inspection. A setting can be correct and
still be bypassed by a code path that never consults it, so every claim below
was executed against a running system with seeded data. The 37 tests in
`tests/test_security_review.py` are written as attacks and named for what an
attacker would achieve if they passed.

**Verdict: no exploitable vulnerabilities found.** Two hardening defects were
found and fixed. Two areas need work before public launch (§5), and neither is
a hole an attacker walks through today.

---

## Findings

| ID | Severity | Area | Issue | Status |
|---|---|---|---|---|
| S-1 | Medium | API surface / CSRF | `SessionAuthentication` authenticated API **reads** from a cookie | **Fixed** |
| S-2 | Medium | Rate limiting | `development.py` silently disabled MFA throttling | **Fixed** |
| S-3 | Medium | Rate limiting | 135 of 154 API views declare no throttle scope | Open |
| S-4 | Low | Observability | Throttling cannot be observed in any environment a developer uses | Open |

---

## S-1 — cookie authentication on a JWT API (fixed)

`DEFAULT_AUTHENTICATION_CLASSES` listed `SessionAuthentication` alongside JWT.
Tested directly:

```
django session login succeeded : True
GET  via session cookie        : 200
POST via cookie, no CSRF token : 403   (CSRF enforced)
```

So writes were protected but **reads were not**. Any holder of a Django session
cookie could read financial data over the API without a bearer token.

Two things made this worse than it looks:

* `CORS_ALLOW_CREDENTIALS = True` in base settings. The origin allowlist is
  empty by default, so it is safe *as configured* — but the combination means a
  single future CORS mistake (a wildcard, a stale dev origin left in
  production, an attacker-controlled subdomain) converts directly into
  cross-origin reads of a household's finances. `development.py` already sets
  `CORS_ALLOW_ALL_ORIGINS = True`, so the unsafe pairing exists today in one
  environment.
* It bought nothing. `DEFAULT_RENDERER_CLASSES` is JSON-only, so there is no
  browsable API to serve — the usual reason to keep `SessionAuthentication`
  does not apply here.

**Fixed** by removing it, with the reasoning recorded in `base.py` so it is not
reinstated by habit. A test now asserts no `Session*` class appears in the
authentication chain, and a second asserts credentialed CORS is never paired
with a wildcard origin.

## S-2 — MFA throttling silently disabled in development (fixed)

`development.py` **replaced** the throttle-rates dict rather than merging into
it, and the replacement omitted `mfa_verify`:

```python
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {"auth": …, "write": …, "read": …}
```

A scope with no configured rate is not "unlimited" in any visible way — DRF
looks the rate up, finds nothing, and stops throttling that view. All five MFA
endpoints were therefore unprotected in development with nothing to indicate
it. The consequence is local-only, but the *shape* of the mistake is one a
production override could repeat exactly.

**Fixed** by merging into the base rates. A test now asserts every
`throttle_scope` string that appears anywhere in `apps/` has a rate configured
in **every** settings module — so the class of bug fails a test rather than
going unnoticed.

## S-3 — most of the API is unthrottled (open)

`ScopedRateThrottle` only applies to views that opt in with `throttle_scope`.
Measured across the codebase:

```
API views: 154   with throttle_scope: 19   without: 135
```

Authentication is well covered (login, register, password reset, MFA — 8 `auth`
+ 5 `mfa_verify` scopes). Almost nothing else is. Unthrottled views include
every analytics report, every debt projection, the payoff simulator and the
cashflow forecaster — the most computationally expensive endpoints in the
product.

The practical risk is resource exhaustion by an authenticated user or a leaked
token: not a data breach, but a cheap way to degrade the service for every
tenant on the same workers. It is a genuine availability gap rather than a
confidentiality one, which is why it is Medium rather than High.

**Recommendation:** set `throttle_scope = "read"` on the tenant-scoped base
view so coverage is inherited by default rather than remembered per view — the
same reasoning that makes `IsTenantMember` a base-class concern. The `read`
rate is already configured and currently unused.

## S-4 — the limiter is unobservable in practice (open)

Throttling is switched off in `test.py` (`DEFAULT_THROTTLE_CLASSES = []`) and
raised to 1000/min in `development.py`. Both choices are defensible on their
own; together they mean **no environment a developer or QA engineer touches
will ever exercise the limiter**. I flooded the login endpoint with 14 failed
attempts against the running dev server and saw fourteen 401s and no 429.

A control nobody can observe is a control nobody notices breaking. The test
added for S-2 partially covers this by driving `ScopedRateThrottle` directly,
but a staging environment running production rates would be better.

---

## What was tested and holds

### Multi-tenant isolation — the property the product depends on

| Attack | Result |
|---|---|
| Keep own JWT, swap `X-Tenant-ID` to a victim workspace | Rejected (403/404) |
| IDOR: write to a victim's account by UUID under a legitimate header | 404, object never appears in listings |
| Direct SQL with no tenant GUC bound | **0 rows** — fail-closed |
| Direct SQL with a forged tenant GUC | Only that tenant's rows |
| Enumerate workspaces the user does not belong to | Only own workspace returned |

The fail-closed RLS result is the one that matters most: it means a future bug
that forgets to scope a query returns nothing rather than everything. The
isolation guarantee does not depend on application code being correct.

### Authorisation and RBAC

Viewer cannot write (403). Member cannot promote themselves. Member cannot
invite above their own role. The last owner cannot be removed. A tenant owner —
however privileged in their own workspace — has no platform authority (403).

### Authentication

Argon2 in production (`test.py` swaps in MD5 for speed, which is why the
assertion targets base settings rather than a hash produced under test). Access
tokens 15 minutes, refresh 14 days, rotation with blacklist-after-rotation.

Forged tokens rejected: wrong signing key → 401; `alg: none` → 401; garbage →
401. Every one of eight representative endpoints across all modules rejects
anonymous requests.

Login does not leak account existence — wrong-password and no-such-user return
identical status and body.

### Injection

No raw SQL is built by string interpolation anywhere in `apps/` (the only
f-string `execute()` calls are migrations interpolating a hardcoded table
name). Four SQL payloads through the transaction search — including
`'; DROP TABLE finance_transaction; --` — execute as data; the table survives.
Ordering parameters are allowlisted rather than passed to `order_by`.

### Secrets and sensitive data

No credentials hardcoded; everything reads from the environment. Invitation
tokens are stored as SHA-256 hashes — a database dump yields no usable
workspace credential. TOTP secrets are encrypted at rest with
`FIELD_ENCRYPTION_KEY`, deliberately not `SECRET_KEY`. No endpoint returns a
password hash or token. Platform settings expose whether a secret is set and
never its value, and the platform audit log records that a secret changed
without recording what it changed to.

### XSS and CSRF

`dangerouslySetInnerHTML` appears **zero** times in the frontend. Stored script
payloads round-trip as JSON data, never as markup and never HTML-escaped
server-side (which would double-escape in React). With S-1 fixed the API is
header-authenticated only, which is what makes it structurally CSRF-resistant
rather than CSRF-*mitigated*.

### Transport and headers

`SECURE_SSL_REDIRECT`, HSTS at one year with `includeSubDomains` and `preload`,
`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_PROXY_SSL_HEADER`,
`X_FRAME_OPTIONS = DENY`, `SECURE_CONTENT_TYPE_NOSNIFF`.

---

## Corrections to my own findings

Eleven of the thirty-seven attacks failed on first run. **Eight were bugs in the
tests, not vulnerabilities.** Recorded because an unverified security finding is
worse than none — it burns the reader's trust and their afternoon:

* "Passwords are MD5-hashed" — `test.py` overrides the hasher for speed.
  Production is Argon2.
* "IDOR returns 405" — the account detail route exposes PATCH/DELETE, not GET.
  My probe used the wrong verb.
* "Workspace enumeration leak" — the endpoint returns *memberships* with a
  nested tenant; I compared against the membership id.
* "MFA secrets stored in plaintext" — the encrypted column is
  `encrypted_secret`; I read `secret`.
* "SQL injection succeeded" — the payload was handled correctly; my follow-up
  assertion used a tenant-scoped manager with no tenant bound.
* "Mass assignment" and "unknown UUID 500" — wrong manager name, wrong verb.
* "Login is not rate limited" — throttling is disabled in test settings and
  loosened to 1000/min in development. Real behaviour confirmed separately.

Only S-1 and S-2 survived verification.

---

## Not covered

- **No penetration testing.** This is a code-and-behaviour review; no fuzzing,
  no timing attacks, no dependency CVE scan.
- **No review of the deployed environment** — TLS configuration, WAF, secret
  storage at rest, database network exposure, backup encryption.
- **Business-logic abuse** beyond the RBAC cases tested: no attempt to
  manipulate money through legitimate-looking sequences of valid operations.
- **File upload security** — receipts accept uploads; content-type
  confusion, path traversal and malware scanning were not exercised.
- **The platform impersonation path** was reviewed by design in the
  platform-admin work but not attacked here.

Of these, a dependency CVE scan and file-upload testing are the two I would
prioritise, in that order.
