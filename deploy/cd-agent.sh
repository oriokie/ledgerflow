#!/usr/bin/env bash
# LedgerFlow — pull-based continuous delivery.
#
# Watches the `:released` tag in the registry and redeploys when it moves. CI
# only ever moves that tag after the whole pipeline passes and a human approves
# the promotion, so this script's job is narrow: notice, pull, restart, and
# prove the result still serves traffic.
#
# The application itself is those images. The git checkout on this box is how
# compose, Caddy, and *this script* arrive. Leaving the tree stale is why a
# merge can look deployed (the timer ran) while `git pull` afterwards prints
# hundreds of files the agent never fetched — and why a Caddyfile or compose
# change in the same merge never reaches the box.
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

mkdir -p "$STATE_DIR"

# Serialise against the previous tick. `flock -n` exits rather than queueing:
# if a deploy is already running, the right move is to wait for the next timer,
# not to stack a second one behind it.
exec 9>"$LOCK_FILE"
flock -n 9 || { log "A deploy is already running; skipping this tick."; exit 0; }

cd "$REPO_DIR"

#: Fast-forward `main` so compose/Caddy/this agent match origin. Images still
#: carry the application; this is the host-side half the registry cannot hold.
#:
#: `ff-only` so a box that grew local commits is not rewritten. Only `main` is
#: moved — feature branches are not fetched, and a checkout that is not on
#: `main` is left alone.
sync_checkout() {
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log "Not a git checkout at $REPO_DIR; skipping tree update."
    return 0
  fi
  local branch
  branch="$(git rev-parse --abbrev-ref HEAD)"
  if [ "$branch" != "main" ]; then
    log "Checkout is on '$branch', not main; leaving it alone."
    return 0
  fi
  export GIT_TERMINAL_PROMPT=0
  # `git fetch origin main` updates FETCH_HEAD. Depending on the remote's
  # fetch refspec it may not move origin/main, so merge FETCH_HEAD rather
  # than assuming that tracking ref moved.
  if ! git fetch --prune origin main; then
    log "Could not fetch origin/main. The git tree stays at $(git rev-parse --short HEAD)."
    log "Images can still move; compose/Caddy will not."
    return 0
  fi
  local local_sha remote_sha
  local_sha="$(git rev-parse HEAD)"
  remote_sha="$(git rev-parse FETCH_HEAD)"
  if [ "$local_sha" = "$remote_sha" ]; then
    return 0
  fi
  log "Updating checkout $(git rev-parse --short "$local_sha") -> $(git rev-parse --short "$remote_sha")"
  git merge --ff-only FETCH_HEAD || {
    log "Cannot fast-forward: local main has diverged from origin. Resolve on the box."
    return 0
  }
}

previous_sha="$(git rev-parse HEAD 2>/dev/null || true)"
sync_checkout
current_sha="$(git rev-parse HEAD 2>/dev/null || true)"

[ -f "$COMPOSE_FILE" ] || die "No compose file at $COMPOSE_FILE (set LEDGERFLOW_DIR)."

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

#: Content id, not the tag name. `:released` is a moving pointer; comparing
#: RepoDigests[0] after `compose pull` of a service that also has a `build:`
#: section can report "already current" while the registry has moved on,
#: because Compose may skip the pull for a buildable service. `docker pull`
#: of the tag always asks the registry. `.Id` is what actually changed.
image_id() {
  docker image inspect --format '{{.Id}}' "$1" 2>/dev/null || true
}

#: A reference `compose up` can retarget on rollback. Prefer the repo digest
#: (pullable) and fall back to the local id (still on disk until prune).
image_ref() {
  docker image inspect --format '{{if .RepoDigests}}{{index .RepoDigests 0}}{{else}}{{.Id}}{{end}}' "$1" 2>/dev/null || true
}

previous_app="$(image_id "$APP_IMAGE")"
previous_frontend="$(image_id "$FRONTEND_IMAGE")"
previous_app_ref="$(image_ref "$APP_IMAGE")"
previous_frontend_ref="$(image_ref "$FRONTEND_IMAGE")"

# A pull that fails is reported, not swallowed. Treating it as "nothing to do"
# is how a CD agent goes quiet for a week: the tag not existing yet, private
# packages the host cannot authenticate for, and a registry outage all look
# identical from here, and all of them mean no deploys are happening.
if ! docker pull --quiet "$APP_IMAGE" || ! docker pull --quiet "$FRONTEND_IMAGE"; then
  log "Could not pull from the registry. Nothing was changed."
  log "Usual causes: no :released tag published yet, the GHCR packages are"
  log "private and this host has not run 'docker login ghcr.io', or a network"
  log "problem. Retrying on the next tick."
  exit 1
fi
current_app="$(image_id "$APP_IMAGE")"
current_frontend="$(image_id "$FRONTEND_IMAGE")"

images_changed=0
checkout_changed=0
[ "$current_app" = "$previous_app" ] && [ "$current_frontend" = "$previous_frontend" ] || images_changed=1
[ "$current_sha" = "$previous_sha" ] || checkout_changed=1

if [ "$images_changed" -eq 0 ] && [ "$checkout_changed" -eq 0 ]; then
  log "Already on the released images; nothing to do."
  exit 0
fi

if [ "$images_changed" -eq 1 ]; then
  log "New release found. Deploying."
  log "  app:      ${previous_app_ref:-none} -> $(image_ref "$APP_IMAGE")"
  log "  frontend: ${previous_frontend_ref:-none} -> $(image_ref "$FRONTEND_IMAGE")"
  # `frontend` publishes the built SPA into the shared volume. `--force-recreate`
  # is the part that actually swaps the files: the container copies once at
  # start and then sleeps, so `up -d` on an already-running frontend leaves
  # Caddy serving yesterday's bundle.
  dc up -d --force-recreate --no-deps frontend
  dc up -d
elif [ "$checkout_changed" -eq 1 ]; then
  log "Checkout updated with no new image; applying compose and reloading the proxy."
  dc up -d
  dc restart caddy 2>/dev/null || dc restart caddy_internal 2>/dev/null || true
fi

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
if [ "$images_changed" -eq 1 ] && [ -n "$previous_app_ref" ]; then
  LEDGERFLOW_APP_IMAGE="$previous_app_ref" \
  LEDGERFLOW_FRONTEND_IMAGE="${previous_frontend_ref:-$FRONTEND_IMAGE}" \
    dc up -d --force-recreate --no-deps frontend
  LEDGERFLOW_APP_IMAGE="$previous_app_ref" \
  LEDGERFLOW_FRONTEND_IMAGE="${previous_frontend_ref:-$FRONTEND_IMAGE}" \
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
