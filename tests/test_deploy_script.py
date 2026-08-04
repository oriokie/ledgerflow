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


# ------------------------------------------------- already-occupied ports 80/443
# A box that already serves other sites (cPanel, Plesk, a hand-rolled multi-site
# host) is the case that failed worst in practice: Caddy was offered and chosen,
# six prompts and a written .env later `docker compose up` died on "bind:
# address already in use", and the recovery involved understanding profiles.
def test_port_conflicts_are_detected_before_the_first_prompt():
    """Detection after the prompts is detection too late — the whole point is
    to change which options are offered."""
    source = SETUP.read_text()
    assert "detect_port_conflict()" in source
    detect_call = source.index("detect_port_conflict\n")
    assert detect_call < source.index("ask WEB_SERVER"), "must run before the web server question"


def test_caddy_is_refused_when_something_already_owns_the_ports():
    source = SETUP.read_text()
    validator = source[source.index("valid_webserver_free_ports() {") :][:600]
    assert "$PORTS_IN_USE" in validator
    assert "caddy" in validator
    assert "return 1" in validator


def test_a_stored_caddy_answer_is_not_reused_once_the_ports_are_taken():
    """Re-runs pre-fill from .env. Defaulting to an answer that can no longer
    work just reproduces the original failure on every subsequent run."""
    source = SETUP.read_text()
    assert '[ "$_ws_default" = caddy ] && _ws_default=existing' in source


def test_the_existing_web_server_option_is_offered_and_handled():
    source = SETUP.read_text()
    assert "existing)" in source, "offered but never dispatched"
    assert "configure_existing() {" in source


def test_existing_mode_writes_no_web_server_config():
    """The whole reason this mode exists: a control panel owns those vhosts and
    regenerates them, and other people's sites share the daemon."""
    source = SETUP.read_text()
    body = source[source.index("configure_existing() {") : source.index('bold ""\nbold "Configuring')]
    for destructive in ("cat > /etc", "a2ensite", "systemctl reload", "systemctl restart", "rm -f /etc"):
        assert destructive not in body, f"configure_existing must not run: {destructive}"


def test_existing_mode_prints_config_for_all_three_front_ends():
    source = SETUP.read_text()
    body = source[source.index("configure_existing() {") :][:2500]
    assert "proxy_pass" in body, "nginx snippet missing"
    assert "ProxyPass " in body, "Apache vhost snippet missing"
    assert "RewriteRule" in body and "[P,L]" in body, ".htaccess snippet missing"


def test_existing_mode_never_issues_a_certificate():
    """TLS already terminates on the existing server. Running certbot would at
    best duplicate its certificate and at worst disrupt a live one — and the
    DNS pre-check would reject a Cloudflare-proxied domain outright."""
    source = SETUP.read_text()
    body = source[source.index("configure_existing() {") :][:2500]
    assert "issue_certificate" not in body


def test_existing_mode_leaves_the_firewall_alone():
    """Whatever already answers on 80/443 publicly has working rules; touching
    them is unnecessary risk on a box hosting other people's sites."""
    source = SETUP.read_text()
    assert '[ "$WEB_SERVER" != existing ]' in source


def test_the_internal_origin_pins_the_public_host_header():
    """Apache rewrites Host to the backend address unless ProxyPreserveHost is
    on — and that directive is forbidden in .htaccess, so shared hosting simply
    cannot set it. Django then rejected every request against ALLOWED_HOSTS
    with a blank 400. The origin serves one site, so the Host is known."""
    caddyfile = Path("deploy/Caddyfile.internal").read_text()
    assert "header_up Host {env.DOMAIN}" in caddyfile
    assert "header_up X-Forwarded-Host {env.DOMAIN}" in caddyfile


def test_the_internal_caddy_is_given_the_domain_it_pins():
    """The Caddyfile reads {env.DOMAIN}; unset, it would pin an empty Host."""
    compose = COMPOSE.read_text()
    internal = compose[compose.index("caddy_internal:") : compose.index("frontend:\n    # Builds")]
    assert "DOMAIN: ${DOMAIN" in internal


# ---------------------------------------------------------------- database access
def test_the_bundled_database_is_reachable_for_ordinary_work():
    """Inspecting the database is where 'did that actually save?' gets
    answered. Container-network-only means every such question needs
    `docker exec` gymnastics."""
    compose = COMPOSE.read_text()
    # Anchored on the service key at the start of a line: "  db:" also matches
    # the `db: {condition: service_healthy}` dependency inside the shared
    # x-app-build anchor, which would slice an empty string and pass nothing.
    db = compose[compose.index("\n  db:\n") : compose.index("\n  redis:\n")]
    assert "ports:" in db, "the bundled database publishes nothing"
    assert ':5432"' in db, "nothing maps through to Postgres' port"


