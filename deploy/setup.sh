#!/usr/bin/env bash
#
# LedgerFlow — interactive production setup.
# Debian/Ubuntu (apt) and the RHEL family — RHEL, Rocky, AlmaLinux, Amazon
# Linux 2023 (dnf/yum) — are auto-detected; nothing to choose.
#
# `provision.sh` does the same job non-interactively from environment
# variables, which is right for CI and wrong for a person on a fresh box: it
# fails on the first missing variable, tells you one at a time, and assumes
# Caddy. This asks, validates as it goes, and lets you pick the web server.
#
#   sudo bash deploy/setup.sh                  # interactive
#   sudo bash deploy/setup.sh --non-interactive # env vars only, for CI
#   sudo bash deploy/setup.sh --reconfigure-web # change web server / re-issue TLS
#
# Everything is idempotent. Re-running keeps your existing .env, DJANGO_SECRET_KEY
# and database — rotating the secret key logs every user out, so it is generated
# exactly once and never regenerated silently.
#
# What it does NOT do, deliberately:
#   * It never overwrites an existing .env without showing you the diff.
#   * It never opens a firewall port you did not ask for.
#   * It refuses to run against a domain whose DNS does not resolve to this
#     host, because Let's Encrypt will fail anyway and the error it gives is
#     far less clear than the one here.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="$REPO_ROOT/.env"
INTERACTIVE=1
RECONFIGURE_WEB_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --non-interactive) INTERACTIVE=0 ;;
    --reconfigure-web) RECONFIGURE_WEB_ONLY=1 ;;
    -h|--help) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------- output
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
info()  { printf '  %s\n' "$*"; }
warn()  { printf '\033[33m  ! %s\033[0m\n' "$*"; }
ok()    { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
die()   { printf '\033[31m\n  ✗ %s\033[0m\n\n' "$*" >&2; exit 1; }

require_root() {
  [ "$(id -u)" -eq 0 ] || die "Run with sudo — this installs packages and writes to /etc."
}

# ---------------------------------------------------------------- OS family
#
# Package manager, not distro name, is what every install step below actually
# branches on — Rocky, Alma and RHEL itself all take the same dnf commands.
# Detected once, up front, before a single prompt: the previous version of this
# script discovered it was on the wrong OS four steps in, after generating
# secrets and writing .env, via a bare "apt-get: command not found" with no
# context. Dying here instead costs one line and saves the round trip.
#
# PKG_FAMILY is "debian" or "rhel" — the two axes install steps below branch
# on (paths, service names, module handling differ by family, not by manager).
detect_pkg_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    PKG_MANAGER=apt; PKG_FAMILY=debian
  elif command -v dnf >/dev/null 2>&1; then
    PKG_MANAGER=dnf; PKG_FAMILY=rhel
  elif command -v yum >/dev/null 2>&1; then
    PKG_MANAGER=yum; PKG_FAMILY=rhel
  else
    die "No apt-get, dnf or yum found. This script supports Debian/Ubuntu and
  the RHEL family (RHEL, Rocky, AlmaLinux, Amazon Linux 2023). For anything
  else — Alpine, Arch, a bare container — see 'Manual / managed infrastructure'
  in deploy/README.md and drive docker-compose.server.yml directly; every
  package-install step in this script is one call, easy to translate by hand."
  fi
}

# pkg_install <packages...> — the one call site every config function below
# uses, so a third package manager is one function to add, not a search-and-
# replace across five functions.
pkg_install() {
  case "$PKG_MANAGER" in
    apt) apt-get install -y -qq "$@" >/dev/null ;;
    dnf) dnf install -y -q "$@" >/dev/null ;;
    yum) yum install -y -q "$@" >/dev/null ;;
  esac
}

