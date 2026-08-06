#!/usr/bin/env bash
# LedgerFlow — is this host actually serving, and if not, why?
#
#   sudo bash deploy/doctor.sh          # full diagnosis
#   sudo bash deploy/doctor.sh --brief  # one line per check, for alert bodies
#
# Written after an outage that took hours to diagnose because the evidence was
# scattered: container health in `docker compose ps`, the real error in the web
# logs, the cause in `iptables -S`, and the proof in a socket test nobody had a
# reason to run. Each was a separate command with a separate mental model. This
# collects them in the order that narrows the problem fastest, so the next
# incident starts from an answer instead of a search.
#
# The ordering is deliberate — bottom of the stack upward. A failure low down
# explains every failure above it, so the first FAIL is nearly always the one
# worth acting on, and everything under it is noise.
#
# Exits non-zero if anything is wrong, so the health monitor can attach the
# output to an alert without interpreting it.
set -uo pipefail   # not -e: a failing check is data, not a reason to stop

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$REPO_DIR/deploy/docker-compose.server.yml"

BRIEF=0
[ "${1:-}" = "--brief" ] && BRIEF=1

FAILURES=0
FIRST_FAILURE=""

bold()  { [ "$BRIEF" -eq 1 ] || printf '\033[1m%s\033[0m\n' "$*"; }
info()  { [ "$BRIEF" -eq 1 ] || printf '  %s\n' "$*"; }
pass()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
fail()  {
  printf '  \033[31m✗\033[0m %s\n' "$*"
  FAILURES=$((FAILURES + 1))
  [ -n "$FIRST_FAILURE" ] || FIRST_FAILURE="$*"
}
fixhint() { [ "$BRIEF" -eq 1 ] || printf '      \033[33m→ %s\033[0m\n' "$*"; }

[ -f "$COMPOSE_FILE" ] || { echo "No compose file at $COMPOSE_FILE"; exit 2; }
dc() { docker compose -f "$COMPOSE_FILE" "$@"; }

DOMAIN=""
if [ -f "$REPO_DIR/.env" ]; then
  DOMAIN="$(grep -E '^DOMAIN=' "$REPO_DIR/.env" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
fi

# ------------------------------------------------------------------ 1. host
bold ""
bold "Host"

if systemctl is-active --quiet docker 2>/dev/null; then
  pass "Docker daemon is running."
else
  fail "Docker daemon is NOT running."
  fixhint "systemctl start docker"
fi

disk_pct="$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
if [ "${disk_pct:-0}" -ge 90 ]; then
  fail "Disk is ${disk_pct}% full on /."
  fixhint "docker system prune -af --volumes   # after checking what it would remove"
else
  pass "Disk ${disk_pct}% used on /."
fi

mem_avail_mb="$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)"
if [ "${mem_avail_mb:-0}" -lt 200 ] && [ "${mem_avail_mb:-0}" -gt 0 ]; then
  fail "Only ${mem_avail_mb}MB memory available."
else
  pass "${mem_avail_mb}MB memory available."
fi

# ------------------------------------------------------- 2. packet forwarding
#
# Before containers, before the app: if the kernel will not forward between
# containers, everything above this line is going to fail in ways that look
# like application bugs. This is where the 2026-08-06 outage actually lived.
bold ""
bold "Container networking"

fwd_policy="$(iptables -S FORWARD 2>/dev/null | head -1)"
fwd_rules="$(iptables -S FORWARD 2>/dev/null | tail -n +2 | wc -l | tr -d ' ')"
if [ "$fwd_policy" = "-P FORWARD DROP" ] && [ "${fwd_rules:-0}" -eq 0 ]; then
  fail "iptables FORWARD is 'policy DROP' with no rules — all container traffic is dropped."
  fixhint "A host firewall (CSF/UFW/firewalld) flushed Docker's rules."
  fixhint "systemctl restart docker && sudo bash deploy/firewall-docker.sh"
else
  pass "FORWARD chain has ${fwd_rules:-0} rule(s)."
fi

if iptables -S 2>/dev/null | grep -q 'DOCKER-USER'; then
  pass "Docker's iptables chains are present."
else
  fail "Docker's iptables chains are missing — its rules were flushed."
  fixhint "systemctl restart docker"
fi

