"""Continuous delivery: what CI publishes, and what the server will run.

The deploy used to build on the server. That box also hosts eight other
production sites, so every release compiled the SPA and installed Python
dependencies in competition with somebody else's live traffic. CI builds the
images now and the server pulls them, which also means the artifact that passed
the suite is the artifact that serves requests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

WORKFLOW = Path(".github/workflows/ci.yml")
COMPOSE = Path("deploy/docker-compose.server.yml")
AGENT = Path("deploy/cd-agent.sh")
INSTALLER = Path("deploy/install-cd.sh")


def _workflow() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(WORKFLOW.read_text())


# ------------------------------------------------------------------ publishing
def test_the_images_are_published_rather_than_discarded():
    source = WORKFLOW.read_text()
    assert "ghcr.io/${{ github.repository }}/app:${{ github.sha }}" in source
    assert "ghcr.io/${{ github.repository }}/frontend:${{ github.sha }}" in source


def test_a_pull_request_builds_but_publishes_nothing():
    """Otherwise any fork's PR could push an image the server might follow."""
    source = WORKFLOW.read_text()
    assert "github.ref == 'refs/heads/main'" in source
    assert "push: ${{ env.PUBLISH == 'true' }}" in source


def test_the_frontend_is_built_from_its_own_dockerfile():
    source = WORKFLOW.read_text()
    assert "file: deploy/frontend.Dockerfile" in source


# ------------------------------------------------------------------- promotion
def test_nothing_is_released_until_the_whole_pipeline_passes():
    jobs = _workflow()["jobs"]
    assert set(jobs["release"]["needs"]) == {"build", "route-audit"}
    # route-audit already gates on test+frontend, and build gates on test, so
    # those two edges transitively require every other job.
    assert "test" in jobs["route-audit"]["needs"]
    assert "frontend" in jobs["route-audit"]["needs"]
    assert jobs["build"]["needs"] == "test"


def test_the_approval_gate_exists():
    """`environment:` is what makes GitHub pause for a required reviewer. The
    reviewer list is repository configuration, but without this key there is
    nowhere for it to attach."""
    assert _workflow()["jobs"]["release"]["environment"] == "production"


def test_release_only_promotes_and_never_rebuilds():
    """A rebuild at promotion time would ship an artifact nothing tested."""
    source = WORKFLOW.read_text()
    release = source[source.index("\n  release:") :]
    assert "imagetools create" in release
    assert "build-push-action" not in release


def test_only_main_is_ever_promoted():
    assert "refs/heads/main" in _workflow()["jobs"]["release"]["if"]


# --------------------------------------------------------------------- compose
def test_the_server_runs_a_published_image():
    compose = COMPOSE.read_text()
    assert "${LEDGERFLOW_APP_IMAGE:-ghcr.io/oriokie/ledgerflow/app:released}" in compose
    assert "${LEDGERFLOW_FRONTEND_IMAGE:-ghcr.io/oriokie/ledgerflow/frontend:released}" in compose


def test_local_development_can_still_build_from_source():
    """Replacing `build:` outright would strip a developer's ability to run
    their working tree."""
    compose = COMPOSE.read_text()
    assert "build:" in compose
    assert "dockerfile: deploy/frontend.Dockerfile" in compose


def test_the_server_follows_a_tag_a_human_approved():
    """`:released` moves only in the gated job — following `:latest` or a
    branch tag would deploy whatever built most recently."""
    assert ":released" in COMPOSE.read_text()


# ----------------------------------------------------------------------- agent
def test_a_failed_deploy_is_rolled_back():
    """A broken release that stays broken until somebody notices is worse than
    one that never happened."""
    source = AGENT.read_text()
    assert "Rolling back" in source
    assert "previous_app" in source


def test_health_is_checked_through_the_real_hostname():
    """localhost proves the container started. It does not prove the proxy
    chain, the TLS termination or the Host header still work — which is where
    this deployment has actually broken before."""
    assert "https://$DOMAIN/healthz/" in AGENT.read_text()


def test_overlapping_runs_cannot_deploy_on_top_of_each_other():
    source = AGENT.read_text()
    assert "flock -n" in source


def test_the_agent_never_writes_env():
    """FIELD_ENCRYPTION_KEY lives there; regenerating it makes every stored MFA
    secret permanently unreadable."""
    source = AGENT.read_text()
    assert 'set -a; . "$REPO_DIR/.env"; set +a' in source, "should read .env"
    assert 'cat > "$REPO_DIR/.env"' not in source
    assert "openssl rand" not in source


def test_the_agent_honours_the_profiles_setup_chose():
    """Bringing the stack up with the wrong profiles would start Caddy on a box
    where something else already owns 80/443, or skip the bundled database."""
    source = AGENT.read_text()
    assert "COMPOSE_PROFILES" in source
    for profile in ("internal", "caddy", "bundled-db", "pgweb"):
        assert profile in source


def test_nothing_external_can_trigger_a_deploy():
    """The point of pull-based delivery on a shared host: no inbound access and
    no credential in GitHub that grants a shell where other people's sites run."""
    source = AGENT.read_text()
    assert "curl" in source  # health check only
    for inbound in ("nc -l", "socat", "listen", "webhook"):
        assert inbound not in source.lower().replace("# ", "")


def test_the_installer_can_remove_what_it_installed():
    source = INSTALLER.read_text()
    assert "--remove" in source
    assert "systemctl disable --now ledgerflow-cd.timer" in source


def test_the_installer_refuses_before_the_stack_is_configured():
    assert "No .env in $REPO_DIR" in INSTALLER.read_text()


def test_a_failed_pull_is_reported_not_swallowed():
    """The agent previously fell back to pulling everything and carried on
    regardless, so an unreachable registry, a private package the host cannot
    authenticate for, and a tag that does not exist yet were all indistinguish-
    able from "nothing to deploy". A CD agent that goes quiet looks identical to
    one with nothing to do."""
    source = AGENT.read_text()
    assert "Could not pull from the registry" in source
    assert "docker login ghcr.io" in source, "the likeliest cause should name its own fix"


def test_the_agent_pulls_services_that_exist():
    """`docker compose pull app` names no service in this file — the app runs as
    web/worker/beat — so the call always failed and fell through."""
    source = AGENT.read_text()
    assert "dc pull --quiet web worker beat frontend" in source


def test_no_unreachable_registry_guard_remains():
    """`docker manifest inspect | sha256sum` hashes empty input to a constant,
    so the emptiness check could never fire. A guard that cannot trigger is
    worse than none: it reads as covered."""
    source = AGENT.read_text()
    assert "sha256sum" not in source


# --------------------------------------------------------------- versioning
def test_both_images_record_the_commit_they_were_built_from():
    source = WORKFLOW.read_text()
    assert source.count("APP_RELEASE=${{ github.sha }}") == 2, "app and frontend both need it"


def test_the_frontend_bakes_the_version_into_the_bundle():
    """Fetching it would report the backend's version, and would keep reporting
    it confidently while a stale bundle sat in front — which is exactly when
    somebody goes looking for a version number."""
    dockerfile = Path("deploy/frontend.Dockerfile").read_text()
    assert "ARG APP_RELEASE" in dockerfile
    assert "ENV VITE_APP_RELEASE" in dockerfile
    # Baked before the build, or the bundle never sees it.
    assert dockerfile.index("ENV VITE_APP_RELEASE") < dockerfile.index("RUN npm run build")


def test_the_backend_keeps_its_release_for_error_reporting():
    assert "ENV APP_RELEASE" in Path("Dockerfile").read_text()