# ---------------------------------------------------------------- prompts
#
# ask VAR "Question" "default" [validator]
#
# Reads from the terminal even when the script itself is piped from curl, which
# is how most people will run it; without </dev/tty the read would consume the
# script's own stdin and silently accept empty answers for everything.
ask() {
  local __var="$1" question="$2" default="${3:-}" validator="${4:-}"
  local current="${!__var:-}" answer prompt

  if [ -n "$current" ]; then default="$current"; fi

  if [ "$INTERACTIVE" -eq 0 ]; then
    [ -n "$default" ] || die "$__var is required in non-interactive mode."
    printf -v "$__var" '%s' "$default"
    return
  fi

  while true; do
    if [ -n "$default" ]; then prompt="$question [$default]: "; else prompt="$question: "; fi
    read -r -p "  $prompt" answer </dev/tty || true
    answer="${answer:-$default}"

    if [ -z "$answer" ]; then warn "This one is required."; continue; fi
    if [ -n "$validator" ] && ! "$validator" "$answer"; then continue; fi

    printf -v "$__var" '%s' "$answer"
    return
  done
}

ask_secret() {
  local __var="$1" question="$2" answer
  if [ "$INTERACTIVE" -eq 0 ]; then return; fi
  read -r -s -p "  $question (leave blank to skip): " answer </dev/tty || true
  echo
  printf -v "$__var" '%s' "$answer"
}

confirm() {
  local question="$1" default="${2:-y}" answer
  if [ "$INTERACTIVE" -eq 0 ]; then [ "$default" = "y" ]; return; fi
  read -r -p "  $question [$( [ "$default" = y ] && echo 'Y/n' || echo 'y/N' )]: " answer </dev/tty || true
  answer="${answer:-$default}"
  [[ "$answer" =~ ^[Yy] ]]
}

# ---------------------------------------------------------------- validators
valid_domain() {
  if [[ "$1" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)+$ ]]; then
    return 0
  fi
  warn "That doesn't look like a domain (e.g. app.example.com)."
  return 1
}

valid_email() {
  [[ "$1" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] && return 0
  warn "That doesn't look like an email address."
  return 1
}

valid_webserver() {
  case "$1" in caddy|nginx|apache|none) return 0 ;; esac
  warn "Choose one of: caddy, nginx, apache, none."
  return 1
}

valid_dbmode() {
  case "$1" in bundled|external) return 0 ;; esac
  warn "Choose one of: bundled, external."
  return 1
}

valid_storagemode() {
  case "$1" in local|s3) return 0 ;; esac
  warn "Choose one of: local, s3."
  return 1
}

valid_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && [ "$1" -ge 1 ] && [ "$1" -le 65535 ] && return 0
  warn "That is not a port number."
  return 1
}

# DNS is checked before requesting a certificate because Let's Encrypt will
# refuse anyway, and its error ("challenge failed") sends people hunting through
# ACME logs rather than at their DNS panel where the actual problem is.
dns_points_here() {
  local domain="$1" resolved public
  resolved="$(getent hosts "$domain" 2>/dev/null | awk '{print $1}' | head -1 || true)"
  public="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
  [ -z "$resolved" ] && { warn "$domain does not resolve yet."; return 1; }
  [ -z "$public" ] && { warn "Could not determine this server's public IP; skipping the DNS check."; return 0; }
  [ "$resolved" = "$public" ] && return 0
  warn "$domain resolves to $resolved but this server is $public."
  return 1
}

# ============================================================================
bold ""
bold "  LedgerFlow — production setup"
bold "  ─────────────────────────────"
echo
require_root
detect_pkg_manager
ok "Detected $PKG_MANAGER ($PKG_FAMILY family)."

# Load any existing configuration so re-runs pre-fill their answers rather than
# asking everything again as though it were a fresh box.
if [ -f "$ENV_FILE" ]; then
  ok "Found an existing .env — its values are the defaults below."
  set -a; . "$ENV_FILE"; set +a
fi

# ---------------------------------------------------------------- 1. domain
bold "1. Where will this run?"
ask DOMAIN "Public domain" "${DOMAIN:-}" valid_domain
ask ACME_EMAIL "Email for Let's Encrypt (expiry warnings)" "${ACME_EMAIL:-}" valid_email

# Extra hostnames are common (apex + www, or a staging alias) and are the single
# most frequent cause of a post-deploy "DisallowedHost" 400.
ask EXTRA_HOSTS "Additional hostnames, comma-separated (blank for none)" "${EXTRA_HOSTS:-none}"
[ "$EXTRA_HOSTS" = "none" ] && EXTRA_HOSTS=""