for fw in csf ufw firewalld; do
  case "$fw" in
    csf)
      command -v csf >/dev/null 2>&1 || continue
      if grep -qE '^DOCKER = "1"' /etc/csf/csf.conf 2>/dev/null; then
        pass "CSF is present and configured for Docker."
      else
        fail "CSF is present with DOCKER disabled — it will flush Docker's rules on reload."
        fixhint "sudo bash deploy/firewall-docker.sh"
      fi
      ;;
    ufw)
      command -v ufw >/dev/null 2>&1 || continue
      ufw status 2>/dev/null | grep -q "Status: active" || continue
      if ufw status 2>/dev/null | grep -q "br-ledgerflow"; then
        pass "UFW is active and permits the container bridge."
      else
        fail "UFW is active but has no rule for the container bridge."
        fixhint "sudo bash deploy/firewall-docker.sh"
      fi
      ;;
    firewalld)
      systemctl is-active --quiet firewalld 2>/dev/null || continue
      if firewall-cmd --zone=trusted --query-interface=br-ledgerflow >/dev/null 2>&1; then
        pass "firewalld is active and trusts the container bridge."
      else
        fail "firewalld is active but does not trust the container bridge."
        fixhint "sudo bash deploy/firewall-docker.sh"
      fi
      ;;
  esac
done

# ------------------------------------------------------------ 3. containers
bold ""
bold "Containers"

ps_out="$(dc ps --format '{{.Service}}\t{{.State}}\t{{.Status}}' 2>/dev/null)"
if [ -z "$ps_out" ]; then
  fail "No containers are running."
  fixhint "docker compose -f $COMPOSE_FILE up -d"
else
  while IFS=$'\t' read -r svc state status; do
    [ -n "$svc" ] || continue
    case "$status" in
      *unhealthy*) fail "$svc is unhealthy — $status" ;;
      *"health: starting"*) info "  … $svc is still starting — $status" ;;
      *Up*|*running*) pass "$svc is up — $status" ;;
      *) fail "$svc is $state — $status" ;;
    esac
  done <<< "$ps_out"
fi

# --------------------------------------------------- 4. the dependency test
#
# The single most diagnostic check here. A raw socket, no Django and no
# psycopg, so a failure means the network path is broken rather than the
# application being misconfigured — a distinction that took hours to establish
# by hand during the outage.
bold ""
bold "Can the app reach its dependencies?"

if dc ps --status running 2>/dev/null | grep -q web; then
  for target in "db 5432 Postgres" "redis 6379 Redis"; do
    set -- $target
    host="$1"; port="$2"; label="$3"
    if err="$(dc exec -T web python -c "
import socket, sys
try:
    socket.create_connection(('$host', $port), timeout=5).close()
except Exception as exc:
    print(type(exc).__name__ + ': ' + str(exc)); sys.exit(1)
" 2>&1)"; then
      pass "web reaches $label at $host:$port."
    else
      fail "web CANNOT reach $label at $host:$port — ${err:-timeout}"
      fixhint "Raw TCP failed, so this is the network, not Django."
      fixhint "systemctl restart docker && sudo bash deploy/firewall-docker.sh"
    fi
  done
else
  fail "web is not running; cannot test its dependencies."
fi

# ------------------------------------------------------------- 5. endpoints
bold ""
bold "Endpoints"

if [ -n "$DOMAIN" ]; then
  # /readyz/ rather than /healthz/ on purpose: liveness deliberately checks
  # nothing external, so it can return 200 while the database is unreachable.
  # Readiness is the one that would have gone red at 04:04.
  for path in healthz readyz; do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://$DOMAIN/$path/" 2>/dev/null || echo 000)"
    case "$code" in
      200) pass "https://$DOMAIN/$path/ → 200" ;;
      000) fail "https://$DOMAIN/$path/ → no response (connection failed)" ;;
      502|503|504) fail "https://$DOMAIN/$path/ → $code (proxy cannot reach the app)" ;;
      *)   fail "https://$DOMAIN/$path/ → $code" ;;
    esac
  done
else
  info "No DOMAIN in .env; skipped public endpoint checks."
fi

# -------------------------------------------------------- 6. recent errors
if [ "$BRIEF" -eq 0 ] && [ "$FAILURES" -gt 0 ]; then
  bold ""
  bold "Recent web errors (last 15)"
  dc logs web --tail 200 2>/dev/null \
    | grep -oE '"message": "[^"]{0,120}' \
    | sed 's/"message": "/  /' \
    | tail -15 \
    || info "  (none found)"
fi

# ---------------------------------------------------------------- verdict
bold ""
if [ "$FAILURES" -eq 0 ]; then
  printf '\033[32m  ✓ All checks passed.\033[0m\n\n'
  exit 0
fi

printf '\033[31m  ✗ %d check(s) failed.\033[0m\n' "$FAILURES"
[ "$BRIEF" -eq 1 ] || printf '\n  Start with the first failure — later ones are usually consequences of it:\n    %s\n\n' "$FIRST_FAILURE"
exit 1
