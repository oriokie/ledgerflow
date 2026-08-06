"""Not part of the test suite — a one-shot smoke test proving the whole stack
wires together against the real dev database: registration, JWT auth,
workspace creation, tenant-scoped ledger writes, RLS isolation, error envelope,
request-id echo. Run with: python smoke_test.py
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
import django

django.setup()

from django.test import Client  # noqa: E402

client = Client()


def ok(cond, msg):
    print("PASS " if cond else "FAIL ", msg)


# 1. Register two separate users (they'll end up in separate tenants).
r1 = client.post(
    "/api/v1/auth/register/",
    {"email": "alice@example.com", "password": "correct-horse-battery-1"},
    content_type="application/json",
)
ok(r1.status_code == 201, f"register alice -> {r1.status_code} {r1.content[:200]}")

r2 = client.post(
    "/api/v1/auth/register/",
    {"email": "bob@example.com", "password": "correct-horse-battery-2"},
    content_type="application/json",
)
ok(r2.status_code == 201, f"register bob -> {r2.status_code}")

# 1b. Duplicate registration must be rejected with our error envelope shape.
dup = client.post(
    "/api/v1/auth/register/",
    {"email": "alice@example.com", "password": "correct-horse-battery-1"},
    content_type="application/json",
)
ok(dup.status_code == 400 and "error" in dup.json(), f"duplicate register -> {dup.status_code} {dup.json()}")

# 2. Login both, get JWTs. Confirm request-id header is echoed.
login1 = client.post(
    "/api/v1/auth/login/",
    {"email": "alice@example.com", "password": "correct-horse-battery-1"},
    content_type="application/json",
    HTTP_X_REQUEST_ID="test-req-alice",
)
ok(login1.status_code == 200, f"login alice -> {login1.status_code} {login1.content[:200]}")
ok(
    login1.headers.get("X-Request-ID") == "test-req-alice",
    f"request id echoed -> {login1.headers.get('X-Request-ID')}",
)
alice_access = login1.json()["access"]
alice_refresh = login1.json()["refresh"]

login2 = client.post(
    "/api/v1/auth/login/",
    {"email": "bob@example.com", "password": "correct-horse-battery-2"},
    content_type="application/json",
)
bob_access = login2.json()["access"]


def auth(token, tenant=None):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
    if tenant:
        headers["HTTP_X_TENANT_ID"] = str(tenant)
    return headers


# 3. Each creates their own workspace.
ws1 = client.post(
    "/api/v1/tenancy/workspaces/",
    {"name": "Alice Household", "base_currency": "USD"},
    content_type="application/json",
    **auth(alice_access),
)
ok(ws1.status_code == 201, f"alice create workspace -> {ws1.status_code} {ws1.content[:300]}")
alice_tenant = ws1.json()["tenant"]["id"]

ws2 = client.post(
    "/api/v1/tenancy/workspaces/",
    {"name": "Bob Household", "base_currency": "EUR"},
    content_type="application/json",
    **auth(bob_access),
)
ok(ws2.status_code == 201, f"bob create workspace -> {ws2.status_code}")
bob_tenant = ws2.json()["tenant"]["id"]

# 4. Missing tenant header -> permission denied via our custom exception handler.
no_tenant = client.get("/api/v1/ledger/accounts/", **auth(alice_access))
ok(
    no_tenant.status_code == 403 and "error" in no_tenant.json(),
    f"no tenant header -> {no_tenant.status_code} {no_tenant.json()}",
)

# 5. Baseline each tenant's accounts before Alice adds hers. Workspace creation
#    auto-seeds default category accounts, so the baseline count isn't 0 — but
#    it's the same set both before and after, which is what RLS isolation
#    actually promises.
bob_accs_before = client.get("/api/v1/ledger/accounts/", **auth(bob_access, bob_tenant)).json()
alice_accs_before = client.get("/api/v1/ledger/accounts/", **auth(alice_access, alice_tenant)).json()

# 6. Alice creates a ledger account inside her tenant (exercises RLS SET LOCAL + double-entry service).
acc1 = client.post(
    "/api/v1/ledger/accounts/",
    {"name": "Checking", "kind": "asset", "currency": "USD"},
    content_type="application/json",
    **auth(alice_access, alice_tenant),
)
ok(acc1.status_code == 201, f"alice create account -> {acc1.status_code} {acc1.content[:300]}")
alice_new_account_id = acc1.json()["id"]

# 7. Bob cannot see Alice's tenant's accounts even if (hypothetically) he guessed the tenant id,
#    because IsTenantMember checks membership before RLS is even reached.
cross = client.get("/api/v1/ledger/accounts/", **auth(bob_access, alice_tenant))
ok(cross.status_code == 403, f"bob probing alice's tenant -> {cross.status_code} {cross.json()}")

# 8. Bob lists accounts in HIS OWN tenant -> RLS must show none of Alice's rows,
#    and his own list must be untouched by what Alice just did.
bob_accs = client.get("/api/v1/ledger/accounts/", **auth(bob_access, bob_tenant))
bob_ids = {a["id"] for a in bob_accs.json()} if bob_accs.status_code == 200 else set()
ok(
    bob_accs.status_code == 200
    and alice_new_account_id not in bob_ids
    and bob_accs.json() == bob_accs_before,
    f"bob's tenant sees none of alice's accounts (RLS) -> {bob_accs.json()}",
)

# 9. Alice sees her own new account plus exactly what she had before it -- nothing more.
alice_accs = client.get("/api/v1/ledger/accounts/", **auth(alice_access, alice_tenant))
alice_ids = {a["id"] for a in alice_accs.json()} if alice_accs.status_code == 200 else set()
ok(
    alice_accs.status_code == 200
    and alice_new_account_id in alice_ids
    and len(alice_accs.json()) == len(alice_accs_before) + 1,
    f"alice sees her new account plus her prior {len(alice_accs_before)} -> {alice_accs.json()}",
)

# 10. Token refresh works. Rotation blacklists the old refresh and issues a new one.
refresh = client.post("/api/v1/auth/refresh/", {"refresh": alice_refresh}, content_type="application/json")
ok(refresh.status_code == 200 and "access" in refresh.json(), f"token refresh -> {refresh.status_code}")
rotated_refresh = refresh.json()["refresh"]

# 11. Logout blacklists the (rotated) refresh token; reusing it must fail.
logout = client.post(
    "/api/v1/auth/logout/",
    {"refresh": rotated_refresh},
    content_type="application/json",
    **auth(alice_access),
)
ok(logout.status_code == 204, f"logout -> {logout.status_code}")
reuse = client.post("/api/v1/auth/refresh/", {"refresh": rotated_refresh}, content_type="application/json")
ok(reuse.status_code == 401, f"blacklisted refresh rejected -> {reuse.status_code}")

# 12. Health check + OpenAPI schema are up.
health = client.get("/healthz/")
ok(health.status_code == 200, f"health check -> {health.status_code}")
schema = client.get("/api/schema/")
ok(schema.status_code == 200, f"openapi schema -> {schema.status_code}")

print("\nSmoke test complete.")
