#!/usr/bin/env bash
# LedgerFlow — notice the site is down without waiting for a person to try it.
#
# Install with: sudo bash deploy/install-monitor.sh
#
# The gap this closes
# -------------------
# deploy/cd-agent.sh smoke-tests the site, but only inside a deploy. On every
# other tick it prints "Already on the released images; nothing to do." and
# exits without checking anything at all. So between releases — which is nearly
# all the time — nothing on this host was watching. The 2026-08-06 outage began
# at 04:04 UTC and was discovered when somebody tried to log in around six
# hours later. Every ingredient for catching it in two minutes was already on
# the box; nothing was looking.
#
# What it checks, and why that endpoint
# -------------------------------------
# /readyz/, not /healthz/. Liveness deliberately checks nothing external — a
# database outage must not make Docker restart every replica at once — so
# /healthz/ can return a confident 200 while the app cannot reach Postgres.
# Readiness touches the database, the cache and the migration state, which is
# precisely the set that went dark during the outage.
#
# The limitation, and how the heartbeat answers it
# ------------------------------------------------
# This runs on the host it watches. If the machine loses power, loses its
# network, or fills its disk to the point systemd cannot start a unit, there is
# nobody left to send the alert — silence from this monitor is not evidence of
# health.
#
# `MONITOR_HEARTBEAT_URL` closes that. After every *successful* probe the
# monitor pings that URL; the service on the other end raises the alarm when
# the pings stop. It is a dead-man's switch, and it inverts the failure mode:
# instead of relying on a dying host to send its own obituary, silence itself
# becomes the signal.
#
# One URL, no account plumbing in this repo, and it works with whatever the
# operator already uses — Healthchecks.io, Better Stack, Cronitor, a plain
# UptimeRobot heartbeat monitor. The ping is deliberately fire-and-forget: a
# heartbeat service being down must never stop the local alerting that does not
# depend on it.
set -uo pipefail

REPO_DIR="${LEDGERFLOW_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
STATE_DIR="${LEDGERFLOW_MONITOR_STATE:-/var/lib/ledgerflow-monitor}"
STATE_FILE="$STATE_DIR/state"

# Three consecutive failures before alerting. A single failed probe is usually
# a dropped packet or a deploy swapping containers, and an alert that cries
# wolf gets muted — at which point the monitor has negative value. With the
# 60s timer this means roughly three minutes to detection, against the six
# hours it actually took.
THRESHOLD="${ALERT_AFTER_FAILURES:-3}"

log() { printf '%s  %s\n' "$(date -u +%FT%TZ)" "$*"; }

mkdir -p "$STATE_DIR"
[ -f "$REPO_DIR/.env" ] || { log "No .env in $REPO_DIR"; exit 1; }
set -a; . "$REPO_DIR/.env"; set +a
: "${DOMAIN:?DOMAIN missing from .env}"

# ------------------------------------------------------------------- probe
probe() {
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$DOMAIN/readyz/" 2>/dev/null || echo 000)"
  echo "$code"
}

# ------------------------------------------------------------------ alerts
#
# Both channels are attempted independently: the point of having two is that
# one of them still works when the other's dependency is the thing that broke.
# Neither failing is allowed to abort the run.

notify_webhook() {
  local title="$1" body="$2"
  [ -n "${ALERT_WEBHOOK_URL:-}" ] || return 0

  # Slack, Discord and ntfy all accept a JSON body with a text field; sending
  # both keys covers the common shapes without needing to know which service
  # the URL belongs to.
  local payload
  payload="$(printf '%s\n\n%s' "$title" "$body" | python3 -c '
import json, sys
text = sys.stdin.read()
print(json.dumps({"text": text, "content": text}))
' 2>/dev/null)" || payload="{\"text\":\"$title\"}"

  if curl -s -o /dev/null --max-time 20 -X POST \
      -H 'Content-Type: application/json' \
      -d "$payload" "$ALERT_WEBHOOK_URL"; then
    log "Webhook alert sent."
  else
    log "Webhook alert FAILED."
  fi
}

notify_email() {
  local title="$1" body="$2"
  [ -n "${ALERT_EMAIL_TO:-}" ] || return 0
  [ -n "${ALERT_SMTP_URL:-}" ] || { log "ALERT_EMAIL_TO set but ALERT_SMTP_URL is not."; return 0; }

  local from="${ALERT_EMAIL_FROM:-ledgerflow@$DOMAIN}"
  local msg; msg="$(mktemp)"
  # A Date and Message-ID keep this out of spam folders that penalise their
  # absence — worth the four extra lines for a mail that only ever matters
  # when something is already wrong.
  {
    printf 'From: LedgerFlow Monitor <%s>\n' "$from"
    printf 'To: %s\n' "$ALERT_EMAIL_TO"
    printf 'Subject: %s\n' "$title"
    printf 'Date: %s\n' "$(date -R)"
    printf 'Message-ID: <%s@%s>\n' "$(date +%s).$$" "$DOMAIN"
    printf 'Content-Type: text/plain; charset=utf-8\n'
    printf '\n%s\n' "$body"
  } > "$msg"

  # `${auth[@]+...}` rather than a bare "${auth[@]}": under `set -u` an empty
  # array expansion is an error on bash 4.2, which is what RHEL 7 still ships.
  local auth=()
  [ -n "${ALERT_SMTP_USER:-}" ] && auth=(--user "${ALERT_SMTP_USER}:${ALERT_SMTP_PASSWORD:-}")

  if curl -s --max-time 30 --ssl-reqd \
      --url "$ALERT_SMTP_URL" \
      --mail-from "$from" \
      --mail-rcpt "$ALERT_EMAIL_TO" \
      ${auth[@]+"${auth[@]}"} \
      --upload-file "$msg"; then
    log "Email alert sent to $ALERT_EMAIL_TO."
  else
    log "Email alert FAILED."
  fi
  rm -f "$msg"
}

