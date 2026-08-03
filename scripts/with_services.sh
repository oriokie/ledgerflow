#!/bin/bash
# Boot Postgres + Redis, then run whatever was passed.
#
# The sandbox reclaims background processes between bash invocations, so a
# daemon started in one call is gone by the next. Every command that touches
# the database therefore has to bring its own services up first; this script
# is that preamble, made idempotent so repeated use is cheap.
set -e

PGBIN=/usr/lib/postgresql/16/bin
PGDATA=/tmp/pgdata

if ! pg_isready -h localhost -p 5432 -q 2>/dev/null; then
  # A hard kill leaves a stale postmaster.pid that blocks startup.
  rm -f "$PGDATA/postmaster.pid"
  runuser -u postgres -- "$PGBIN/pg_ctl" -D "$PGDATA" -l /tmp/pg.log -o "-p 5432 -k /tmp" -w start >/dev/null
fi

redis-cli ping >/dev/null 2>&1 || redis-server --daemonize yes

for _ in $(seq 1 20); do
  pg_isready -h localhost -p 5432 -q 2>/dev/null && break
  sleep 0.5
done

cd /home/claude/work/ledgerflow
unset DJANGO_SETTINGS_MODULE
export DJANGO_SECRET_KEY=test

exec "$@"
