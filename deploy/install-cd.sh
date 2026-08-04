#!/usr/bin/env bash
# Installs the pull-based CD agent as a systemd timer.
#
#   sudo bash deploy/install-cd.sh            # install and start
#   sudo bash deploy/install-cd.sh --remove   # take it back off
#
# Idempotent: re-running updates the unit files and restarts the timer.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INTERVAL="${CD_INTERVAL:-1min}"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
die()  { printf '\033[31m\n  ✗ %s\033[0m\n\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root: sudo bash deploy/install-cd.sh"
command -v systemctl >/dev/null 2>&1 || die "This host has no systemd."

if [ "${1:-}" = "--remove" ]; then
  systemctl disable --now ledgerflow-cd.timer 2>/dev/null || true
  rm -f /etc/systemd/system/ledgerflow-cd.{service,timer}
  systemctl daemon-reload
  ok "CD agent removed. Nothing deploys automatically now."
  exit 0
fi

[ -f "$REPO_DIR/.env" ] || die "No .env in $REPO_DIR — run deploy/setup.sh first."

cat > /etc/systemd/system/ledgerflow-cd.service <<UNIT
[Unit]
Description=LedgerFlow continuous delivery (checks for a promoted release)
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
Environment=LEDGERFLOW_DIR=$REPO_DIR
ExecStart=/usr/bin/env bash $REPO_DIR/deploy/cd-agent.sh
# The agent logs to stdout; journald keeps it with the unit.
StandardOutput=journal
StandardError=journal
UNIT

cat > /etc/systemd/system/ledgerflow-cd.timer <<UNIT
[Unit]
Description=Check for a promoted LedgerFlow release

[Timer]
OnBootSec=2min
OnUnitActiveSec=$INTERVAL
# Spread the load if several services ever share this schedule.
RandomizedDelaySec=15
Unit=ledgerflow-cd.service

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now ledgerflow-cd.timer

bold ""
ok "CD agent installed, checking every $INTERVAL."
echo
info "It deploys only what CI promoted to :released — which happens after the"
info "whole pipeline passes and you approve the promotion on GitHub."
echo
info "Watch it       journalctl -u ledgerflow-cd -f"
info "Deploy now     systemctl start ledgerflow-cd"
info "Pause it       systemctl disable --now ledgerflow-cd.timer"
info "Remove it      sudo bash deploy/install-cd.sh --remove"
echo
