#!/usr/bin/env bash
# LedgerFlow — teach the host firewall about Docker, and prove it worked.
#
#   sudo bash deploy/firewall-docker.sh               # detect, reconcile, verify
#   sudo bash deploy/firewall-docker.sh --check       # report only, change nothing
#   sudo bash deploy/firewall-docker.sh --no-repair   # configure, but never restart Docker
#
# Exit codes: 0 healthy · 1 container networking broken · 2 healthy but the
# stack is not yet on the pinned bridge (recreate the network when convenient).
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
NO_REPAIR=0
for arg in "$@"; do
  case "$arg" in
    --check)      CHECK_ONLY=1 ;;
    --no-repair)  NO_REPAIR=1 ;;
  esac
done

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

# Does the device the firewall was just pointed at actually exist? Writing a
# rule for a bridge that does not exist yet is how the config and the running
# stack drift apart without anything looking wrong.
verify_bridge_exists() {
  if ip link show "$BRIDGE" >/dev/null 2>&1; then
    ok "The bridge $BRIDGE exists."
    return 0
  fi
  warn "The firewall now allows $BRIDGE, but no such device exists yet."
  info "The stack is still on its old network. Until it is recreated, the rules"
  info "written above protect a bridge nothing is using — and the old one is no"
  info "longer named in the config."
  echo
  info "Recreate it, with the profiles the stack was brought up with:"
  print_recreate_commands
  return 1
}

print_recreate_commands() {
  # Profiles are not optional. Without them `down` leaves db and the internal
  # proxy running on the old network while everything else moves to the new
  # one, and they cannot then reach each other. This mirrors cd-agent.sh.
  cat <<'RECREATE'
      cd "$(dirname "$0")/.."
      set -a; . .env; set +a
      PROFILES="internal"; [ "${WEB_SERVER:-existing}" = "caddy" ] && PROFILES="caddy"
      [ "${DB_MODE:-bundled}" = "bundled" ] && PROFILES="$PROFILES,bundled-db"
      export COMPOSE_PROFILES="$PROFILES"
      docker compose -f deploy/docker-compose.server.yml down --remove-orphans
      docker compose -f deploy/docker-compose.server.yml up -d
RECREATE
  info 'Data is safe: "down" without -v never touches the pgdata volume.'
}

# Put Docker's flushed rules back, rather than advising somebody to.
#
# This script's whole job is to make container networking work, and it already
# mutates the host — it rewrites csf.conf and reloads CSF. Detecting the exact
# fault it exists to fix, knowing the one-line remedy, and then printing that
# remedy as a warning among four green ticks is how an operator reads it as
# advisory, runs "docker compose down", and finds that "up" cannot recreate the
# network because the chain it jumps to no longer exists. That is not a
# hypothetical: it is the 2026-08-06 second outage.
#
# Restarting Docker restarts this host's containers and nothing else. Against a
# host where "docker compose up" is already impossible, that is the cheaper
# side of the trade by a wide margin.
repair_docker_chains() {
  if [ "$CHECK_ONLY" -eq 1 ]; then
    info "(--check: would restart Docker to reinstate its chains)"
    return 1
  fi
  if [ "$NO_REPAIR" -eq 1 ]; then
    warn "Docker's chains are missing and --no-repair was given."
    info "Run: systemctl restart docker"
    return 1
  fi

  warn "Docker's chains are missing — restarting Docker to reinstate them."
  info "This restarts the containers on this host. Nothing else is affected."
  if ! systemctl restart docker; then
    die "Could not restart Docker. Run 'systemctl status docker' — nothing below will work until it starts."
  fi

  # Give the daemon a moment to write its rules before re-checking.
  for _ in $(seq 1 15); do
    iptables -S 2>/dev/null | grep -q 'DOCKER-USER' && break
    sleep 1
  done
  if iptables -S 2>/dev/null | grep -q 'DOCKER-USER'; then
    ok "Docker restarted and its chains are back."
    return 0
  fi
  warn "Docker restarted but its chains are still missing."
  return 1
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
verify_forward_chain || status=1

# Repaired rather than reported. The failure this detects makes `docker compose
# up` impossible, so leaving the host in it — with the remedy printed as a
# warning among green ticks — is how the operator proceeds to `down` and
# discovers there is no way back up.
if ! verify_docker_chains; then
  if repair_docker_chains; then
    verify_docker_chains || status=1
  else
    status=1
  fi
fi

verify_container_connectivity || status=1

# Checked last, and separately from the rest: this one is not a fault in the
# firewall, it is the firewall being correct about a state the stack has not
# caught up with yet.
bridge_missing=0
verify_bridge_exists || bridge_missing=1

bold ""
if [ "$status" -eq 0 ] && [ "$bridge_missing" -eq 0 ]; then
  ok "Container networking is intact."
  echo
  exit 0
fi

if [ "$status" -eq 0 ] && [ "$bridge_missing" -eq 1 ]; then
  # Everything works; the config is simply ahead of the running stack. That is
  # a real thing to act on but not an outage, and calling it one would train
  # people to ignore the times it is.
  warn "Container networking works, but the stack is not on the pinned bridge yet."
  echo
  exit 2
fi

warn "Container networking is NOT healthy."
echo
info "Next steps, in order:"
info "  1. bash deploy/doctor.sh         # full diagnosis, bottom of the stack up"
info "  2. recreate the network, with profiles:"
print_recreate_commands
echo
exit 1