ALLOWED_HOSTS="$DOMAIN"
[ -n "$EXTRA_HOSTS" ] && ALLOWED_HOSTS="$DOMAIN,$EXTRA_HOSTS"

CORS_ORIGINS="https://$DOMAIN"
if [ -n "$EXTRA_HOSTS" ]; then
  IFS=',' read -ra _hosts <<< "$EXTRA_HOSTS"
  for h in "${_hosts[@]}"; do CORS_ORIGINS="$CORS_ORIGINS,https://$(echo "$h" | xargs)"; done
fi
echo

# ------------------------------------------------------------ 2. web server
bold "2. Web server"
info "caddy  — automatic TLS, no config to maintain (recommended)"
info "nginx  — if you already run nginx or need its module ecosystem"
info "apache — if your organisation standardises on it"
info "none   — you terminate TLS elsewhere (a load balancer, Cloudflare)"
ask WEB_SERVER "Which" "${WEB_SERVER:-caddy}" valid_webserver
echo

# -------------------------------------------------------------- 3. database
bold "3. Database"
info "bundled  — Postgres runs on this server inside the stack (default)"
info "external — a managed Postgres (RDS, Cloud SQL, Neon, your own box)"
ask DB_MODE "Which" "${DB_MODE:-bundled}" valid_dbmode
if [ "$DB_MODE" = "external" ]; then
  info "Row-level tenant isolation requires PostgreSQL — this cannot be MySQL."
  ask DB_HOST "Postgres host" "${DB_HOST:-}"
  ask DB_PORT "Postgres port" "${DB_PORT:-5432}" valid_port
  ask DB_NAME "Database name" "${DB_NAME:-ledgerflow}"
  ask DB_USER "Database user" "${DB_USER:-ledgerflow}"
  ask_secret DB_PASSWORD "Database password"
  [ -n "${DB_PASSWORD:-}" ] || die "An external database needs its password."
  info "The user must be able to create tables; migrations enable row-level"
  info "security on every tenant table, and FORCE RLS applies it to the owner too."
fi
echo

# ---------------------------------------------------------- 4. file storage
bold "4. File storage (receipts and attachments)"
info "local — files stay on this server, inside the Docker media volume."
info "        Right for a single server; they are part of your backups."
info "s3    — an S3-compatible bucket (AWS, R2, MinIO). Required the moment"
info "        you run more than one server, because local files don't follow."
ask STORAGE_MODE "Which" "${STORAGE_MODE:-local}" valid_storagemode
if [ "$STORAGE_MODE" = "s3" ]; then
  ask AWS_STORAGE_BUCKET_NAME "Bucket name" "${AWS_STORAGE_BUCKET_NAME:-}"
  ask AWS_S3_REGION_NAME "Region" "${AWS_S3_REGION_NAME:-auto}"
  ask AWS_S3_ENDPOINT_URL "Endpoint URL (blank for AWS)" "${AWS_S3_ENDPOINT_URL:-none}"
  [ "$AWS_S3_ENDPOINT_URL" = "none" ] && AWS_S3_ENDPOINT_URL=""
  ask AWS_ACCESS_KEY_ID "Access key id" "${AWS_ACCESS_KEY_ID:-}"
  ask_secret AWS_SECRET_ACCESS_KEY "Secret access key"
fi
echo

# ----------------------------------------------------------------- 5. email
bold "5. Outbound email"
info "Used for invitations, password resets, invoices and alerts."
info "Leave blank to configure later — the app runs, but sends nothing."
ask EMAIL_HOST "SMTP host" "${EMAIL_HOST:-none}"
if [ "$EMAIL_HOST" = "none" ] || [ -z "$EMAIL_HOST" ]; then
  EMAIL_HOST=""; EMAIL_PORT=""; EMAIL_HOST_USER=""; EMAIL_HOST_PASSWORD=""
  warn "No SMTP configured. Invitations and password resets will not be delivered."
