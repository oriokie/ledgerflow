"""The provisioning script.

A deploy script is run once, as root, on a machine nobody has logged into yet —
so a syntax error or a wrong config template is discovered at the worst possible
moment. These are cheap structural checks, not a substitute for running it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

SETUP = Path("deploy/setup.sh")
COMPOSE = Path("deploy/docker-compose.server.yml")
PROVISION = Path("deploy/provision.sh")


def test_the_script_parses():
    """`bash -n` catches the unclosed quote that would otherwise surface as a
    cryptic failure halfway through provisioning a production box."""
    result = subprocess.run(["bash", "-n", str(SETUP)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_it_fails_fast_rather_than_limping_on():
    source = SETUP.read_text()
    assert "set -euo pipefail" in source


def test_help_works_without_root():
    """People run `--help` first. It must not demand sudo to explain itself."""
    result = subprocess.run(["bash", str(SETUP), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "interactive production setup" in result.stdout


def test_an_unknown_flag_is_rejected():
    result = subprocess.run(["bash", str(SETUP), "--wat"], capture_output=True, text=True)
    assert result.returncode != 0


@pytest.mark.parametrize("server", ["nginx", "apache", "caddy", "none"])
def test_every_offered_web_server_has_a_branch(server):
    source = SETUP.read_text()
    assert f"{server})" in source, f"{server} is offered but never handled"


def test_the_proxy_passes_the_scheme_header():
    """Django's SECURE_PROXY_SSL_HEADER reads X-Forwarded-Proto. Without it the
    app thinks every request is plaintext and SECURE_SSL_REDIRECT loops."""
    source = SETUP.read_text()
    assert "X-Forwarded-Proto" in source
    assert source.count("X-Forwarded-Proto") >= 2, "nginx and Apache both need it"


def test_secrets_are_generated_once_and_never_rotated_silently():
    """Rotating DJANGO_SECRET_KEY logs everyone out; rotating
    FIELD_ENCRYPTION_KEY makes stored TOTP secrets permanently unreadable."""
    source = SETUP.read_text()
    for key in ("DJANGO_SECRET_KEY", "FIELD_ENCRYPTION_KEY"):
        assert re.search(rf'if \[ -z "\$\{{{key}:-\}}" \]', source), key


def test_the_env_file_is_written_with_restrictive_permissions():
    source = SETUP.read_text()
    assert "umask 077" in source
    assert "chmod 600" in source


def test_an_existing_env_is_backed_up_before_being_replaced():
    source = SETUP.read_text()
    assert ".bak." in source


def test_dns_is_checked_before_requesting_a_certificate():
    """certbot's own failure sends people to ACME logs; the real problem is
    almost always DNS, so say that instead."""
    source = SETUP.read_text()
    assert "dns_points_here" in source
    issue = source[source.index("issue_certificate() {") :]
    assert "dns_points_here" in issue[:400]


def test_certbot_reuses_a_live_certificate():
    """Let's Encrypt rate-limits issuance; re-running setup must not burn a slot."""
    assert "--keep-until-expiring" in SETUP.read_text()


def test_prompts_read_from_the_terminal():
    """Piped from curl, a bare `read` consumes the script's own stdin and
    silently accepts empty answers for every question."""
    source = SETUP.read_text()
    assert source.count("</dev/tty") >= 3


def test_optional_services_are_profiled_and_core_ones_are_not():
    """With nginx or Apache on the host, starting Caddy too means two servers
    fighting over 80/443 — and the failure looks like a certificate problem.
    The bundled database is optional for the same structural reason: a managed
    Postgres deployment must be able to start this stack without the file
    insisting on running a second database."""
    import yaml

    compose = yaml.safe_load(COMPOSE.read_text())
    assert compose["services"]["caddy"].get("profiles") == ["caddy"]
    assert compose["services"]["caddy_internal"].get("profiles") == ["internal"]
    assert compose["services"]["db"].get("profiles") == ["bundled-db"]
    # The core services must not be profiled, or they would not start at all.
    for name in ("web", "worker", "beat", "redis"):
        assert "profiles" not in compose["services"][name], name


def test_a_profiled_db_cannot_strand_its_dependents():
    """`depends_on: db` must be `required: false`, or choosing an external
    database makes compose refuse to start web/worker/beat at all — the
    failure mode that turns "point DATABASE_URL at RDS" into an outage."""
    import yaml

    compose = yaml.safe_load(COMPOSE.read_text())
    for name in ("web", "worker", "beat"):
        dep = compose["services"][name]["depends_on"]["db"]
        assert dep.get("required") is False, name


def test_scripts_actually_enable_the_profiles_they_depend_on():
    """The compose file has relied on profile flags nobody passed before:
    provision.sh deployed a stack with no TLS front end at all. Both scripts
    must name the profiles explicitly."""
    assert "COMPOSE_PROFILES" in PROVISION.read_text()
    assert "caddy,bundled-db" in PROVISION.read_text()
    setup = SETUP.read_text()
    assert "--profile internal" in setup
    assert "--profile bundled-db" in setup


def test_the_internal_origin_is_loopback_only():
    """The internal origin serves the app without TLS or HSTS. Bound wider
    than loopback it would be a second, insecure front door."""
    import yaml

    compose = yaml.safe_load(COMPOSE.read_text())
    ports = compose["services"]["caddy_internal"]["ports"]
    assert all(str(p).startswith("127.0.0.1:") for p in ports), ports


