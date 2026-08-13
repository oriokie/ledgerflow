"""docker/entrypoint.sh — runs before every container start (web, worker,
beat), gated on RUN_MIGRATIONS so only the container actually responsible
for schema changes (see docs/DEPLOYMENT.md) does them on every deploy.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ENTRYPOINT = Path("docker/entrypoint.sh")


def test_the_script_parses():
    result = subprocess.run(["sh", "-n", str(ENTRYPOINT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_it_seeds_the_plan_catalogue_on_every_deploy():
    """setup.sh also seeds plans, but only on a manual (re-)run — a redeploy
    through the CD agent never invokes it. Without this in the automatic
    startup path, a fresh environment's Plan table stays empty forever, and
    every new workspace's best-effort start_trial call silently fails: the
    sidebar plan card and Upgrade button render nothing, with no error
    anywhere a human would see it."""
    source = ENTRYPOINT.read_text()
    assert "seed_plans" in source


def test_the_catalogue_is_seeded_after_migrations_not_before():
    """seed_plans writes Plan rows; running it before the table exists on a
    genuinely fresh database would fail the whole container boot."""
    source = ENTRYPOINT.read_text()
    assert source.index("manage.py migrate") < source.index("seed_plans")


def test_seeding_is_gated_on_run_migrations_not_unconditional():
    """Only the container running migrations should also own seeding — every
    worker/beat replica doing it too is redundant (if harmless, since
    seed_plans is idempotent) work on every restart. Proven by position: the
    call sits between the RUN_MIGRATIONS check and the next distinct gate
    (COLLECT_STATIC), not before or after that block."""
    source = ENTRYPOINT.read_text()
    assert (
        source.index('RUN_MIGRATIONS" = "true"')
        < source.index("seed_plans")
        < source.index('COLLECT_STATIC" = "true"')
    )
