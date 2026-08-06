#!/usr/bin/env bash
# LedgerFlow — teach the host firewall about Docker, and prove it worked.
#
#   sudo bash deploy/firewall-docker.sh          # detect, reconcile, verify
#   sudo bash deploy/firewall-docker.sh --check  # verify only, change nothing
#
# Why this exists
# ---------------
# On 2026-08-06 this application was down for roughly six hours. Nothing was
# wrong with it. CSF — the control panel's firewall — rebuilt the iptables
# ruleset on a scheduled reload, and because its `DOCKER` option was off it
# rebuilt FORWARD as a bare `policy DROP` with no rules at all, discarding the
# chains Docker had installed at daemon start. Docker had no idea: it only
# writes those rules when it starts, so every container kept running and every
# connection between them silently timed out. Postgres was healthy the whole
# time; the application simply could not reach it.
#
# Restarting containers does not fix this, which is what makes it expensive to
# diagnose — the containers were never the problem.
#
# The same trap is set by every host firewall, not just CSF:
#
#   * CSF      rebuilds all chains on `csf -r`; DOCKER="0" means Docker's are
#              not restored. Ships on cPanel boxes, reloads from cron.
#   * UFW      defaults DEFAULT_FORWARD_POLICY to DROP, and forwarding between
#              containers is forwarding. deploy/provision.sh enables UFW, so
#              this repo has been shipping the latent version of this bug.
#   * firewalld  reloads flush the direct rules Docker added, with the same
#              result on the RHEL family that setup.sh targets.
#
# So the fix cannot be "configure CSF". It has to be: work out which firewall
# is in charge, apply that firewall's idiom for permitting the container
# network, and then — the part that actually matters — *test that a container
# can reach another container* rather than trusting that the configuration did
# what it claimed. Every check below is empirical for that reason.
#
# Idempotent. Safe to re-run, and worth re-running after any firewall change.
set -euo pipefail

# Kept deliberately in step with the `networks:` block in
# docker-compose.server.yml. Both are pinned so firewall rules can name them.
BRIDGE="${DOCKER_BRIDGE:-br-ledgerflow}"
SUBNET="${DOCKER_SUBNET:-172.28.0.0/16}"

