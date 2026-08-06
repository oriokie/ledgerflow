#!/usr/bin/env bash
#
# LedgerFlow — automated server provisioning (Ubuntu 22.04 / 24.04 LTS).
#
# Idempotent: safe to re-run. Turns a fresh Ubuntu VM into a running LedgerFlow
# production stack (web + worker + beat + Postgres + Redis + Caddy TLS) using
# Docker Compose. Designed to be run once on a new server as root (or via sudo).
#
# Usage:
#   sudo DOMAIN=ledgerflow.example.com ACME_EMAIL=you@example.com \
#        bash deploy/provision.sh
#
# What it does:
#   1. Installs Docker Engine + the compose plugin (official Docker repo).
#   2. Creates a non-root deploy user and an app directory.
#   3. Generates a production .env with strong secrets (only on first run).
#   4. Configures a UFW firewall (22, 80, 443) and unattended-upgrades.
#   5. Brings the stack up with docker compose (Caddy auto-provisions TLS).
#
# It does NOT clone your code — copy the repo to the server first (git clone,
# scp, or rsync) and run this script from inside the repo root. See
# deploy/README.md for the full walkthrough.

set -euo pipefail

# --------------------------------------------------------------------------- #
# Configuration (override via environment variables)
# --------------------------------------------------------------------------- #
APP_DIR="${APP_DIR:-/opt/ledgerflow}"
DEPLOY_USER="${DEPLOY_USER:-ledgerflow}"
DOMAIN="${DOMAIN:-}"                       # required for TLS
ACME_EMAIL="${ACME_EMAIL:-}"              # required for Let's Encrypt
COMPOSE_FILE="deploy/docker-compose.server.yml"
# Which optional services this path runs. provision.sh is the Caddy-fronted,
# self-contained flavour, so both profiles are on; exporting the variable
# (rather than passing --profile flags) makes every compose invocation in this
# script — and any command a person copies from its output — see the same set.
# The compose file previously relied on flags that this script never passed,
# which deployed a stack with no TLS front end at all.
export COMPOSE_PROFILES="${COMPOSE_PROFILES:-caddy,bundled-db}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log()  { printf '\033[1;32m[provision]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[provision]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[provision] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root (or with sudo)."
[ -f "$REPO_ROOT/manage.py" ] || die "Run from the LedgerFlow repo root; manage.py not found."

# --------------------------------------------------------------------------- #
# 1. System packages + Docker
# --------------------------------------------------------------------------- #
install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "Docker + compose already installed — skipping."
    return
  fi
  log "Installing Docker Engine and the compose plugin..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg ufw

  install -m 0755 -d /etc/apt/keyrings
  if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
      | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
  fi
  local codename
  codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu ${codename} stable" \
    > /etc/apt/sources.list.d/docker.list

  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
  log "Docker installed."
}

# --------------------------------------------------------------------------- #
# 2. Deploy user + app directory
# --------------------------------------------------------------------------- #
setup_user_and_dir() {
  if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
    log "Creating deploy user '$DEPLOY_USER'..."
    adduser --system --group --home "$APP_DIR" --shell /bin/bash "$DEPLOY_USER"
  fi
  usermod -aG docker "$DEPLOY_USER" || true

  mkdir -p "$APP_DIR"
  # Sync the repo into the app dir (excluding VCS/build cruft). rsync keeps
  # re-runs fast and preserves the generated .env.
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
      --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
      --exclude '*.pyc' --exclude '.env' \
      "$REPO_ROOT"/ "$APP_DIR"/
  else
    cp -r "$REPO_ROOT"/. "$APP_DIR"/
  fi
  chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"
  log "App synced to $APP_DIR."
}

# --------------------------------------------------------------------------- #
# 3. Production .env with strong secrets (first run only)
# --------------------------------------------------------------------------- #
gen_secret()  { python3 - <<'PY'
import secrets; print(secrets.token_urlsafe(64))
PY
}
gen_fernet()  { python3 - <<'PY'
try:
    from cryptography.fernet import Fernet
    print(Fernet.generate_key().decode())
except ImportError:
    import base64, secrets
    print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
PY
}
gen_password() { python3 - <<'PY'
import secrets; print(secrets.token_urlsafe(24))
PY
}