@pytest.mark.parametrize("service,port", [("\n  db:\n", "5432"), ("\n  pgweb:\n", "8081")])
def test_database_ports_are_loopback_only(service, port):
    """0.0.0.0 would put Postgres — and pgweb, which has no authentication at
    all — on the public internet. The SSH tunnel is the authentication."""
    compose = COMPOSE.read_text()
    body = compose[compose.index(service) :][:1400]
    published = [row for row in body.splitlines() if f":{port}" in row and "-" in row]
    assert published, f"{service} publishes no {port} line"
    for row in published:
        assert "127.0.0.1:" in row, f"{row.strip()} must bind loopback only"


def test_pgweb_is_optional():
    """A credential-free full-SQL console should not run on a box nobody is
    actively inspecting."""
    compose = COMPOSE.read_text()
    pgweb = compose[compose.index("\n  pgweb:\n") :]
    assert 'profiles: ["pgweb"]' in pgweb
    source = SETUP.read_text()
    assert "--profile pgweb" in source
    assert "ENABLE_PGWEB" in source


def test_pgweb_is_only_started_when_asked_for():
    source = SETUP.read_text()
    assert '[ "${ENABLE_PGWEB:-0}" -eq 1 ] && PROFILES=' in source


def test_the_env_symlink_makes_manual_compose_commands_work():
    """Compose interpolates ${VAR} from a .env in the compose file's own
    directory. Without the link, every documented Day-2 `docker compose -f
    deploy/...` command fails on a missing DOMAIN before it starts."""
    source = SETUP.read_text()
    assert 'ln -sf ../.env "$REPO_ROOT/deploy/.env"' in source


