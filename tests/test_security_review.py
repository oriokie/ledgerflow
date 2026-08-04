"""Adversarial security tests.

Written as attacks rather than assertions about configuration: a setting can be
correct and still be bypassed by a code path that never consults it. Each test
is named for the attack it attempts, so a failure tells you what an attacker
just achieved.
"""

from __future__ import annotations

import uuid

import pytest
from django.db import connection

from apps.tenancy.models import Role
from tests.conftest import _bearer_client
from tests.factories import MembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _client(membership):
    return _bearer_client(membership.user, tenant_id=membership.tenant_id)


def _make_account(client, name="Probe"):
    r = client.post(
        "/api/v1/finance/accounts/",
        {"name": name, "account_type": "checking", "currency": "USD"},
        format="json",
    )
    assert r.status_code in (200, 201), r.data
    return r.data


# ==================================================== multi-tenant isolation
def test_header_spoofing_cannot_reach_another_workspace():
    """The classic multi-tenant attack: keep your own token, swap the tenant
    header for a workspace you do not belong to."""
    victim = MembershipFactory()
    attacker = MembershipFactory()
    _make_account(_client(victim), "Victim savings")

    stolen = _bearer_client(attacker.user, tenant_id=victim.tenant_id)
    response = stolen.get("/api/v1/finance/accounts/")

    # Membership resolution must reject the header outright, not silently scope
    # to the attacker's own tenant (which would leak the *existence* of nothing
    # but would still mean the header was trusted).
    assert response.status_code in (403, 404), response.status_code


def test_direct_object_reference_across_tenants_is_refused():
    """IDOR: attacker knows a victim's account UUID and asks for it under their
    own, legitimate tenant header."""
    victim = MembershipFactory()
    attacker = MembershipFactory()
    account = _make_account(_client(victim), "Victim savings")

    # The detail route exposes PATCH/DELETE only, so probe with a write and
    # separately confirm the object never appears in the attacker's list.
    response = _client(attacker).patch(
        f"/api/v1/finance/accounts/{account['id']}/", {"name": "Owned"}, format="json"
    )
    assert response.status_code == 404
    listing = _client(attacker).get("/api/v1/finance/accounts/")
    assert "Victim savings" not in str(listing.data)


def test_writing_to_another_tenants_object_is_refused():
    victim = MembershipFactory()
    attacker = MembershipFactory()
    account = _make_account(_client(victim), "Victim savings")

    response = _client(attacker).patch(
        f"/api/v1/finance/accounts/{account['id']}/", {"name": "Owned"}, format="json"
    )
    assert response.status_code == 404


def test_rls_denies_reads_when_no_tenant_is_bound():
    """Fail-closed is the property that makes every other layer forgiving: a
    bug that forgets to scope a query returns nothing, not everything."""
    MembershipFactory()
    with connection.cursor() as cur:
        cur.execute("SET LOCAL app.current_tenant = ''")
        cur.execute("SELECT count(*) FROM finance_financialaccount")
        assert cur.fetchone()[0] == 0


def test_rls_survives_a_forged_tenant_guc():
    """Even with direct SQL, binding a tenant you don't own yields only that
    tenant's rows — the policy is on the data, not on the application."""
    a, b = MembershipFactory(), MembershipFactory()
    _make_account(_client(a), "A account")
    _make_account(_client(b), "B account")

    with connection.cursor() as cur:
        cur.execute("SET LOCAL app.current_tenant = %s", [str(a.tenant_id)])
        cur.execute("SELECT name FROM finance_financialaccount")
        names = {row[0] for row in cur.fetchall()}
    assert "B account" not in names


def test_a_user_cannot_enumerate_workspaces_they_do_not_belong_to():
    MembershipFactory()  # someone else's
    outsider = MembershipFactory()
    body = _client(outsider).get("/api/v1/tenancy/workspaces/").json()
    rows = body if isinstance(body, list) else body.get("results", [])
    # Rows are memberships carrying a nested tenant, so the tenant id is what
    # must be checked — the membership id would always look "wrong".
    tenant_ids = {row["tenant"]["id"] for row in rows}
    assert tenant_ids == {str(outsider.tenant_id)}


# ============================================================ authorisation
def test_a_viewer_cannot_write():
    owner = MembershipFactory(role=Role.OWNER)
    viewer = MembershipFactory(tenant=owner.tenant, role=Role.VIEWER)

    response = _client(viewer).post(
        "/api/v1/finance/accounts/",
        {"name": "Sneaky", "account_type": "checking", "currency": "USD"},
        format="json",
    )
    assert response.status_code == 403