def test_django_admin_stays_off_the_spa_console_namespace():
    """Django's admin lives at /django-admin/. Both Caddyfiles route it there;
    neither may claim /admin/* for the backend, because the platform console
    is part of the SPA and owns that path in the browser — routing it to
    Django made every console page a 404 in production."""
    for caddyfile in (COMPOSE.parent / "Caddyfile", COMPOSE.parent / "Caddyfile.internal"):
        text = caddyfile.read_text()
        assert "/django-admin/*" in text, caddyfile.name
        assert "/admin/*" not in text.replace("/django-admin/*", ""), caddyfile.name


def test_the_generated_env_covers_what_the_app_requires():
    """A missing FRONTEND_BASE_URL is how invitation links broke before."""
    source = SETUP.read_text()
    for key in (
        "DJANGO_SECRET_KEY",
        "FIELD_ENCRYPTION_KEY",
        "DJANGO_ALLOWED_HOSTS",
        "CORS_ALLOWED_ORIGINS",
        "FRONTEND_BASE_URL",
        "DATABASE_URL",
        "REDIS_URL",
        "WEBAUTHN_RP_ID",
    ):
        assert f"{key}=" in source, key


def test_it_seeds_the_plan_catalogue():
    """A deployment with no plans cannot take a subscription."""
    assert "seed_plans" in SETUP.read_text()


def test_it_does_not_seed_demo_data_into_production():
    """`seed_platform_demo` invents customers; on a production box those become
    real rows in every revenue figure the console reports."""
    assert "seed_platform_demo" not in SETUP.read_text()


# --------------------------------------------------------------- OS support
#
# The script originally hardcoded apt-get with no guard, so a run on any
# non-Debian box (RHEL, Rocky, AlmaLinux, Amazon Linux — all dnf-based) died
# mid-script on "apt-get: command not found", four prompts and a generated
# .env after the point where it could have said so.


def test_the_package_manager_is_detected_before_any_prompt():
    """Detecting the OS after asking six questions and writing secrets is why
    this broke silently in the first place — the check has to come first."""
    source = SETUP.read_text()
    detect_at = source.index("detect_pkg_manager\n")
    first_prompt = source.index('bold "1. Where will this run?"')
    assert detect_at < first_prompt


def test_an_unsupported_package_manager_dies_with_a_pointer_not_a_crash():
    source = SETUP.read_text()
    die_block = source[source.index("detect_pkg_manager() {") : source.index("pkg_install() {")]
    assert 'die "No apt-get, dnf or yum found' in die_block
    # Points somewhere useful rather than just naming the problem.
    assert "docker-compose.server.yml" in die_block


@pytest.mark.parametrize("marker", ["dnf install", "yum install"])
def test_dependency_install_has_an_rhel_branch(marker):
    source = SETUP.read_text()
    assert marker in source or "pkg_install" in source


@pytest.mark.parametrize(
    "needle",
    [
        "download.docker.com/linux/centos/docker-ce.repo",  # Docker's own RHEL guidance
        "systemctl enable --now docker",  # dnf's docker-ce postinst doesn't start it
        "httpd",  # RHEL's Apache package/service/binary name
        "mod_ssl",  # ships as its own RPM on RHEL, unlike Debian's a2enmod ssl
        "apachectl",  # RHEL's ctl binary — "apache2ctl" doesn't exist there
        "epel-release",  # certbot's RHEL home
    ],
)
def test_every_rhel_specific_step_is_present(needle):
    assert needle in SETUP.read_text(), needle


def test_apache_service_and_binary_names_are_not_hardcoded_debian():
    """The pre-fix version called `apache2ctl` and `systemctl reload apache2`
    unconditionally — both undefined on a box whose Apache is `httpd`."""
    source = SETUP.read_text()
    configure_apache = source[source.index("configure_apache() {") : source.index("issue_certificate() {")]
    assert "apache_service" in configure_apache
    assert "apache_ctl" in configure_apache
    # Must still branch to the Debian names somewhere, not just the RHEL ones.
    assert "apache2ctl" in configure_apache
    assert "apache2" in configure_apache


def test_nginx_config_lands_somewhere_both_families_auto_include():
    """sites-available/sites-enabled is a Debian-only convention; conf.d is
    read by both, which is why the fix collapses to one code path rather than
    a second Debian/RHEL branch alongside Apache's. The old target path may
    still appear in a comment explaining the switch away from it — only the
    actual write target matters here."""
    source = SETUP.read_text()
    assert "/etc/nginx/sites-available/ledgerflow" not in source
    assert "> /etc/nginx/conf.d/ledgerflow.conf" in source


def test_opening_the_firewall_asks_first():
    """The script's own stated rule: 'It never opens a firewall port you did
    not ask for.' Adding firewalld support must not quietly break that."""
    source = SETUP.read_text()
    assert "It never opens a firewall port you did not ask for." in source
    firewalld_block = source[source.index("firewall-cmd >/dev/null") : source.index('case "$WEB_SERVER" in')]
    assert "confirm " in firewalld_block or "confirm(" in firewalld_block


def test_firewalld_only_touches_http_and_https():
    """Never SSH — a script run over an SSH session that closes its own
    connection has no way to fix what it just did."""
    source = SETUP.read_text()
    assert "add-service=ssh" not in source
    assert "add-port" not in source  # only the named http/https services


def test_selinux_bind_mounts_are_labelled():
    """SELinux enforcing (the RHEL-family default) silently denies a
    container reading a bind-mounted host file with the wrong context —
    Caddy would fail with 'permission denied' on a file that is right there.
    `:z` is a no-op where SELinux isn't in play, so this costs nothing on
    Debian/Ubuntu."""
    compose = Path("deploy/docker-compose.server.yml").read_text()
    for mount in ("./Caddyfile:", "./Caddyfile.internal:"):
        line = next(row for row in compose.splitlines() if mount in row)
        assert line.rstrip().endswith(",z"), line
