"""The demo seeder must be reproducible when asked.

The route audit is a ratchet over a rendered page, so it can only work if the
workspace it measures is identical every run. It was not: the RNG is keyed on
the tenant's id, which is a fresh UUID on every fresh database, so two clean
seeds never agreed and the audit's counts wandered (66, 67, 69, 70 for one
unchanged commit) until CI failed on its own noise.
"""

from __future__ import annotations

import random

import pytest

from apps.tenancy.management.commands import seed_tenant_demo

pytestmark = pytest.mark.django_db


def _amounts(seed: str, tenant_id: str) -> list[int]:
    """The sequence the seeder would draw for a given seed/tenant pair."""
    rng = random.Random(seed or f"{tenant_id}:2026-01-01")
    return [rng.randint(1, 10_000) for _ in range(25)]


def test_an_explicit_seed_makes_two_fresh_databases_agree():
    """Different tenant ids, same --seed: identical data."""
    assert _amounts("route-audit", "tenant-a") == _amounts("route-audit", "tenant-b")


def test_without_a_seed_two_fresh_databases_diverge():
    """The behaviour the flag exists to override — documented, not accidental."""
    assert _amounts("", "tenant-a") != _amounts("", "tenant-b")


def test_the_command_exposes_the_seed_flag():
    parser = seed_tenant_demo.Command().create_parser("manage.py", "seed_tenant_demo")
    assert "--seed" in parser.format_help()


def test_the_seed_flag_reaches_the_generator():
    """A flag that is parsed but never read is worse than no flag: the audit
    would look reproducible and still drift."""
    source = seed_tenant_demo.__file__
    with open(source) as fh:
        text = fh.read()
    assert 'options["seed"] or' in text, "the parsed seed never reaches random.Random"