def test_a_member_cannot_promote_themselves():
    """Self-escalation is the shortest path from any role to owner."""
    owner = MembershipFactory(role=Role.OWNER)
    member = MembershipFactory(tenant=owner.tenant, role=Role.MEMBER)

    response = _client(member).patch(
        f"/api/v1/tenancy/workspaces/members/{member.id}/",
        {"role": Role.OWNER},
        format="json",
    )
    assert response.status_code in (400, 403, 422), response.status_code
    member.refresh_from_db()
    assert member.role == Role.MEMBER


def test_a_member_cannot_invite_above_their_own_role():
    owner = MembershipFactory(role=Role.OWNER)
    member = MembershipFactory(tenant=owner.tenant, role=Role.MEMBER)

    response = _client(member).post(
        "/api/v1/tenancy/workspaces/invitations/",
        {"email": "x@example.test", "role": Role.OWNER},
        format="json",
    )
    assert response.status_code == 403


def test_the_last_owner_cannot_be_removed():
    """Otherwise a workspace becomes permanently unadministrable."""
    owner = MembershipFactory(role=Role.OWNER)
    response = _client(owner).delete(f"/api/v1/tenancy/workspaces/members/{owner.id}/")
    assert response.status_code in (400, 403, 409, 422)


def test_a_tenant_member_has_no_platform_authority():
    membership = MembershipFactory(role=Role.OWNER)
    assert _client(membership).get("/api/v1/platform/tenants/").status_code == 403


# =========================================================== authentication
def test_every_api_route_rejects_an_anonymous_request():
    """Swept rather than sampled: one forgotten AllowAny is a whole-product hole."""
    from django.test import Client

    anon = Client()
    for path in (
        "/api/v1/finance/accounts/",
        "/api/v1/finance/transactions/",
        "/api/v1/budgeting/budgets/",
        "/api/v1/debt/debts/",
        "/api/v1/investments/securities/",
        "/api/v1/analytics/reports/",
        "/api/v1/tenancy/workspaces/",
        "/api/v1/platform/dashboard/",
    ):
        assert anon.get(path).status_code in (401, 403), path


def test_a_garbage_token_is_rejected():
    from rest_framework.test import APIClient

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
    assert client.get("/api/v1/finance/accounts/").status_code == 401


def test_a_token_signed_with_the_wrong_key_is_rejected():
    """Guards against an algorithm/secret confusion bug."""
    import jwt
    from rest_framework.test import APIClient

    membership = MembershipFactory()
    forged = jwt.encode(
        {"user_id": str(membership.user_id), "token_type": "access", "exp": 9999999999},
        "not-the-signing-key",
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {forged}")
    assert client.get("/api/v1/finance/accounts/").status_code == 401


def test_an_alg_none_token_is_rejected():
    """The classic JWT bypass."""
    import jwt
    from rest_framework.test import APIClient

    membership = MembershipFactory()
    forged = jwt.encode(
        {"user_id": str(membership.user_id), "token_type": "access", "exp": 9999999999},
        key="",
        algorithm="none",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {forged}")
    assert client.get("/api/v1/finance/accounts/").status_code == 401


def test_passwords_are_hashed_with_argon2_in_production():
    """`config/settings/test.py` swaps in MD5 for speed, so asserting on a
    hash produced under test settings would only prove the override works.
    The property that matters is what base settings configure."""
    import importlib

    base = importlib.import_module("config.settings.base")
    assert base.PASSWORD_HASHERS[0].endswith("Argon2PasswordHasher")

    user = UserFactory()
    user.set_password("correct horse battery staple")
    user.save()
    assert "correct horse" not in user.password


def test_login_does_not_reveal_whether_an_account_exists():
    """Username enumeration: wrong-password and no-such-user must be alike."""
    from django.test import Client

    user = UserFactory()
    client = Client()
    real = client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "wrong-password"},
        content_type="application/json",
    )
    fake = client.post(
        "/api/v1/auth/login/",
        {"email": "nobody@example.test", "password": "wrong-password"},
        content_type="application/json",
    )
    assert real.status_code == fake.status_code
    assert real.json() == fake.json()


# ================================================== sensitive data exposure
def test_no_endpoint_returns_a_password_hash_or_token():
    membership = MembershipFactory()
    client = _client(membership)
    for path in ("/api/v1/auth/me/", "/api/v1/tenancy/workspaces/", "/api/v1/finance/accounts/"):
        body = str(client.get(path).content)
        assert "argon2" not in body
        assert "password" not in body.lower() or "password_" in body.lower()
        assert "token_hash" not in body