# Rules are written against the whole private range rather than just $SUBNET.
# 172.16.0.0/12 spans 172.16–172.31, so it covers this stack, Docker's default
# bridge, and any other compose project on the box. The alternative — one rule
# per network — is precisely the arrangement that breaks when a network is
# recreated, which is the failure this script exists to prevent.
DOCKER_RANGE="172.16.0.0/12"

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
die()  { printf '\033[31m\n  ✗ %s\033[0m\n\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root: sudo bash deploy/firewall-docker.sh"
command -v docker >/dev/null 2>&1 || die "Docker is not installed on this host."

# --------------------------------------------------------------- which firewall
#
# More than one can be installed; only one is usually in charge. They are
# reported in order of how aggressively they rewrite the ruleset, and all
# detected ones get configured — a dormant UFW that someone enables next month
# should already have the right rules in it.
FIREWALLS=()
if command -v csf >/dev/null 2>&1 && [ -f /etc/csf/csf.conf ]; then
  FIREWALLS+=("csf")
fi
if command -v ufw >/dev/null 2>&1; then
  FIREWALLS+=("ufw")
fi
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
  FIREWALLS+=("firewalld")
fi

# ------------------------------------------------------------------- CSF
configure_csf() {
  local conf=/etc/csf/csf.conf changed=0

  # csf.conf is a flat KEY = "value" file. Rewriting in place with sed keeps
  # every other setting — and every comment — untouched, which matters on a
  # cPanel box where this file is the operator's, not ours.
  set_csf() {
    local key="$1" value="$2" current
    current="$(grep -E "^${key} = " "$conf" | head -1 | sed -E 's/^[^=]+= *"?([^"]*)"?.*/\1/')"
    if [ "$current" = "$value" ]; then
      return 0
    fi
    sed -i -E "s|^${key} = .*|${key} = \"${value}\"|" "$conf"
    info "csf.conf: ${key} ${current:-unset} -> ${value}"
    changed=1
  }

  set_csf DOCKER 1
  set_csf DOCKER_DEVICE "$BRIDGE"
  set_csf DOCKER_NETWORK4 "$DOCKER_RANGE"

  # Belt and braces, and the more important half. CSF's own DOCKER option only
  # covers the single device named above, and it can be switched back off by a
  # CSF upgrade, a restored config, or somebody tidying up. csfpost.sh runs
  # after *every* rebuild CSF does, so putting the rules here means they come
  # back whatever else changes — including for compose networks this script has
  # never heard of.
  local post=/etc/csf/csfpost.sh
  local marker="# --- ledgerflow docker rules ---"
  if ! grep -qF "$marker" "$post" 2>/dev/null; then
    [ -f "$post" ] || printf '#!/bin/sh\n' > "$post"
    cat >> "$post" <<POST

$marker
# Re-add the forwarding Docker needs. CSF flushes FORWARD on every rebuild and
# Docker only writes its rules at daemon start, so without this a reload
# silently severs every container-to-container connection on the host.
# -C tests for the rule first, so re-running cannot stack duplicates.
for _lf_br in \$(ip -o link show type bridge | awk -F': ' '{print \$2}' | grep -E '^(br-|docker)'); do
  iptables -C FORWARD -i "\$_lf_br" -o "\$_lf_br" -j ACCEPT 2>/dev/null || \\
    iptables -I FORWARD -i "\$_lf_br" -o "\$_lf_br" -j ACCEPT
  iptables -C FORWARD -i "\$_lf_br" ! -o "\$_lf_br" -j ACCEPT 2>/dev/null || \\
    iptables -I FORWARD -i "\$_lf_br" ! -o "\$_lf_br" -j ACCEPT
  iptables -C FORWARD -o "\$_lf_br" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || \\
    iptables -I FORWARD -o "\$_lf_br" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
done
# Egress from containers to the internet.
iptables -t nat -C POSTROUTING -s $DOCKER_RANGE ! -d $DOCKER_RANGE -j MASQUERADE 2>/dev/null || \\
  iptables -t nat -A POSTROUTING -s $DOCKER_RANGE ! -d $DOCKER_RANGE -j MASQUERADE
$marker end
POST
    chmod 700 "$post"
    info "Wrote Docker forwarding rules into /etc/csf/csfpost.sh"
    changed=1
  fi

  if [ "$changed" -eq 1 ]; then
    csf -r >/dev/null 2>&1 || warn "csf -r reported a problem; check 'csf -r' output."
    ok "CSF reconciled with Docker and reloaded."
  else
    ok "CSF already configured for Docker."
  fi
}

# ------------------------------------------------------------------- UFW
configure_ufw() {
  # `ufw route allow` writes into the user-forward chain, which is consulted
  # regardless of DEFAULT_FORWARD_POLICY. Targeting the bridge specifically is
  # deliberate: flipping DEFAULT_FORWARD_POLICY to ACCEPT would also turn this
  # host into a general-purpose router, which is a much larger change than
  # "containers may talk to each other".
  local before after
  before="$(ufw status 2>/dev/null || true)"

  ufw route allow in on "$BRIDGE" out on "$BRIDGE" >/dev/null 2>&1 || true
  ufw route allow in on "$BRIDGE" >/dev/null 2>&1 || true

  after="$(ufw status 2>/dev/null || true)"
  if [ "$before" = "$after" ]; then
    ok "UFW already permits the container network."
  else
    ok "UFW: allowed forwarding on $BRIDGE."
  fi

  # Reported rather than changed. On a host where UFW is installed but inactive
  # the rules above are stored and inert, which is the right outcome — but
  # somebody enabling UFW later should know forwarding is the thing to re-check.
  if ! ufw status 2>/dev/null | grep -q "Status: active"; then
    info "UFW is installed but inactive; the rules are stored for when it is enabled."
  fi
  if grep -q '^DEFAULT_FORWARD_POLICY="DROP"' /etc/default/ufw 2>/dev/null; then
    info "DEFAULT_FORWARD_POLICY is DROP (left alone) — the route rules above cover the bridge."
  fi
}

# --------------------------------------------------------------- firewalld
configure_firewalld() {
  # The bridge goes in the trusted zone: traffic between containers on a
  # private bridge is already inside the trust boundary, and firewalld's
  # per-zone model makes that a one-line statement rather than a rule set.
  if firewall-cmd --permanent --zone=trusted --query-interface="$BRIDGE" >/dev/null 2>&1; then
    ok "firewalld already trusts $BRIDGE."
    return 0
  fi
  firewall-cmd --permanent --zone=trusted --add-interface="$BRIDGE" >/dev/null 2>&1 \
    || warn "Could not add $BRIDGE to the trusted zone (does the bridge exist yet?)."
  firewall-cmd --permanent --zone=trusted --add-masquerade >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
  ok "firewalld: $BRIDGE trusted, masquerade enabled."
}

# ------------------------------------------------------------------ verify
#
# Configuration that has not been tested is a hypothesis. These checks are the
# reason the script can be trusted: they interrogate the running kernel and the
# running containers, not the config files that were just written.

verify_forward_chain() {
  local policy rules
  policy="$(iptables -S FORWARD 2>/dev/null | head -1)"
  rules="$(iptables -S FORWARD 2>/dev/null | tail -n +2 | wc -l | tr -d ' ')"

  if [ "$policy" = "-P FORWARD DROP" ] && [ "$rules" -eq 0 ]; then
    warn "FORWARD is 'policy DROP' with no rules — containers cannot reach each other."
    info "This is the exact state that caused the 2026-08-06 outage."
    return 1
  fi
  ok "FORWARD chain has $rules rule(s); traffic is not blanket-dropped."
}

verify_docker_chains() {
  if iptables -S 2>/dev/null | grep -q 'DOCKER-USER'; then
    ok "Docker's own chains are present in the ruleset."
  else
    warn "Docker's chains are missing — the daemon's rules have been flushed."
    info "Fix: systemctl restart docker  (re-inserts them; only restarts containers)"
    return 1
  fi
}

# The check that would have caught this outage in seconds. Everything else is
# inference about whether traffic should flow; this asks whether it does.
verify_container_connectivity() {
  local compose_file
  compose_file="$(dirname "${BASH_SOURCE[0]}")/docker-compose.server.yml"
  if ! docker compose -f "$compose_file" ps --status running 2>/dev/null | grep -q web; then
    info "Stack is not running; skipped the live container-to-container test."
    return 0
  fi

  local failed=0
  for target in "db 5432" "redis 6379"; do
    set -- $target
    if docker compose -f "$compose_file" exec -T web python -c "
import socket, sys
try:
    socket.create_connection(('$1', $2), timeout=5).close()
except Exception as exc:
    print(exc); sys.exit(1)
" >/dev/null 2>&1; then
      ok "web can reach $1:$2."
    else
      warn "web CANNOT reach $1:$2 — this is the outage signature."
      failed=1
    fi
  done
  return $failed
}

# ------------------------------------------------------------------- main
bold ""
bold "Docker and the host firewall"

info "Bridge $BRIDGE, stack subnet $SUBNET, rules written for $DOCKER_RANGE."

if [ "${#FIREWALLS[@]}" -eq 0 ]; then
  info "No CSF, UFW or firewalld found. Nothing to reconcile."
  info "If you add one later, re-run this script before trusting the stack."
else
  info "Detected: ${FIREWALLS[*]}"
  if [ "$CHECK_ONLY" -eq 1 ]; then
    info "(--check: reporting only, nothing was changed)"
  else
    for fw in "${FIREWALLS[@]}"; do
      case "$fw" in
        csf)       configure_csf ;;
        ufw)       configure_ufw ;;
        firewalld) configure_firewalld ;;
      esac
    done
  fi
fi

bold ""
bold "Verifying"
status=0
verify_forward_chain          || status=1
verify_docker_chains          || status=1
verify_container_connectivity || status=1

bold ""
if [ "$status" -eq 0 ]; then
  ok "Container networking is intact."
  echo
  exit 0
fi

warn "Container networking is NOT healthy."
echo
info "Most likely fix, in order:"
info "  1. systemctl restart docker      # re-inserts Docker's flushed rules"
info "  2. bash deploy/doctor.sh         # full diagnosis if that is not enough"
echo
exit 1