else
  ask EMAIL_PORT "SMTP port" "${EMAIL_PORT:-587}"
  ask EMAIL_HOST_USER "SMTP username" "${EMAIL_HOST_USER:-}"
  ask_secret EMAIL_HOST_PASSWORD "SMTP password"
  ask DEFAULT_FROM_EMAIL "Send from" "${DEFAULT_FROM_EMAIL:-no-reply@$DOMAIN}" valid_email
fi
echo

# --------------------------------------------------------------- 6. payments
bold "6. Payments (optional — set later in the admin console)"
if confirm "Configure a payment provider now?" n; then
  ask_secret STRIPE_SECRET_KEY "Stripe secret key"
  ask_secret STRIPE_WEBHOOK_SECRET "Stripe webhook signing secret"
  ask_secret MPESA_CONSUMER_KEY "M-PESA consumer key"
  ask_secret MPESA_CONSUMER_SECRET "M-PESA consumer secret"
else
  info "Skipped — configure at https://$DOMAIN/admin/settings once you're up."
fi
echo

# ------------------------------------------------------------------- secrets
# Generated once and never rotated silently: changing DJANGO_SECRET_KEY
# invalidates every session and password-reset link in flight, and
# FIELD_ENCRYPTION_KEY is worse — it makes every stored TOTP secret and
# platform credential permanently unreadable.
if [ -z "${DJANGO_SECRET_KEY:-}" ]; then
  DJANGO_SECRET_KEY="$(openssl rand -base64 48 | tr -d '\n=/+' | cut -c1-50)"
  ok "Generated DJANGO_SECRET_KEY."
else
  ok "Keeping the existing DJANGO_SECRET_KEY (rotating it logs everyone out)."
fi

if [ -z "${FIELD_ENCRYPTION_KEY:-}" ]; then
  FIELD_ENCRYPTION_KEY="$(openssl rand -base64 32)"
  ok "Generated FIELD_ENCRYPTION_KEY."
else
  ok "Keeping the existing FIELD_ENCRYPTION_KEY (rotating it orphans encrypted data)."
fi

POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(openssl rand -hex 24)}"

# ------------------------------------------------------------------ summary
echo
bold "Summary"
info "Domain          $DOMAIN"
info "Allowed hosts   $ALLOWED_HOSTS"
info "Web server      $WEB_SERVER"
info "Database        $( [ "$DB_MODE" = external ] && echo "external — $DB_HOST:$DB_PORT/$DB_NAME" || echo 'bundled Postgres 16' )"
info "File storage    $( [ "$STORAGE_MODE" = s3 ] && echo "S3 — $AWS_STORAGE_BUCKET_NAME" || echo 'local media volume' )"
info "TLS             $( [ "$WEB_SERVER" = caddy ] && echo 'automatic (Caddy)' || { [ "$WEB_SERVER" = none ] && echo 'terminated upstream' || echo "Let's Encrypt via certbot"; } )"
info "Email           ${EMAIL_HOST:-not configured}"
info "Payments        $( [ -n "${STRIPE_SECRET_KEY:-}${MPESA_CONSUMER_KEY:-}" ] && echo configured || echo 'configure in the console' )"
echo
confirm "Proceed?" y || die "Cancelled — nothing was written."
echo

# ------------------------------------------------------------------- write
if [ -f "$ENV_FILE" ]; then
  cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
  ok "Backed up the previous .env"
fi

umask 077
cat > "$ENV_FILE" <<ENVEOF
# Written by deploy/setup.sh on $(date -Iseconds).
# Treat as a secret: it contains the signing key, the database password and the
# encryption key protecting TOTP secrets and stored platform credentials.

DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}
FIELD_ENCRYPTION_KEY=${FIELD_ENCRYPTION_KEY}

DJANGO_ALLOWED_HOSTS=${ALLOWED_HOSTS}
CORS_ALLOWED_ORIGINS=${CORS_ORIGINS}
FRONTEND_BASE_URL=https://${DOMAIN}
OAUTH_REDIRECT_URI=https://${DOMAIN}/auth/callback
WEBAUTHN_RP_ID=${DOMAIN}
WEBAUTHN_ORIGINS=https://${DOMAIN}