write_env() {
  local env_file="$APP_DIR/.env"
  if [ -f "$env_file" ]; then
    warn ".env already exists — leaving it untouched (delete it to regenerate)."
    return
  fi
  [ -n "$DOMAIN" ] || die "DOMAIN is required on first run (e.g. DOMAIN=app.example.com)."
  [ -n "$ACME_EMAIL" ] || die "ACME_EMAIL is required on first run (for Let's Encrypt)."

  log "Generating production .env with fresh secrets..."
  local secret fernet db_pass
  secret="$(gen_secret)"
  fernet="$(gen_fernet)"
  db_pass="$(gen_password)"

  cat > "$env_file" <<EOF
# Generated by deploy/provision.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ).
# Treat this file as a secret. Rotating DJANGO_SECRET_KEY logs everyone out;
# rotating FIELD_ENCRYPTION_KEY makes existing encrypted MFA secrets unreadable.

DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_SECRET_KEY=${secret}
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=${DOMAIN}
CORS_ALLOWED_ORIGINS=https://${DOMAIN}

# Database (Postgres runs in the compose stack; override to point at a managed DB)
POSTGRES_DB=ledgerflow
POSTGRES_USER=ledgerflow
POSTGRES_PASSWORD=${db_pass}
DATABASE_URL=postgres://ledgerflow:${db_pass}@db:5432/ledgerflow
DB_CONN_MAX_AGE=60

# Redis / Celery
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

# Field encryption (MFA secrets at rest)
FIELD_ENCRYPTION_KEY=${fernet}

# JWT
JWT_ACCESS_MINUTES=15
JWT_REFRESH_DAYS=14

# WebAuthn / passkeys (must match the public domain)
WEBAUTHN_RP_ID=${DOMAIN}
WEBAUTHN_RP_NAME=LedgerFlow
WEBAUTHN_ORIGINS=https://${DOMAIN}

# Security headers (production settings enforce these)
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_HSTS_SECONDS=31536000

# Logging
LOG_LEVEL=INFO
LOG_FORMATTER=json

# TLS / reverse proxy (consumed by deploy/Caddyfile)
DOMAIN=${DOMAIN}
ACME_EMAIL=${ACME_EMAIL}

# --- Fill these in as needed, then \`docker compose ... up -d\` again ---
# Email (SMTP) — invitations & notifications
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=true
DEFAULT_FROM_EMAIL=LedgerFlow <no-reply@${DOMAIN}>
# Object storage (attachments) — S3 / R2 / MinIO
DEFAULT_FILE_STORAGE=django.core.files.storage.FileSystemStorage
AWS_STORAGE_BUCKET_NAME=
AWS_S3_REGION_NAME=
AWS_S3_ENDPOINT_URL=
# OAuth (optional)
OAUTH_GOOGLE_CLIENT_ID=
OAUTH_GOOGLE_CLIENT_SECRET=
OAUTH_APPLE_CLIENT_ID=
OAUTH_APPLE_CLIENT_SECRET=
OAUTH_REDIRECT_URI=https://${DOMAIN}/auth/callback
EOF
  chown "$DEPLOY_USER:$DEPLOY_USER" "$env_file"
  chmod 600 "$env_file"
  log ".env written to $env_file (chmod 600)."
}

# --------------------------------------------------------------------------- #
# 4. Firewall + automatic security updates
# --------------------------------------------------------------------------- #
harden() {
  log "Configuring UFW firewall (allow 22, 80, 443)..."
  ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp

  # Container traffic is forwarded traffic, and UFW's DEFAULT_FORWARD_POLICY is
  # DROP. Allowing 80/443 says nothing about whether the app may reach its own
  # database — so without this, enabling UFW below can sever the stack from
  # Postgres while every port this script opened stays perfectly open. The
  # symptom is a site that 502s with all containers running and healthy.
  #
  # Stated as a route rule on the bridge rather than by flipping the forward
  # policy to ACCEPT, which would turn the host into a general-purpose router
  # — a far larger change than "these containers may talk to each other".
  # deploy/firewall-docker.sh re-applies and *verifies* this after launch.
  log "Allowing forwarding on the container bridge (UFW blocks it by default)..."
  ufw route allow in on br-ledgerflow out on br-ledgerflow >/dev/null 2>&1 || true
  ufw route allow in on br-ledgerflow >/dev/null 2>&1 || true

  ufw --force enable

  log "Enabling unattended security upgrades..."
  DEBIAN_FRONTEND=noninteractive apt-get install -y unattended-upgrades
  dpkg-reconfigure -f noninteractive unattended-upgrades || true
}

# --------------------------------------------------------------------------- #
# 5. Bring the stack up
# --------------------------------------------------------------------------- #
launch() {
  log "Building and starting the stack (this pulls base images and builds once)..."
  cd "$APP_DIR"
  # Run compose as the deploy user so file ownership stays consistent.
  sudo -u "$DEPLOY_USER" docker compose -f "$COMPOSE_FILE" up -d --build
  log "Waiting for the web service to report healthy..."
  for _ in $(seq 1 30); do
    if sudo -u "$DEPLOY_USER" docker compose -f "$COMPOSE_FILE" ps web \
        | grep -q "healthy"; then
      log "web is healthy."
      break
    fi
    sleep 5
  done
}

# --------------------------------------------------------------------------- #
main() {
  install_docker
  setup_user_and_dir
  write_env
  harden
  launch

  # After launch, because the bridge must exist before the firewall can be
  # told about it, and because this proves a container actually reaches
  # Postgres instead of trusting that the rules above did what they claim.
  log "Reconciling the host firewall with Docker..."
  bash "$(dirname "${BASH_SOURCE[0]}")/firewall-docker.sh" \
    || log "WARNING: container networking could not be verified — see above."

  cat <<EOF

============================================================================
  LedgerFlow is deploying.

  Domain:   https://${DOMAIN:-<set DOMAIN>}
  App dir:  $APP_DIR
  Env file: $APP_DIR/.env   (secrets generated — back this up securely)

  Useful commands (run from $APP_DIR):
    docker compose -f $COMPOSE_FILE ps
    docker compose -f $COMPOSE_FILE logs -f web
    docker compose -f $COMPOSE_FILE exec web python manage.py createsuperuser

  TLS: Caddy provisions a Let's Encrypt certificate automatically on first
  request. DNS for ${DOMAIN:-your domain} must already point at this server's
  public IP, and ports 80/443 must be reachable, for the certificate to issue.

  To update after pulling new code: re-run this script, or from $APP_DIR:
    docker compose -f $COMPOSE_FILE up -d --build
============================================================================
EOF
}

main "$@"
