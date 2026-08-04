"""API responses must be unstorable by any cache.

Written after a production incident: with no cache directives at all, an
intermediary cache (Apache's mod_cache on a shared host, in front of
Cloudflare) stored the first, empty `GET /api/v1/tenancy/workspaces/` and
replayed it for every later request. The account had nine workspaces and the
app insisted it had none, because the request never reached Django again.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_api_responses_forbid_storage(client):
    resp = client.get("/api/v1/tenancy/workspaces/")
    assert "no-store" in resp.headers.get("Cache-Control", "")


def test_unauthenticated_api_errors_are_also_unstorable(client):
    """A cached 401 is as damaging as a cached 200: it pins a signed-out
    answer in front of a user who has since signed in."""
    resp = client.get("/api/v1/tenancy/workspaces/")
    assert resp.status_code == 401
    assert "no-store" in resp.headers.get("Cache-Control", "")


def test_the_directive_is_private_so_shared_caches_cannot_hold_it(client):
    resp = client.get("/api/v1/tenancy/workspaces/")
    assert "private" in resp.headers.get("Cache-Control", "")


def test_non_api_paths_are_left_alone(client):
    """Static assets and the health probes are cacheable by design; stamping
    no-store on everything would defeat the CDN for the SPA bundle."""
    resp = client.get("/healthz/")
    assert "no-store" not in resp.headers.get("Cache-Control", "")


def test_the_middleware_is_installed():
    from django.conf import settings

    assert "apps.common.middleware.NoStoreAPIMiddleware" in settings.MIDDLEWARE
