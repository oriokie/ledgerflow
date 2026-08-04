"""The isolation check has to look where the rows actually are.

Its read-back — bind tenant A, confirm tenant B's rows are invisible — only
means something if some table holds rows. Finding one has to happen *bound to a
tenant*: with nothing bound, every policy returns zero rows, which is the
fail-closed behaviour working correctly. Searching unbound therefore reported a
busy production database as empty and skipped the check on exactly the
deployment where it had just been switched on for the first time.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from apps.finance import services as finance_services
from apps.finance.models import AccountType
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


def _run() -> str:
    out = StringIO()
    call_command("verify_tenant_isolation", stdout=out)
    return out.getvalue()


def test_it_reports_configuration_regardless_of_data():
    output = _run()
    assert "subject to RLS" in output or "tenant isolation enabled and forced" in output


def test_an_empty_database_says_so_without_claiming_success():
    """Vacuous success is worse than an honest skip — it tells an operator the
    property holds when nothing was tested."""
    output = _run()
    assert "vacuously" in output
    assert "no workspaces exist yet" in output


def test_a_workspace_with_rows_is_found_and_read_back():
    """The regression: rows existed, the search ran unbound, saw nothing, and
    reported the database empty.

    The rows have to sit under a registered workspace, which is the only shape
    production ever has — tenant data always belongs to a row in
    `tenancy_tenant`, because that is what a workspace *is*."""
    from apps.tenancy.models import Tenant

    tenant = Tenant.objects.create(name="Real", type="personal", base_currency="USD")
    with tenant_scope(tenant.id):
        finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )

    output = _run()
    assert "vacuously" not in output, "rows exist; the read-back must not be skipped"
    assert "isolation is enforced" in output.lower() or "visible" in output.lower()


def test_workspaces_without_rows_are_described_accurately():
    """A workspace that exists but holds nothing is a different state from no
    workspaces at all, and an operator reading this needs to tell them apart."""
    from apps.tenancy.models import Tenant

    Tenant.objects.create(name="Empty", type="personal", base_currency="USD")

    output = _run()
    assert "hold no rows yet" in output


def test_it_searches_bound_to_a_tenant():
    """Pins the mechanism, because the symptom only shows on a database whose
    role cannot bypass RLS — a superuser sees the rows either way, so a local
    run would not notice this regressing."""
    from pathlib import Path

    text = Path("apps/tenancy/management/commands/verify_tenant_isolation.py").read_text()
    probe_block = text[text.index("probe = None") :][:900]
    assert "bind_db_tenant" in probe_block, "the search runs unbound and will find nothing"
