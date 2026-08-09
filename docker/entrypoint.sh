#!/bin/sh
# Runs before every container start (web, worker, beat). Idempotent and safe
# to run concurrently from multiple replicas — Django's migration lock
# (implicit via Postgres advisory locks in recent versions) prevents races.
set -e

if [ "$DJANGO_SETTINGS_MODULE" != "config.settings.test" ]; then
    echo "Waiting for database..."
    python - <<'PYEOF'
import os, sys, time
import django
django.setup()
from django.db import connections
from django.db.utils import OperationalError

for _ in range(30):
    try:
        connections["default"].cursor()
        break
    except OperationalError:
        time.sleep(1)
else:
    sys.exit("Database never became available.")
PYEOF

    if [ "$RUN_MIGRATIONS" = "true" ]; then
        echo "Applying migrations..."
        python manage.py migrate --noinput

        # Idempotent (matches existing plans on tier/interval/currency) and
        # cheap, so it runs alongside migrations rather than needing its own
        # gate. Without this, a fresh environment's Plan table stays empty
        # forever — nothing else ever seeds it — and every new workspace's
        # best-effort start_trial call silently fails, leaving the sidebar
        # plan card and Upgrade button permanently blank with no visible error.
        echo "Seeding the plan catalogue..."
        python manage.py seed_plans
    fi

    if [ "$COLLECT_STATIC" = "true" ]; then
        echo "Collecting static files..."
        python manage.py collectstatic --noinput
    fi
fi

exec "$@"
