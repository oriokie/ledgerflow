"""Periodic live FX refresh."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="fx.refresh_rates")
def refresh_rates_task(*, force: bool = False) -> int:
    """Beat entrypoint. Honours the console's auto-refresh switch so an
    operator who has pinned manual rates is not fighting the overnight job."""
    from apps.fx.providers import RateProviderError
    from apps.fx.services import refresh_rates
    from apps.platform_admin.settings_store import get

    if not force and not get("fx.auto_refresh"):
        logger.info("FX auto-refresh is off.")
        return 0
    try:
        result = refresh_rates(force=force)
    except RateProviderError:
        logger.exception("Scheduled FX refresh failed.")
        return 0
    return int(result["updated"])
