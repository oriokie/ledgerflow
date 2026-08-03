#!/usr/bin/env bash
#
# LedgerFlow — local development bootstrap for macOS.
#
# Two ways to run LedgerFlow locally:
#   • Docker (recommended, zero host installs beyond Docker Desktop) — pass
#     --docker, or just run `docker compose up` yourself.
#   • Native (a Python venv + Homebrew Postgres/Redis) — the default here, for
#     when you want to run/debug the code directly on the host.
#
# Usage:
#   bash deploy/mac-setup.sh            # native venv setup
#   bash deploy/mac-setup.sh --docker   # docker compose path
#
# Idempotent: re-running is safe.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

log()  { printf '\033[1;32m[mac-setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[mac-setup]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[mac-setup] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

MODE="native"
[ "${1:-}" = "--docker" ] && MODE="docker"

# --------------------------------------------------------------------------- #
gen_fernet() { python3 - <<'PY'
try:
    from cryptography.fernet import Fernet
    print(Fernet.generate_key().decode())
except ImportError:
    import base64, secrets
    print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
PY
}

ensure_env() {
  if [ -f .env ]; then
    log ".env already exists — leaving it."
    return
  fi
  log "Creating .env from .env.example..."
  cp .env.example .env
  # Fill in a real field-encryption key so MFA works out of the box.
  local key; key="$(gen_fernet)"
  # macOS sed needs the empty-string backup arg.
  sed -i '' "s|^FIELD_ENCRYPTION_KEY=.*|FIELD_ENCRYPTION_KEY=${key}|" .env
  log "Generated FIELD_ENCRYPTION_KEY."
}

# --------------------------------------------------------------------------- #
docker_path() {
  command -v docker >/dev/null 2>&1 || die "Docker Desktop not found. Install: https://www.docker.com/products/docker-desktop/"
  ensure_env
  log "Starting the full stack with Docker Compose..."
  docker compose up --build -d
  log "Waiting for web to come up..."
  sleep 5
  cat <<EOF

  LedgerFlow is running via Docker.
    API:      http://localhost:8000/api/v1/
    Docs:     http://localhost:8000/api/docs/
    Health:   http://localhost:8000/healthz/

  Logs:            docker compose logs -f
  Create a user:   docker compose exec web python manage.py createsuperuser
  Stop:            docker compose down
EOF
}

# --------------------------------------------------------------------------- #
native_path() {
  command -v brew >/dev/null 2>&1 || die "Homebrew not found. Install from https://brew.sh first."

  log "Installing Postgres 16 and Redis via Homebrew (skips if present)..."
  brew list postgresql@16 >/dev/null 2>&1 || brew install postgresql@16
  brew list redis >/dev/null 2>&1 || brew install redis
  brew services start postgresql@16
  brew services start redis

  # Make sure the postgres CLIs are on PATH for this session.
  local pg_prefix
  pg_prefix="$(brew --prefix postgresql@16)"
  export PATH="${pg_prefix}/bin:$PATH"

  log "Creating the ledgerflow database and role (idempotent)..."
  # createuser/createdb are no-ops-with-error if they already exist; guard them.
  psql postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='app'" | grep -q 1 \
    || psql postgres -c "CREATE ROLE app LOGIN PASSWORD 'app';"
  psql postgres -tc "SELECT 1 FROM pg_database WHERE datname='ledgerflow'" | grep -q 1 \
    || psql postgres -c "CREATE DATABASE ledgerflow OWNER app;"

  log "Creating a Python virtual environment (.venv)..."
  local py=python3.12
  command -v $py >/dev/null 2>&1 || py=python3
  $py -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install --upgrade pip >/dev/null
  log "Installing development dependencies..."
  pip install -r requirements/development.txt

  ensure_env
  # Point .env at the default local Postgres port for the native path.
  sed -i '' "s|^DATABASE_URL=.*|DATABASE_URL=postgres://app:app@localhost:5432/ledgerflow|" .env

  log "Applying migrations..."
  set -a; # shellcheck disable=SC1091
  source .env; set +a
  python manage.py migrate

  cat <<EOF

  LedgerFlow is set up (native).

  Activate the venv in each new shell:   source .venv/bin/activate

  Then, in three terminals (all with the venv active):
    make run       # API at http://localhost:8000
    make worker    # Celery worker
    make beat      # Celery beat scheduler

  Create an admin user:  python manage.py createsuperuser
  Run the tests:         make test
  API docs:              http://localhost:8000/api/docs/
EOF
}

# --------------------------------------------------------------------------- #
if [ "$MODE" = "docker" ]; then
  docker_path
else
  native_path
fi