# Tell the external watchdog we are alive *and* the site answered.
heartbeat_ok() {
  [ -n "${MONITOR_HEARTBEAT_URL:-}" ] || return 0
  # Fire and forget, short timeout. If the watchdog is unreachable that is the
  # watchdog's problem to report, not a reason to delay or fail this run.
  curl -fsS -m 10 -o /dev/null "$MONITOR_HEARTBEAT_URL" 2>/dev/null \
    && log "Heartbeat sent." \
    || log "Heartbeat could not be sent (the watchdog will notice)."
  return 0
}


alert() {
  local title="$1" body="$2"
  notify_webhook "$title" "$body"
  notify_email   "$title" "$body"
}

# Fire one alert through the real channels and stop. Worth running at install
# time, because a webhook URL with a typo and an SMTP relay that rejects the
# sender are both indistinguishable from "no outages yet" until the day it
# matters. Exercises the same functions a genuine alert uses, so a pass here
# means the real path works.
if [ "${1:-}" = "--test-alert" ]; then
  alert "🧪 LedgerFlow monitor test — $DOMAIN" \
"Alerting works. If you can read this, the monitor can reach you.

Sent $(date -u +%FT%TZ) from $(hostname).
No outage: this was triggered by hand."
  exit 0
fi

# ------------------------------------------------------------------- state
failures=0
alerted=0
# shellcheck source=/dev/null
[ -f "$STATE_FILE" ] && . "$STATE_FILE"

save_state() {
  printf 'failures=%d\nalerted=%d\n' "$failures" "$alerted" > "$STATE_FILE"
}

# -------------------------------------------------------------------- main
code="$(probe)"

if [ "$code" = "200" ]; then
  # Only on success, and this is the whole point: the heartbeat must mean "I
  # checked and the site was up", not "this script ran". A ping sent regardless
  # of the result would keep the dead-man's switch quiet while the site was
  # down, which is worse than not having one.
  heartbeat_ok

  if [ "$alerted" -eq 1 ]; then
    # Recovery matters as much as the alert. Without it the only way to learn
    # the site came back is to check by hand, which is the habit the monitor
    # is supposed to replace.
    log "Recovered (readyz 200 after $failures failed probes)."
    alert "✅ LedgerFlow recovered — $DOMAIN" \
"$DOMAIN is serving again.

/readyz/ returned 200 after $failures consecutive failures.
Recovered at $(date -u +%FT%TZ)."
  fi
  failures=0
  alerted=0
  save_state
  exit 0
fi

failures=$((failures + 1))
log "Probe failed: /readyz/ returned ${code} (consecutive failures: $failures)."

if [ "$failures" -lt "$THRESHOLD" ]; then
  save_state
  exit 0
fi

if [ "$alerted" -eq 1 ]; then
  # Already alerted for this incident. Staying quiet is the whole reason the
  # threshold and this flag exist — a monitor that repeats itself every minute
  # trains people to ignore it, and then the next real outage goes unread.
  save_state
  exit 1
fi

log "Threshold reached; alerting."

# The diagnosis travels with the alert. Waking someone with "the site is down"
# and no cause means their first ten minutes go on the same commands every
# time; doctor.sh has already run them.
diagnosis="$(bash "$REPO_DIR/deploy/doctor.sh" --brief 2>&1 | sed 's/\x1b\[[0-9;]*m//g')"

alert "🔴 LedgerFlow is DOWN — $DOMAIN" \
"https://$DOMAIN/readyz/ returned ${code} on $failures consecutive checks.

First seen failing: $(date -u +%FT%TZ)

── Diagnosis ──────────────────────────────
$diagnosis

── Next steps ─────────────────────────────
  ssh into the host, then:
    sudo bash deploy/doctor.sh              # full detail
    sudo bash deploy/firewall-docker.sh     # if container networking failed

  The most common cause of a total outage on this host is the host
  firewall flushing Docker's iptables rules on reload. It presents as
  every container running and healthy while the app cannot reach the
  database. Restarting containers does not fix it; restarting Docker does."

alerted=1
save_state
exit 1
