import logging

from celery import shared_task
from django.core.cache import cache

logger = logging.getLogger(__name__)

LOCK_KEY = 'aggregates_lock'
LOCK_TTL = 900  # 15 min


@shared_task
def refresh_aggregates() -> dict:
    """
    Rebuild the dashboard tables. Queued after every transform and extraction
    run, and once a day by Beat as a safety net.

    The lock stops two refreshes overlapping; the refresh itself is a full
    replace, so even back-to-back runs never double-count.
    """
    from apps.analytics import services

    if not cache.add(LOCK_KEY, '1', LOCK_TTL):
        logger.warning('refresh_aggregates: already running, skipping')
        return {'skipped': True, 'reason': 'overlap'}
    try:
        return services.refresh_aggregates()
    finally:
        cache.delete(LOCK_KEY)


def queue_refresh() -> None:
    """Queue a refresh without letting a broker hiccup fail the calling stage."""
    try:
        refresh_aggregates.delay()
    except Exception as exc:
        logger.error('could not queue refresh_aggregates — %s', exc.__class__.__name__)
