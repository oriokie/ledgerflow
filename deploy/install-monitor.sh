#!/usr/bin/env bash
# Installs the health monitor as a systemd timer.
#
#   sudo bash deploy/install-monitor.sh            # install and start
#   sudo bash deploy/install-monitor.sh --test     # send a test alert, then exit
#   sudo bash deploy/install-monitor.sh --remove   # take it back off
#
# Idempotent: re-running updates the unit files and restarts the timer.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INTERVAL="${MONITOR_INTERVAL:-1min}"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
die()  { printf '\033[31m\n  ✗ %s\033[0m\n\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root: sudo bash deploy/install-monitor.sh"
command -v systemctl >/dev/null 2>&1 || die "This host has no systemd."

if [ "${1:-}" = "--remove" ]; then
  systemctl disable --now ledgerflow-monitor.timer 2>/dev/null || true
  rm -f /etc/systemd/system/ledgerflow-monitor.{service,timer}
  systemctl daemon-reload
  ok "Monitor removed. Nothing is watching the site now."
  exit 0
fi

[ -f "$REPO_DIR/.env" ] || die "No .env in $REPO_DIR — run deploy/setup.sh first."

# Refuse to install a monitor that cannot reach anybody. A timer that probes
# faithfully and has no way to tell you is worse than no monitor: it looks like
# coverage on the next incident review, and it is not.
have_channel=0
grep -qE '^ALERT_WEBHOOK_URL=.+' "$REPO_DIR/.env" && have_channel=1
grep -qE '^ALERT_EMAIL_TO=.+'    "$REPO_DIR/.env" && have_channel=1

if [ "$have_channel" -eq 0 ]; then
  bold ""
  warn "No alert channel is configured in .env — the monitor would have nobody to tell."
  echo
  info "Add at least one of these, then re-run:"
  echo
  info "  # Webhook — Slack, Discord, ntfy. Simplest, and independent of mail."
  info "  ALERT_WEBHOOK_URL=https://hooks.slack.com/services/..."
  echo
  info "  # Email — needs an SMTP relay it can authenticate to."
  info "  ALERT_EMAIL_TO=you@example.com"
  info "  ALERT_EMAIL_FROM=ledgerflow@yourdomain.com"
  info "  ALERT_SMTP_URL=smtps://smtp.example.com:465"
  info "  ALERT_SMTP_USER=apikey"
  info "  ALERT_SMTP_PASSWORD=..."
  echo
  info "  # Optional — alert after N consecutive failed probes (default 3)."
  info "  ALERT_AFTER_FAILURES=3"
  echo
  die "Refusing to install a monitor with no way to reach you."
fi

if [ "${1:-}" = "--test" ]; then
  bold ""
  bold "Sending a test alert"
  LEDGERFLOW_DIR="$REPO_DIR" bash "$REPO_DIR/deploy/health-monitor.sh" --test-alert
  echo
  ok "Test alert dispatched. Check the channel(s) you configured."
  info "Nothing was installed — re-run without --test to install the timer."
  echo
  exit 0
fi

cat > /etc/systemd/system/ledgerflow-monitor.service <<UNIT
[Unit]
Description=LedgerFlow health monitor (alerts when the site stops serving)
After=docker.service

[Service]
Type=oneshot
Environment=LEDGERFLOW_DIR=$REPO_DIR
ExecStart=/usr/bin/env bash $REPO_DIR/deploy/health-monitor.sh
StandardOutput=journal
StandardError=journal
# A failed probe exits non-zero by design; that is the signal, not a fault.
SuccessExitStatus=0 1
UNIT

cat > /etc/systemd/system/ledgerflow-monitor.timer <<UNIT
[Unit]
Description=Check that LedgerFlow is still serving

[Timer]
OnBootSec=3min
OnUnitActiveSec=$INTERVAL
# Persistent so a probe still runs after the host was asleep or the timer was
# stopped, rather than silently skipping until the next natural tick.
Persistent=true
Unit=ledgerflow-monitor.service

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now ledgerflow-monitor.timer

bold ""
ok "Health monitor installed, probing every $INTERVAL."
echo
info "It probes https://\$DOMAIN/readyz/ — readiness, not liveness, so a"
info "database or cache outage actually registers instead of returning 200."
echo
info "Alerts fire after 3 consecutive failures (~3 minutes) and carry the"
info "output of deploy/doctor.sh, so the cause arrives with the notification."
echo
info "Watch it        journalctl -u ledgerflow-monitor -f"
info "Probe now       systemctl start ledgerflow-monitor"
info "Test alerting   sudo bash deploy/install-monitor.sh --test"
info "Remove it       sudo bash deploy/install-monitor.sh --remove"
echo
warn "This monitor runs on the host it watches. It cannot report a dead host —"
info "for that, point an external check (Healthchecks.io, UptimeRobot,"
info "BetterStack) at https://\$DOMAIN/readyz/ as well. The two are complements."
echo
