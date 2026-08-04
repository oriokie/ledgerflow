#!/usr/bin/env bash
# LedgerFlow — pull-based continuous delivery.
#
# Watches the `:released` tag in the registry and redeploys when it moves. CI
# only ever moves that tag after the whole pipeline passes and a human approves
# the promotion, so this script's job is narrow: notice, pull, restart, and
# prove the result still serves traffic.
#
# Why pull rather than GitHub connecting inbound: this box also hosts other
# people's production sites. A push-based deploy needs a credential in GitHub
# that grants a shell here, and a leak of that secret reaches every site on the
# machine, not just this one. Nothing here can be triggered from outside — the
# server decides when to look.
#
# Safety properties, in order of how much they matter:
#
#   * It rolls back. A deploy that starts but fails its health check is put
#     back on the previous digest, because a broken deploy that stays broken
#     until someone notices is worse than one that never happened.
#   * It verifies through the real hostname, not localhost, so the check covers
#     the proxy chain and TLS rather than just the container.
#   * It never touches .env. FIELD_ENCRYPTION_KEY lives there and rotating it
#     makes every stored MFA secret permanently unreadable.
#   * It holds a lock, so an overlapping timer tick cannot deploy on top of a
#     deploy in progress.
#
# Install with: sudo bash deploy/install-cd.sh
set -euo pipefail

REPO_DIR="${LEDGERFLOW_DIR:-/root/ledgerflow}"
COMPOSE_FILE="$REPO_DIR/deploy/docker-compose.server.yml"
STATE_DIR="${LEDGERFLOW_STATE_DIR:-/var/lib/ledgerflow-cd}"
LOCK_FILE="$STATE_DIR/deploy.lock"
APP_IMAGE="${LEDGERFLOW_APP_IMAGE:-ghcr.io/oriokie/ledgerflow/app:released}"
FRONTEND_IMAGE="${LEDGERFLOW_FRONTEND_IMAGE:-ghcr.io/oriokie/ledgerflow/frontend:released}"

log() { printf '%s  %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { log "ERROR: $*"; exit 1; }

[ -f "$COMPOSE_FILE" ] || die "No compose file at $COMPOSE_FILE (set LEDGERFLOW_DIR)."
mkdir -p "$STATE_DIR"

# Serialise against the previous tick. `flock -n` exits rather than queueing:
# if a deploy is already running, the right move is to wait for the next timer,
# not to stack a second one behind it.
exec 9>"$LOCK_FILE"
flock -n 9 || { log "A deploy is already running; skipping this tick."; exit 0; }

cd "$REPO_DIR"

# .env carries the profile choice and the ports; sourcing it here means the
# agent brings the stack up exactly the way setup.sh configured it.
set -a; . "$REPO_DIR/.env"; set +a
: "${DOMAIN:?DOMAIN missing from .env}"

PROFILES="internal"
[ "${WEB_SERVER:-existing}" = "caddy" ] && PROFILES="caddy"
[ "${DB_MODE:-bundled}" = "bundled" ] && PROFILES="$PROFILES,bundled-db"
[ "${ENABLE_PGWEB:-0}" -eq 1 ] && PROFILES="$PROFILES,pgweb"
export COMPOSE_PROFILES="$PROFILES"

dc() { docker compose -f "$COMPOSE_FILE" "$@"; }

#: The digest actually running right now, for comparison and for rollback.
running_digest() {
  docker image inspect --format '{{index .RepoDigests 0}}' "$1" 2>/dev/null || true
}

#: The digest the registry currently serves for a tag, without pulling it.
published_digest() {
  docker manifest inspect "$1" 2>/dev/null | sha256sum | cut -d' ' -f1
}

previous_app="$(running_digest "$APP_IMAGE")"
previous_frontend="$(running_digest "$FRONTEND_IMAGE")"

before="$(published_digest "$APP_IMAGE")$(published_digest "$FRONTEND_IMAGE")"
[ -n "$before" ] || die "Could not reach the registry."

# Compare against what is on disk rather than a remembered value: a state file
# can disagree with reality after a manual `docker pull`, and then the agent
# either redeploys forever or never notices a change.
dc pull --quiet app frontend >/dev/null 2>&1 || dc pull --quiet >/dev/null 2>&1 || true
current_app="$(running_digest "$APP_IMAGE")"
current_frontend="$(running_digest "$FRONTEND_IMAGE")"

if [ "$current_app" = "$previous_app" ] && [ "$current_frontend" = "$previous_frontend" ]; then
  log "Already on the released images; nothing to do."
  exit 0
fi

log "New release found. Deploying."
log "  app:      ${previous_app:-none} -> ${current_app:-unknown}"
log "  frontend: ${previous_frontend:-none} -> ${current_frontend:-unknown}"

# `frontend` publishes the built SPA into the shared volume and exits, so it is
# brought up first and separately — Caddy serves whatever is in that volume,
# and starting it alongside the app would race the asset swap.
dc up -d frontend
dc up -d

#: The deploy only counts if the site answers through its real front door.
smoke() {
  local code
  for _ in $(seq 1 30); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://$DOMAIN/healthz/" || true)"
    [ "$code" = "200" ] && return 0
    sleep 5
  done
  log "Health check never returned 200 (last: ${code:-no response})."
  return 1
}

if smoke; then
  log "Deploy healthy."
  exit 0
fi

log "Rolling back."
if [ -n "$previous_app" ]; then
  LEDGERFLOW_APP_IMAGE="$previous_app" \
  LEDGERFLOW_FRONTEND_IMAGE="${previous_frontend:-$FRONTEND_IMAGE}" \
    dc up -d
  if smoke; then
    log "Rolled back to the previous release, which is healthy."
  else
    log "Rollback did not restore health — the problem is not the new image."
  fi
else
  log "No previous image recorded; cannot roll back automatically."
fi
exit 1
