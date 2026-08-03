#!/usr/bin/env bash
#
# LedgerFlow — interactive production setup (Ubuntu 22.04 / 24.04 LTS).
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

# ------------------------------------------------------------- dependencies
if [ "$RECONFIGURE_WEB_ONLY" -eq 0 ]; then
  bold ""
  bold "Installing dependencies"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg openssl >/dev/null

  if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
      | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
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
  apt-get install -y -qq nginx >/dev/null
  cat > /etc/nginx/sites-available/ledgerflow <<NGINXEOF
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
  ln -sf /etc/nginx/sites-available/ledgerflow /etc/nginx/sites-enabled/ledgerflow
  rm -f /etc/nginx/sites-enabled/default
  nginx -t >/dev/null 2>&1 || die "nginx rejected the generated config; run 'nginx -t' to see why."
  systemctl reload nginx || systemctl start nginx
  ok "Configured nginx"
  issue_certificate nginx
}

configure_apache() {
  apt-get install -y -qq apache2 >/dev/null
  a2enmod proxy proxy_http headers ssl rewrite >/dev/null 2>&1 || true
  cat > /etc/apache2/sites-available/ledgerflow.conf <<APACHEEOF
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
  a2ensite ledgerflow >/dev/null 2>&1 || true
  a2dissite 000-default >/dev/null 2>&1 || true
  apache2ctl configtest >/dev/null 2>&1 || die "Apache rejected the generated config; run 'apache2ctl configtest'."
  systemctl reload apache2 || systemctl start apache2
  ok "Configured Apache"
  issue_certificate apache
}

issue_certificate() {
  local flavour="$1"
  if ! dns_points_here "$DOMAIN"; then
    warn "Skipping TLS: point $DOMAIN at this server, then re-run with --reconfigure-web."
    return
  fi
  apt-get install -y -qq certbot "python3-certbot-${flavour}" >/dev/null

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