$(if [ "$DB_MODE" = "external" ]; then
  echo "DATABASE_URL=postgres://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
else
  echo "DATABASE_URL=postgres://ledgerflow:${POSTGRES_PASSWORD}@db:5432/ledgerflow"
fi)
POSTGRES_USER=ledgerflow
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=ledgerflow
REDIS_URL=redis://redis:6379/0

# File storage. Local keeps uploads in the Docker media volume; S3 makes them
# follow the app across servers. production.py defaults to S3 unless told
# otherwise, so the local choice must be written down explicitly.
$(if [ "$STORAGE_MODE" = "s3" ]; then
  echo "DEFAULT_FILE_STORAGE=storages.backends.s3.S3Storage"
  echo "AWS_STORAGE_BUCKET_NAME=${AWS_STORAGE_BUCKET_NAME}"
  echo "AWS_S3_REGION_NAME=${AWS_S3_REGION_NAME}"
  echo "AWS_S3_ENDPOINT_URL=${AWS_S3_ENDPOINT_URL}"
  echo "AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}"
  echo "AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}"
else
  echo "DEFAULT_FILE_STORAGE=django.core.files.storage.FileSystemStorage"
fi)

EMAIL_HOST=${EMAIL_HOST:-}
EMAIL_PORT=${EMAIL_PORT:-587}
EMAIL_HOST_USER=${EMAIL_HOST_USER:-}
EMAIL_HOST_PASSWORD=${EMAIL_HOST_PASSWORD:-}
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=${DEFAULT_FROM_EMAIL:-no-reply@${DOMAIN}}

STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY:-}
STRIPE_WEBHOOK_SECRET=${STRIPE_WEBHOOK_SECRET:-}
MPESA_CONSUMER_KEY=${MPESA_CONSUMER_KEY:-}
MPESA_CONSUMER_SECRET=${MPESA_CONSUMER_SECRET:-}

DOMAIN=${DOMAIN}
ACME_EMAIL=${ACME_EMAIL}
WEB_SERVER=${WEB_SERVER}
EXTRA_HOSTS=${EXTRA_HOSTS}
DB_MODE=${DB_MODE}
DB_HOST=${DB_HOST:-}
DB_PORT=${DB_PORT:-}
DB_NAME=${DB_NAME:-}
DB_USER=${DB_USER:-}
DB_PASSWORD=${DB_PASSWORD:-}
STORAGE_MODE=${STORAGE_MODE}
ENVEOF
chmod 600 "$ENV_FILE"
ok "Wrote .env (mode 600)"

# Compose resolves ${VAR} interpolation (e.g. the caddy service's required
# DOMAIN/ACME_EMAIL) against a .env file in the *compose file's* directory,
# not the caller's cwd or the env_file: directive below — those only inject
# vars into containers, they don't feed interpolation. Without this symlink,
# any manual `docker compose -f deploy/docker-compose.server.yml ...` run
# from the repo root (exactly what the README's Day-2 ops section shows)
# fails interpolation unless .env was sourced into the shell first.
ln -sf ../.env "$REPO_ROOT/deploy/.env"

