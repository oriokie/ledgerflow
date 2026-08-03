"""Shared fixtures for the whole suite. Kept intentionally small — most tests
should build exactly what they need via factories, not a kitchen-sink fixture."""

from __future__ import annotations

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tests.factories import MembershipFactory, UserFactory


@pytest.fixture(autouse=True)
def _clear_cache_between_tests():
    """Root-cause fix for the intermittent MFA/WebAuthn/OAuth failures: the test
    cache is LocMemCache, which persists across tests in the same process.
    Those flows store single-use challenges keyed by user id; without clearing,
    a challenge from one test could collide with another's, producing failures
    that looked like 'Redis flakiness' but were really cache-state bleed. Clear
    before and after every test so each starts from a clean cache."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _restore_migration_seeded_data(django_db_setup, django_db_blocker):
    """Keep migration-seeded reference data alive across transactional tests.

    A `django_db(transaction=True)` test flushes every table on teardown, and
    the flush does not spare rows written by data migrations — here, the FX
    rates from `fx/0002_seed_rates`. Every subsequent test in the session then
    sees an empty rate table, and because pytest.ini sets `--reuse-db` the loss
    persists into the *next* run as well. The symptom is FX tests that pass on
    a fresh database and fail on the second invocation, which reads as
    flakiness and is not.

    Django's own answer, `serialized_rollback=True`, does not help: it restores
    at the start of the next *transactional* test, leaving the ordinary tests
    in between looking at an empty table.

    So the seed is re-applied here instead. The check is a single cheap
    `EXISTS` on a table with a few dozen rows, and it runs only when something
    has actually wiped them.
    """
    import importlib
    from decimal import Decimal

    from django.utils import timezone

    from apps.fx.models import ExchangeRate

    with django_db_blocker.unblock():
        if not ExchangeRate.objects.filter(source="seed").exists():
            # Read the rates from the migration itself rather than duplicating
            # them here, so the two can never disagree.
            seed_module = importlib.import_module("apps.fx.migrations.0002_seed_rates")
            now = timezone.now()
            ExchangeRate.objects.bulk_create(
                [
                    ExchangeRate(
                        base_currency="USD",
                        quote_currency=quote,
                        as_of=now,
                        source="seed",
                        rate=Decimal(rate),
                    )
                    for quote, rate in seed_module.SEED.items()
                ],
                ignore_conflicts=True,
            )
    yield


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def user(db):
    return UserFactory()


def _bearer_client(user, tenant_id=None) -> APIClient:
    client = APIClient()
    token = RefreshToken.for_user(user).access_token
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
    if tenant_id is not None:
        headers["HTTP_X_TENANT_ID"] = str(tenant_id)
    client.credentials(**headers)
    return client


@pytest.fixture
def auth_client(user) -> APIClient:
    """Authenticated, but with no workspace/tenant header — for testing the
    endpoints that don't need one, and the ones that correctly reject its absence."""
    return _bearer_client(user)


@pytest.fixture
def tenant_context(db):
    """A user who owns a workspace, plus a ready-to-use authenticated client
    with the X-Tenant-ID header already set. Covers the common case."""
    membership = MembershipFactory()
    client = _bearer_client(membership.user, tenant_id=membership.tenant_id)
    return membership, client