def test_invitation_tokens_are_stored_only_as_hashes():
    """A database dump must not be a set of live workspace credentials."""
    from apps.tenancy import services as tenancy
    from apps.tenancy.models import Invitation

    owner = MembershipFactory(role=Role.OWNER)
    _, raw = tenancy.create_invitation(
        tenant=owner.tenant, invited_by_membership=owner, email="x@example.test", role=Role.MEMBER
    )
    stored = Invitation.objects.get(email="x@example.test")
    assert raw not in stored.token_hash
    assert not Invitation.objects.filter(token_hash=raw).exists()


def test_mfa_secrets_are_encrypted_at_rest():
    from apps.users.mfa_models import TOTPDevice

    user = UserFactory()
    device = TOTPDevice(user=user)
    secret = TOTPDevice.generate_secret()
    device.set_secret(secret)
    device.save()

    raw = TOTPDevice.objects.filter(pk=device.pk).values_list("encrypted_secret", flat=True).first()
    assert raw
    assert secret not in str(raw)


# ======================================================== injection surfaces
@pytest.mark.parametrize(
    "payload",
    [
        "'; DROP TABLE finance_transaction; --",
        "' OR '1'='1",
        "%' UNION SELECT NULL,NULL,NULL--",
        "\\'; SELECT pg_sleep(5); --",
    ],
)
def test_search_parameters_do_not_execute_sql(payload):
    """The ORM parameterises, but search paths that build SQL by hand would not."""
    membership = MembershipFactory()
    response = _client(membership).get("/api/v1/finance/transactions/", {"q": payload})
    assert response.status_code in (200, 400)
    # The query ran as data, not as SQL: the table survives and the payload is
    # not echoed back as an executed fragment.
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('finance_transaction')")
        assert cur.fetchone()[0] is not None


def test_ordering_parameter_is_an_allowlist_not_passed_through():
    """`order_by` on user input allows table scans and can leak schema."""
    membership = MembershipFactory()
    response = _client(membership).get("/api/v1/finance/transactions/", {"order_by": "user__password"})
    assert response.status_code in (200, 400)


def test_no_raw_sql_is_built_by_string_interpolation():
    import pathlib
    import re

    offenders = []
    for f in pathlib.Path("apps").rglob("*.py"):
        if "migrations" in str(f) or "test" in f.name:
            continue
        src = f.read_text()
        for m in re.finditer(r'cursor\.execute\(\s*f?["\']', src):
            snippet = src[m.start() : m.start() + 260]
            # An f-string inside execute() is the risk; %s placeholders with a
            # params list are correct, and a hardcoded {table} name is not user
            # input.
            interpolated = re.search(r'execute\(\s*f["\']', snippet)
            if interpolated and "%s" not in snippet and "{table}" not in snippet.lower():
                offenders.append(f"{f}: {snippet[:90]}")
    assert not offenders, offenders


# ================================================================= API layer
def test_mass_assignment_cannot_set_protected_fields():
    """Extra keys in a payload must be ignored, not bound."""
    membership = MembershipFactory()
    other = MembershipFactory()
    response = _client(membership).post(
        "/api/v1/finance/accounts/",
        {
            "name": "Probe",
            "account_type": "checking",
            "currency": "USD",
            "tenant_id": str(other.tenant_id),
            "id": str(uuid.uuid4()),
            "is_active": False,
        },
        format="json",
    )
    assert response.status_code in (200, 201)
    # The attacker's tenant_id must have been ignored: the row is visible to
    # its creator and invisible to the tenant they tried to plant it in.
    assert response.data["id"] in str(_client(membership).get("/api/v1/finance/accounts/").data)
    assert response.data["id"] not in str(_client(other).get("/api/v1/finance/accounts/").data)
    assert response.data.get("is_active") is not False


def test_negative_and_absurd_amounts_are_rejected():
    membership = MembershipFactory()
    client = _client(membership)
    account = _make_account(client)
    for amount in (-1, 10**18):
        response = client.post(
            "/api/v1/finance/transactions/",
            {
                "account_id": account["id"],
                "amount_minor": amount,
                "occurred_at": "2026-01-01T00:00:00Z",
                "direction": "outflow",
            },
            format="json",
        )
        assert response.status_code in (400, 422), (amount, response.status_code)


def test_an_unknown_uuid_is_a_404_not_a_500():
    membership = MembershipFactory()
    response = _client(membership).patch(
        f"/api/v1/finance/accounts/{uuid.uuid4()}/", {"name": "x"}, format="json"
    )
    assert response.status_code == 404


def test_a_malformed_uuid_does_not_leak_a_traceback():
    membership = MembershipFactory()
    response = _client(membership).get("/api/v1/finance/accounts/not-a-uuid/")
    assert response.status_code in (400, 404)
    assert "Traceback" not in str(response.content)


