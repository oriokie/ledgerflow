"""Celery application entrypoint.

Broker/backend, serialization, retry, and beat-schedule config all live in
`config/settings/base.py` (CELERY_* keys) so there is one source of truth
shared between the web process and workers.
"""

from __future__ import annotations

import os

from celery import Celery
from celery.signals import setup_logging as celery_setup_logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("ledgerflow")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@celery_setup_logging.connect
def _use_django_logging_config(**kwargs):
    """Reuse Django's LOGGING config (JSON formatter, request-id filter)
    instead of Celery's own logging setup, so worker logs match web logs."""
    from logging.config import dictConfig

    from django.conf import settings

    dictConfig(settings.LOGGING)
