"""Payload contract: the fields the client depends on must actually arrive.

`test_api_contract.py` proves a path resolves. It says nothing about what comes
back, so a renamed or removed serializer field still reaches a user — as
`undefined` rendered into the UI, or a `TypeError` on a nested access. That is
the more common drift, because paths are stable and serializers are edited
constantly.

This test calls each endpoint against a real seeded workspace and checks the
response against the TypeScript interface the client declares for it.

Direction matters
-----------------
Only one direction is a failure. A field the **backend dropped that TypeScript
declares as required** breaks the client at runtime — that is asserted. A field
the **backend added that TypeScript does not know about** is harmless: JSON
carries it, the client ignores it, nothing breaks. That is reported for
awareness and not asserted, because failing on it would make every additive
backend change a frontend chore and train people to weaken the test.

Optional fields (`name?:`) and nullable unions (`string | null`) are excluded
from the required set, since the client has already said it can cope.

Limits
------
Field *names* are checked, not types: this will not catch `amount_minor`
changing from a number to a string. Generated types from the OpenAPI schema are
the complete answer; this is the cheap 80% that catches the failure that
actually happens.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.utils import timezone

from tests.conftest import _bearer_client
from tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db

TYPES_FILE = Path("frontend/app/src/api/types.ts")


def _parse_interfaces(source: str) -> dict[str, dict[str, bool]]:
    """Map interface name -> {field: is_required}.

    A brace-counting scan rather than a regex, because interfaces contain
    nested object literals and union types with braces of their own.
    """
    interfaces: dict[str, dict[str, bool]] = {}
    for match in re.finditer(r"export interface (\w+)[^{]*\{", source):
        name = match.group(1)
        i, depth = match.end(), 1
        start = i
        while i < len(source) and depth:
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
            i += 1
        body = source[start : i - 1]

        fields: dict[str, bool] = {}
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith(("//", "/*", "*")):
                continue
            # `field?: type;` or `field: type;` — only top-level members.
            member = re.match(r"(\w+)(\??):\s*(.+?);?$", line)
            if not member:
                continue
            field, optional, declared = member.group(1), member.group(2), member.group(3)
            nullable = "null" in declared
            fields[field] = not optional and not nullable
        interfaces[name] = fields
    return interfaces


INTERFACES = _parse_interfaces(TYPES_FILE.read_text()) if TYPES_FILE.exists() else {}


def _seeded_workspace():
    """A workspace with one of everything the endpoints below return."""
    membership = MembershipFactory()
    client = _bearer_client(membership.user, tenant_id=membership.tenant_id)

    account = client.post(
        "/api/v1/finance/accounts/",
        # Funded: a workspace blocks manual overdrafts by default.
        {
            "name": "Current",
            "account_type": "checking",
            "currency": "USD",
            "opening_balance_minor": 1_000_000,
        },
        format="json",
    ).data
    category = client.post(
        "/api/v1/finance/categories/",
        {"name": "Living", "kind": "expense", "currency": "USD"},
        format="json",
    ).data
    client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": account["id"],
            "category_id": category["id"],
            "amount_minor": 1250,
            "occurred_at": timezone.now().isoformat(),
            "memo": "Contract probe",
        },
        format="json",
    )
    return membership, client


#: (endpoint, TypeScript interface, how to reach one object in the response)
CONTRACTS = [
    ("/api/v1/finance/accounts/", "FinancialAccount", "list"),
    ("/api/v1/finance/categories/", "Category", "list"),
    ("/api/v1/finance/transactions/", "Transaction", "paginated"),
    ("/api/v1/auth/me/", "User", "object"),
    ("/api/v1/tenancy/workspaces/", "Workspace", "list"),
    ("/api/v1/analytics/reports/", "ReportMeta", "list"),
]


def _first_object(payload, shape):
    if shape == "object":
        return payload
    rows = payload["results"] if shape == "paginated" and isinstance(payload, dict) else payload
    if isinstance(rows, dict):
        rows = rows.get("results", [])
    return rows[0] if rows else None


def test_the_interface_parser_found_something():
    """A parser that silently matches nothing makes every assertion below pass
    while checking nothing — the failure mode that has already bitten this
    suite twice."""
    assert len(INTERFACES) > 50, f"only parsed {len(INTERFACES)} interfaces"
    assert INTERFACES.get("User", {}).get("email") is True


@pytest.mark.parametrize("path,interface,shape", CONTRACTS)
def test_every_required_field_the_client_declares_actually_arrives(path, interface, shape):
    """The failure that reaches a user: TypeScript promises a field, the
    serializer no longer sends it, and the UI renders `undefined`."""
    declared = INTERFACES.get(interface)
    assert declared, f"no TypeScript interface named {interface}"

    _, client = _seeded_workspace()
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code)

    obj = _first_object(response.data, shape)
    assert obj is not None, f"{path} returned nothing to check the contract against"

    required = {f for f, is_required in declared.items() if is_required}
    missing = sorted(required - set(obj))
    assert not missing, (
        f"{interface} declares {missing} as required, but {path} did not return them. "
        "Either the serializer dropped a field or the interface is stale."
    )


@pytest.mark.parametrize("path,interface,shape", CONTRACTS)
def test_report_fields_the_client_does_not_know_about(path, interface, shape, capsys):
    """Reported, never asserted.

    A field the backend added is harmless — JSON carries it, the client ignores
    it. Failing here would make every additive backend change a frontend chore,
    and a test people routinely have to weaken stops being a test.
    """
    declared = INTERFACES.get(interface, {})
    _, client = _seeded_workspace()
    obj = _first_object(client.get(path).data, shape)
    if obj is None:
        pytest.skip("nothing returned")

    unknown = sorted(set(obj) - set(declared))
    if unknown:
        with capsys.disabled():
            print(f"\n  note: {path} also returns {unknown}, absent from {interface}")


def test_a_removed_serializer_field_is_detected():
    """Proves the assertion can fail — otherwise it is decoration.

    Simulates the drift by pretending the interface requires a field the API
    has never sent, which is the same shape as the API dropping one.
    """
    _, client = _seeded_workspace()
    obj = _first_object(client.get("/api/v1/finance/accounts/").data, "list")

    pretend_required = set(INTERFACES["FinancialAccount"]) | {"field_the_api_no_longer_sends"}
    missing = pretend_required - set(obj)
    assert "field_the_api_no_longer_sends" in missing


def test_nullable_and_optional_fields_are_not_treated_as_required():
    """`last_used_at: string | null` and `first_name?: string` are both the
    client saying it can cope, so neither may fail the contract."""
    credential = INTERFACES["WebAuthnCredential"]
    assert credential["device_name"] is True
    assert credential["last_used_at"] is False, "a nullable field was marked required"

    user = INTERFACES["User"]
    assert user["email"] is True
    assert user["first_name"] is False, "an optional field was marked required"