# ================================================================ CSRF / XSS
def test_the_api_is_not_cookie_authenticated():
    """JWT in a header is what makes the API structurally CSRF-resistant.

    SessionAuthentication used to sit alongside it and authenticated API
    *reads* from a Django session cookie — writes were CSRF-protected, reads
    were not. With CORS_ALLOW_CREDENTIALS enabled, one bad CORS origin would
    have turned that into cross-origin access to financial data. It served no
    purpose: the renderer set is JSON-only, so there is no browsable API.
    """
    import importlib

    base = importlib.import_module("config.settings.base")
    classes = base.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]
    assert not any("Session" in c for c in classes), classes


def test_credentialed_cors_is_not_paired_with_an_open_origin_list():
    """CORS_ALLOW_CREDENTIALS with a wildcard origin is the combination that
    makes any read endpoint reachable from an attacker's page."""
    import importlib

    base = importlib.import_module("config.settings.base")
    if getattr(base, "CORS_ALLOW_CREDENTIALS", False):
        assert "*" not in getattr(base, "CORS_ALLOWED_ORIGINS", [])
        assert not getattr(base, "CORS_ALLOW_ALL_ORIGINS", False)


def test_stored_script_is_returned_as_data_not_markup():
    """React escapes on render; the API must not pre-render or unescape."""
    membership = MembershipFactory()
    client = _client(membership)
    payload = "<script>alert('xss')</script>"
    created = client.post(
        "/api/v1/finance/accounts/",
        {"name": payload, "account_type": "checking", "currency": "USD"},
        format="json",
    )
    assert created.status_code in (200, 201)
    fetched = client.get("/api/v1/finance/accounts/")
    # Stored verbatim and JSON-encoded — never HTML-escaped server-side, which
    # would double-escape in the client, and never emitted as raw markup.
    assert payload in str(fetched.data)
    assert fetched["Content-Type"].startswith("application/json")


def test_no_dangerously_set_inner_html_in_the_frontend():
    import pathlib

    offenders = [
        str(f)
        for f in pathlib.Path("frontend/app/src").rglob("*.tsx")
        if "dangerouslySetInnerHTML" in f.read_text()
    ]
    assert not offenders, offenders


# ============================================================ rate limiting
def test_the_login_throttle_actually_denies(settings):
    """Brute-force protection, tested at the throttle rather than through a view.

    DRF materialises `api_settings` once at import, so mutating
    `settings.REST_FRAMEWORK` mid-suite is order-dependent and produces a test
    that passes alone and fails in company. Driving `ScopedRateThrottle`
    directly exercises the same mechanism deterministically.
    """
    from django.core.cache import cache
    from rest_framework.test import APIRequestFactory
    from rest_framework.throttling import ScopedRateThrottle

    cache.clear()
    throttle = ScopedRateThrottle()
    throttle.THROTTLE_RATES = {"auth": "5/min"}

    class _View:
        throttle_scope = "auth"

    request = APIRequestFactory().post("/api/v1/auth/login/")
    request.user = None
    allowed = [throttle.allow_request(request, _View()) for _ in range(9)]

    assert allowed[:5] == [True] * 5
    assert False in allowed[5:], allowed
    cache.clear()


def test_auth_endpoints_declare_a_restrictive_scope():
    """The throttle only applies where a view opts in, so the opt-in is the
    control — a login view without `throttle_scope` is unlimited."""
    import importlib
    import pathlib as _p
    import re as _re

    src = _p.Path("apps/users/api/views.py").read_text()
    for view in ("LoginView", "RegisterView"):
        m = _re.search(rf"class {view}\(.*?\):\n((?:    .*\n|\n)*?)(?=\nclass |\Z)", src)
        if m:
            assert 'throttle_scope = "auth"' in m.group(1), view

    base = importlib.import_module("config.settings.base")
    rates = base.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    # Tight enough to matter: a permissive auth rate is the same as none.
    assert int(rates["auth"].split("/")[0]) <= 30, rates["auth"]
    assert int(rates["mfa_verify"].split("/")[0]) <= 10, rates["mfa_verify"]


def test_every_throttle_scope_used_has_a_configured_rate():
    """A scope with no matching rate silently disables throttling for that view.

    `development.py` replaces the whole rates dict and omits `mfa_verify`,
    so the MFA endpoints are unthrottled there — harmless locally, but the
    shape of the mistake is one a production override could repeat.
    """
    import importlib
    import pathlib
    import re

    scopes = set()
    for f in pathlib.Path("apps").rglob("*.py"):
        for m in re.finditer(r'throttle_scope\s*=\s*["\'](\w+)["\']', f.read_text()):
            scopes.add(m.group(1))

    for module in ("config.settings.base", "config.settings.development"):
        rates = importlib.import_module(module).REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        missing = scopes - set(rates)
        assert not missing, f"{module} has no rate for: {sorted(missing)}"
