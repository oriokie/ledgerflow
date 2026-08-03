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
    fi

    if [ "$COLLECT_STATIC" = "true" ]; then
        echo "Collecting static files..."
        python manage.py collectstatic --noinput
    fi
fi

exec "$@"