def test_help_survives_the_header_growing():
    """A fixed sed line range silently truncates --help every time a bullet is
    added to the header, which is how it stops mentioning the newest feature."""
    source = SETUP.read_text()
    assert "sed -n '2,25p'" not in source
    result = subprocess.run(["bash", str(SETUP), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "existing" in result.stdout, "--help must mention the shared-server path"


# ------------------------------------------------- occupied ports beyond 80/443
# The 80/443 preflight above was written after a real failure; the same class of
# failure then recurred on the same box for 5432, because a host already running
# Postgres for something else owns it. A bind that fails only once the rest of
# the stack is up reads as "the deploy broke", not "one port was spoken for".
def test_every_loopback_published_port_is_configurable():
    """A hard-coded host port cannot be moved out of the way without editing a
    tracked file, which is the thing a deployment must not require."""
    compose = COMPOSE.read_text()
    for var, default in (
        ("POSTGRES_HOST_PORT", "5432"),
        ("PGWEB_HOST_PORT", "8081"),
        ("INTERNAL_HTTP_PORT", "8080"),
    ):
        assert f"${{{var}:-{default}}}" in compose, f"{var} is not overridable"


@pytest.mark.parametrize("default", ["5432", "8081", "8080"])
def test_no_host_port_is_published_as_a_bare_literal(default):
    compose = COMPOSE.read_text()
    assert (
        f'"127.0.0.1:{default}:' not in compose
    ), f"port {default} is published literally; a busy host cannot move it"


def test_a_taken_port_is_stepped_over_rather_than_hit():
    source = SETUP.read_text()
    assert "pick_free_port() {" in source
    assert "port_is_free() {" in source
    # The picker must actually advance, or it returns the busy port forever.
    picker = source[source.index("pick_free_port() {") :][:600]
    assert "candidate=$((candidate + 1))" in picker


def test_port_selection_happens_before_env_is_written():
    """Compose interpolates the published ports out of .env. A port chosen
    after the heredoc closes is a port compose never sees."""
    source = SETUP.read_text()
    env_write_end = source.index("\nENVEOF")
    for var in ("keep_or_pick POSTGRES_HOST_PORT", "keep_or_pick INTERNAL_HTTP_PORT"):
        assert source.index(var) < env_write_end, f"{var} is chosen too late to be written"


@pytest.mark.parametrize("var", ["POSTGRES_HOST_PORT", "PGWEB_HOST_PORT", "INTERNAL_HTTP_PORT"])
def test_chosen_ports_are_persisted_for_later_compose_runs(var):
    """Day-2 `docker compose` runs re-read .env. A port that only existed in
    the script's memory means the next manual command binds the wrong one."""
    source = SETUP.read_text()
    env_body = source[source.index('cat > "$ENV_FILE"') : source.index("\nENVEOF")]
    assert f"{var}=" in env_body


def test_the_proxy_snippet_uses_the_port_actually_chosen():
    """Printing 8080 while binding 8081 sends the operator to a dead upstream."""
    source = SETUP.read_text()
    assert 'APP_UPSTREAM="127.0.0.1:${INTERNAL_HTTP_PORT}"' in source


def test_a_port_check_that_cannot_run_does_not_block_the_deploy():
    """Neither ss nor netstat present is not a reason to refuse to install."""
    source = SETUP.read_text()
    checker = source[source.index("port_is_free() {") :][:500]
    assert "return 0" in checker.split("else")[-1], "must assume free when it cannot tell"


# ------------------------------------------------------- unprivileged app role
# PostgreSQL exempts superusers from row-level security unconditionally and
# silently. The bundled database's POSTGRES_USER is one, so connecting the app
# as it produced a deployment that looked entirely normal and had no tenant
# isolation at all — the single most serious defect this script could ship.
def test_the_app_does_not_connect_as_the_database_superuser():
    source = SETUP.read_text()
    assert "postgres://ledgerflow_app:" in source, "DATABASE_URL still uses the superuser"
    assert "postgres://ledgerflow:${POSTGRES_PASSWORD}@db" not in source


@pytest.mark.parametrize("attribute", ["NOSUPERUSER", "NOBYPASSRLS"])
def test_the_app_role_cannot_bypass_row_level_security(attribute):
    """Both are required: NOSUPERUSER alone still leaves BYPASSRLS grantable,
    and either one being absent silently disables every policy."""
    assert attribute in SETUP.read_text()


def test_the_role_is_created_before_the_app_connects():
    """web's entrypoint opens a connection as soon as it starts; a role created
    afterwards means the first boot fails authentication."""
    source = SETUP.read_text()
    assert source.index("CREATE ROLE ledgerflow_app") < source.index("up -d --build")


def test_creating_the_role_twice_is_not_an_error():
    """setup.sh is documented as idempotent and people re-run it to deploy."""
    source = SETUP.read_text()
    assert "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ledgerflow_app')" in source


def test_an_existing_install_grants_the_role_rights_on_tables_it_does_not_own():
    """Upgrades have tables already owned by the superuser. Without this the
    switch-over produces permission denied on every query."""
    source = SETUP.read_text()
    assert "ON ALL TABLES IN SCHEMA public TO ledgerflow_app" in source
    assert "ALTER DEFAULT PRIVILEGES" in source


def test_the_role_password_is_generated_not_fixed():
    source = SETUP.read_text()
    assert 'APP_DB_PASSWORD="${APP_DB_PASSWORD:-$(openssl rand -hex 24)}"' in source


def test_the_role_password_survives_a_rerun():
    """Re-running must not mint a new password while the role keeps the old
    one — that locks the app out of its own database."""
    source = SETUP.read_text()
    env_body = source[source.index('cat > "$ENV_FILE"') : source.index("\nENVEOF")]
    assert "APP_DB_PASSWORD=" in env_body


# ---------------------------------------------- migrations under the app role
# Switching DATABASE_URL to an unprivileged role broke the very next deploy:
# `permission denied for table tenancy_tenant`, while a migration added a
# foreign key to it. DML grants let the app read and write rows; a migration is
# DDL, and altering a table requires owning it.
def test_the_app_role_owns_the_tables_it_has_to_migrate():
    source = SETUP.read_text()
    assert "ALTER TABLE public.%I OWNER TO ledgerflow_app" in source


@pytest.mark.parametrize("kind", ["pg_tables", "pg_sequences", "pg_views"])
def test_ownership_covers_every_object_kind_a_migration_touches(kind):
    """Sequences back every id column and views are rebuilt by migrations too;
    transferring only tables leaves the next migration failing on those."""
    assert kind in SETUP.read_text()


def test_ownership_transfer_runs_before_the_app_starts():
    """web's entrypoint migrates on boot, so ownership has to be settled before
    the stack comes up — afterwards is one failed deploy too late."""
    source = SETUP.read_text()
    assert source.index("OWNER TO ledgerflow_app") < source.index("up -d --build")


def test_owning_the_tables_does_not_hand_back_rls_bypass():
    """Postgres exempts a table's owner from its policies *unless* the table is
    FORCE'd. The migrations do that, and this pins the pairing: if the forcing
    ever stopped, ownership transfer would silently disable isolation."""
    forced = list(Path("apps").glob("*/migrations/*.py"))
    assert any(
        "FORCE ROW LEVEL SECURITY" in p.read_text() for p in forced
    ), "no migration forces RLS; transferring ownership would disable it"
    source = SETUP.read_text()
    assert "NOSUPERUSER" in source and "NOBYPASSRLS" in source
    # And the deploy proves it rather than trusting this reasoning.
    assert "verify_tenant_isolation" in source


# --------------------------------------------------- two picks, two ports
# Nothing is bound until the containers start, so two independent picks in one
# run both saw the same port as free and both took it. pgweb won the race and
# caddy_internal died on "port is already allocated" — after every other
# container had already started.
def _run_picker(script: str) -> subprocess.CompletedProcess:
    """Drive the real functions out of setup.sh rather than a copy of them."""
    harness = f"""
set -euo pipefail
warn() {{ :; }}
eval "$(sed -n '/^PICKED_PORTS=""/,/^$/p' {SETUP})"
eval "$(sed -n '/^port_is_free() {{/,/^}}/p' {SETUP})"
eval "$(sed -n '/^pick_free_port() {{/,/^}}/p' {SETUP})"
eval "$(sed -n '/^keep_or_pick() {{/,/^}}/p' {SETUP})"
PICKED_PORTS=""
{script}
"""
    return subprocess.run(["bash", "-c", harness], capture_output=True, text=True)


def test_two_picks_in_one_run_never_return_the_same_port():
    result = _run_picker(
        'pick_free_port A 9871\npick_free_port B 9871\npick_free_port C 9871\necho "$A $B $C"'
    )
    assert result.returncode == 0, result.stderr
    ports = result.stdout.split()
    assert len(set(ports)) == 3, f"collision: {ports}"


def test_the_picker_assigns_rather_than_prints():
    """A `$(...)` call runs in a subshell, so a picker that printed its answer
    would lose the record of what it had already handed out — which is the bug
    itself, not an implementation detail."""
    source = SETUP.read_text()
    assert 'printf -v "$__var"' in source
    assert '"$(pick_free_port' not in source, "still called in a subshell"


def test_a_port_this_run_claimed_counts_as_taken():
    source = SETUP.read_text()
    checker = source[source.index("port_is_free() {") :][:400]
    assert "PICKED_PORTS" in checker


# ------------------------------------------------- ports belong to a deploy
# A port already in .env is the deployment's, and the host proxy config names
# it. Re-picking it because "something is listening" steps past this stack's
# own container: INTERNAL_HTTP_PORT drifted 8080 -> 8082 -> 8091 over three
# runs, and each move silently orphaned the .htaccess pointing at the previous
# one, so a successful deploy took the site down.
def test_a_port_already_in_env_is_reused_not_repicked():
    result = _run_picker(
        "INTERNAL_HTTP_PORT=8091\n"
        'keep_or_pick INTERNAL_HTTP_PORT 8080 "origin"\n'
        'echo "$INTERNAL_HTTP_PORT"'
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("8091"), "a stored port must survive a re-run"


def test_a_kept_port_still_blocks_a_later_pick():
    """Keeping it must also reserve it, or the next pick collides with the
    thing the keeping was protecting."""
    result = _run_picker(
        "INTERNAL_HTTP_PORT=8091\n"
        'keep_or_pick INTERNAL_HTTP_PORT 8080 "origin"\n'
        'keep_or_pick PGWEB_HOST_PORT 8091 "browser"\n'
        'echo "$INTERNAL_HTTP_PORT $PGWEB_HOST_PORT"'
    )
    kept, fresh = result.stdout.split()[-2:]
    assert kept == "8091"
    assert fresh != kept


def test_a_fresh_install_still_chooses_a_free_port():
    result = _run_picker('keep_or_pick NEW_PORT 5432 "database"\necho "$NEW_PORT"')
    assert result.stdout.split()[-1].isdigit()


@pytest.mark.parametrize("var", ["INTERNAL_HTTP_PORT", "POSTGRES_HOST_PORT", "PGWEB_HOST_PORT"])
def test_every_published_port_is_stable_across_reruns(var):
    source = SETUP.read_text()
    assert f"keep_or_pick {var}" in source, f"{var} can still drift on a re-run"