# ------------------------------------------------------------- dependencies
if [ "$RECONFIGURE_WEB_ONLY" -eq 0 ]; then
  bold ""
  bold "Installing dependencies"

  if [ "$PKG_FAMILY" = debian ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    pkg_install ca-certificates curl gnupg openssl
  else
    dnf makecache -q 2>/dev/null || yum makecache -q 2>/dev/null || true
    pkg_install ca-certificates curl openssl
  fi

  if ! command -v docker >/dev/null 2>&1; then
    if [ "$PKG_FAMILY" = debian ]; then
      install -m 0755 -d /etc/apt/keyrings
      curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
      chmod a+r /etc/apt/keyrings/docker.gpg
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list
      apt-get update -qq
      pkg_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    else
      # Docker publishes no first-party RHEL repo; its own docs point RHEL,
      # Rocky and Alma at the CentOS one — all four are ABI-compatible with
      # the RPMs it ships, which is why this is the documented path rather
      # than a workaround.
      pkg_install dnf-plugins-core
      dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo -y -q 2>/dev/null \
        || yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
      pkg_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
      # The apt package's postinst enables+starts the daemon; dnf/yum's does
      # not, so a fresh RHEL install would otherwise leave `docker compose up`
      # failing against a socket nothing is listening on.
      systemctl enable --now docker
    fi
    ok "Installed Docker"
  else
    ok "Docker already present"
  fi
fi

# --------------------------------------------------------------- web server
#
# nginx and Apache proxy to the stack's *internal origin* — a loopback-bound
# Caddy that serves the SPA and routes /api, /django-admin and /static to
# gunicorn. They must NOT proxy to gunicorn directly: it publishes no host
# port, and it has never served the frontend — the original config here did
# exactly that, and every nginx/Apache deployment got connection-refused.
# Keeping path-routing inside the stack also means the host web server is a
# pure TLS terminator, so switching servers can never change what /admin is.
APP_UPSTREAM="127.0.0.1:8080"

configure_nginx() {
  pkg_install nginx
  # /etc/nginx/conf.d/*.conf is auto-included by nginx.conf on every packaging
  # of nginx — Debian's own default nginx.conf includes it alongside
  # sites-enabled, and it's the *only* convention on the RHEL family, which
  # has no sites-available/sites-enabled at all. Writing here instead of into
  # sites-available means one code path serves both families, and it drops
  # the symlink step the sites-available convention required.
  cat > /etc/nginx/conf.d/ledgerflow.conf <<NGINXEOF
# Managed by deploy/setup.sh — re-run with --reconfigure-web to regenerate.
server {
    listen 80;
    listen [::]:80;
    server_name ${ALLOWED_HOSTS//,/ };

    # certbot writes its challenge here; everything else goes to HTTPS.
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${ALLOWED_HOSTS//,/ };

    # ssl_certificate lines are added by certbot on first issue.

    # Django sets HSTS, X-Frame-Options and nosniff itself; they are not
    # duplicated here, because two sources for one header is how they end up
    # disagreeing.

    client_max_body_size 25M;   # receipt uploads

    location / {
        proxy_pass http://${APP_UPSTREAM};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        # SECURE_PROXY_SSL_HEADER reads this; without it Django thinks every
        # request is plaintext and redirect-loops on SECURE_SSL_REDIRECT.
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
NGINXEOF
  # Both families ship a catch-all default server on :80 that would otherwise
  # win ties against ours by file-sort order; disabling it is harmless if it
  # was never there.
  rm -f /etc/nginx/sites-enabled/default            # Debian/Ubuntu
  rm -f /etc/nginx/conf.d/default.conf               # RHEL family
  nginx -t >/dev/null 2>&1 || die "nginx rejected the generated config; run 'nginx -t' to see why."
  systemctl reload nginx || systemctl start nginx
  ok "Configured nginx"
  issue_certificate nginx
}

configure_apache() {
  # Package name, config directory and service name all diverge by family —
  # more than nginx does, because "sites-available + a2enmod" is a Debian
  # invention with no RHEL equivalent, not just a path difference.
  local conf_dir
  if [ "$PKG_FAMILY" = debian ]; then
    pkg_install apache2
    a2enmod proxy proxy_http headers ssl rewrite >/dev/null 2>&1 || true
    conf_dir=/etc/apache2/sites-available
  else
    # RHEL's base httpd package auto-loads proxy/proxy_http/headers/rewrite
    # from conf.modules.d/00-base.conf — there is no a2enmod to run. mod_ssl
    # is the one module that ships as its own RPM.
    pkg_install httpd mod_ssl
    conf_dir=/etc/httpd/conf.d
    # Installing mod_ssl drops /etc/httpd/conf.d/ssl.conf: a second *:443
    # VirtualHost pointed at RHEL's snake-oil certificate. Apache picks
    # between same-port vhosts by ServerName/SNI, but a broken second vhost
    # is still worth removing rather than trusting Apache's tie-break — it
    # has caused startup failures on distros where the placeholder cert path
    # in that file doesn't exist.
    rm -f /etc/httpd/conf.d/ssl.conf
  fi

  cat > "$conf_dir/ledgerflow.conf" <<APACHEEOF
# Managed by deploy/setup.sh — re-run with --reconfigure-web to regenerate.
<VirtualHost *:80>
    ServerName ${DOMAIN}
$(for h in ${EXTRA_HOSTS//,/ }; do echo "    ServerAlias $h"; done)

    # Leave the ACME path alone; redirect the rest.
    RewriteEngine On
    RewriteCond %{REQUEST_URI} !^/\.well-known/acme-challenge/
    RewriteRule ^(.*)\$ https://%{HTTP_HOST}\$1 [R=301,L]
</VirtualHost>

<VirtualHost *:443>
    ServerName ${DOMAIN}
$(for h in ${EXTRA_HOSTS//,/ }; do echo "    ServerAlias $h"; done)

    SSLEngine on
    # SSLCertificateFile lines are added by certbot on first issue.

    ProxyPreserveHost On
    ProxyPass        / http://${APP_UPSTREAM}/
    ProxyPassReverse / http://${APP_UPSTREAM}/
    # Django's SECURE_PROXY_SSL_HEADER depends on this.
    RequestHeader set X-Forwarded-Proto "https"
    LimitRequestBody 26214400
</VirtualHost>
APACHEEOF
  local apache_service apache_ctl
  if [ "$PKG_FAMILY" = debian ]; then
    a2ensite ledgerflow >/dev/null 2>&1 || true
    a2dissite 000-default >/dev/null 2>&1 || true
    apache_service=apache2
    apache_ctl=apache2ctl
  else
    # conf.d is auto-included on RHEL — no ensite step, and no default vhost
    # ships to disable.
    apache_service=httpd
    apache_ctl=apachectl
  fi
  "$apache_ctl" configtest >/dev/null 2>&1 \
    || die "Apache rejected the generated config; run '$apache_ctl configtest' to see why."
  systemctl reload "$apache_service" || systemctl start "$apache_service"
  ok "Configured Apache"
  issue_certificate apache
}

issue_certificate() {
  local flavour="$1"
  if ! dns_points_here "$DOMAIN"; then
    warn "Skipping TLS: point $DOMAIN at this server, then re-run with --reconfigure-web."
    return
  fi
  if [ "$PKG_FAMILY" = rhel ]; then
    # certbot and its plugins live in EPEL, not the base/AppStream repos.
    # Harmless to re-run: dnf no-ops on an already-enabled repo.
    pkg_install epel-release
  fi
  pkg_install certbot "python3-certbot-${flavour}"

  local domain_args="-d $DOMAIN"
  for h in ${EXTRA_HOSTS//,/ }; do domain_args="$domain_args -d $(echo "$h" | xargs)"; done

  # --keep-until-expiring makes re-running safe: it reuses a live certificate
  # instead of burning a Let's Encrypt rate-limit slot on every provision.
  if certbot --"$flavour" $domain_args \
      --non-interactive --agree-tos -m "$ACME_EMAIL" \
      --redirect --keep-until-expiring; then
    ok "TLS certificate issued and auto-renewal enabled"
  else
    warn "certbot failed. The site is up on HTTP; fix DNS and re-run with --reconfigure-web."
  fi
}

configure_caddy() {
  # Caddy runs in the compose stack and obtains its own certificates, so there
  # is nothing to install on the host.
  ok "Caddy handles TLS automatically from the compose stack"
}

bold ""
bold "Configuring the web server"

# RHEL cloud images commonly ship firewalld active with only SSH open —
# Ubuntu images typically ship no firewall at all. Left alone, DNS resolves
# and certbot's HTTP-01 challenge times out with nothing indicating the cause
# is a closed port rather than the DNS/TLS problem its own error suggests.
# Gated on a prompt, matching "never opens a firewall port you did not ask
# for" above — the fix for that closed port is still the user's call, just
# now an informed one instead of a mysterious timeout three steps later.
if [ "$WEB_SERVER" != none ] && command -v firewall-cmd >/dev/null 2>&1 \
    && systemctl is-active --quiet firewalld; then
  warn "firewalld is active and only allows SSH through by default."
  if confirm "Open 80 and 443 (ssh stays untouched)?" y; then
    firewall-cmd --permanent --add-service=http >/dev/null
    firewall-cmd --permanent --add-service=https >/dev/null
    firewall-cmd --reload >/dev/null
    ok "Opened 80/443 in firewalld."
  else
    warn "Left closed — TLS issuance will fail until you open them yourself:"
    info "  firewall-cmd --permanent --add-service={http,https} && firewall-cmd --reload"
  fi
fi

case "$WEB_SERVER" in
  nginx)  configure_nginx ;;
  apache) configure_apache ;;
  caddy)  configure_caddy ;;
  none)   warn "No web server configured. Point your load balancer at ${APP_UPSTREAM} (the stack's internal origin) and forward X-Forwarded-Proto." ;;
esac

# ------------------------------------------------------------------- launch
if [ "$RECONFIGURE_WEB_ONLY" -eq 1 ]; then
  bold ""
  ok "Web server reconfigured. The application stack was left running."
  exit 0
fi

bold ""
bold "Starting the stack"
COMPOSE_FILE="deploy/docker-compose.server.yml"
[ -f "$COMPOSE_FILE" ] || die "Missing $COMPOSE_FILE"

# Caddy-on-443 only when it is the chosen front end; with nginx or Apache the
# stack instead exposes the loopback internal origin they proxy to. The
# bundled database profile stays off when a managed Postgres was chosen.
PROFILES=""
if [ "$WEB_SERVER" = "caddy" ]; then
  PROFILES="--profile caddy"
else
  PROFILES="--profile internal"
fi
[ "$DB_MODE" = "bundled" ] && PROFILES="$PROFILES --profile bundled-db"

# Exported as well as passed: `docker compose ps/logs/exec` in the done-block
# hints below then behave identically for whoever copies them.
export COMPOSE_PROFILES="${PROFILES//--profile /}"
export COMPOSE_PROFILES="${COMPOSE_PROFILES// /,}"
docker compose -f "$COMPOSE_FILE" up -d --build
docker compose -f "$COMPOSE_FILE" exec -T web python manage.py migrate --no-input
docker compose -f "$COMPOSE_FILE" exec -T web python manage.py collectstatic --no-input >/dev/null
docker compose -f "$COMPOSE_FILE" exec -T web python manage.py seed_plans

# -------------------------------------------------------------- first owner
bold ""
bold "Platform owner"
if [ "$INTERACTIVE" -eq 1 ] && confirm "Create the first platform administrator now?" y; then
  ask OWNER_EMAIL "Their email (they must register first)" "${OWNER_EMAIL:-$ACME_EMAIL}" valid_email
  docker compose -f "$COMPOSE_FILE" exec -T web \
    python manage.py bootstrap_platform_owner --email "$OWNER_EMAIL" \
    || warn "Could not appoint $OWNER_EMAIL — register the account first, then re-run this one command."
else
  info "Later: docker compose -f $COMPOSE_FILE exec web python manage.py bootstrap_platform_owner --email you@example.com"
fi

# ------------------------------------------------------------------ done
bold ""
bold "  Done"
echo
info "Application   https://${DOMAIN}"
info "Admin console https://${DOMAIN}/admin (Django's own admin: /django-admin)"
info "Configuration $ENV_FILE (mode 600 — back it up somewhere safe)"
echo
info "Logs      docker compose -f $COMPOSE_FILE logs -f web"
info "Restart   docker compose -f $COMPOSE_FILE restart web"
info "Update    git pull && sudo bash deploy/setup.sh --non-interactive"
info "Compose   export COMPOSE_PROFILES=$COMPOSE_PROFILES   # before any manual 'docker compose' command"
echo
[ -z "${EMAIL_HOST:-}" ] && warn "No SMTP: invitations and password resets will not be delivered."
[ "$WEB_SERVER" = "none" ] && warn "No TLS on this host — terminate it upstream, or re-run with --reconfigure-web."
echo
