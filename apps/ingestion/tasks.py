import logging
from celery import shared_task
from django.core.cache import cache

from apps.ingestion.base import FetchError, RateLimitError

logger = logging.getLogger(__name__)

LOCK_TTL = 3600  # 1 hour — covers max expected run time


def _acquire_lock(key: str) -> bool:
    """Atomic set-if-not-exists. Returns True if lock was acquired."""
    return cache.add(key, '1', LOCK_TTL)


def _release_lock(key: str) -> None:
    cache.delete(key)


@shared_task(
    bind=True,
    autoretry_for=(FetchError,),
    max_retries=3,
    retry_backoff=60,
    retry_backoff_max=300,
    retry_jitter=True,
)
def task_ingest_jobs(self, source: str, limit: int | None = None, max_pages: int | None = None):
    from apps.ingestion.sources.remotive import RemotiveSource
    from apps.ingestion.sources.arbeitnow import ArbeitnowSource
    from apps.ingestion.services import ingest_from_source
    from apps.ingestion.models import ingestion_run

    lock_key = f'ingest_lock:{source}'
    if not _acquire_lock(lock_key):
        logger.warning('task_ingest_jobs: %s already running, skipping', source)
        return {'skipped': True, 'reason': 'overlap'}

    try:
        with ingestion_run('ingest', source) as run:
            sources = {'remotive': RemotiveSource, 'arbeitnow': ArbeitnowSource}
            kwargs = {k: v for k, v in {'limit': limit, 'max_pages': max_pages}.items() if v is not None}
            src = sources[source](**kwargs)
            jobs = src.fetch_all()
            result = ingest_from_source(src.source_name, jobs)
            run.fetched = result['total']
            run.created = result['saved']
            run.skipped = result['skipped']
            return result
    except RateLimitError as exc:
        # Longer backoff for rate limiting — override retry delay
        raise self.retry(exc=exc, countdown=300)
    finally:
        _release_lock(lock_key)


@shared_task(
    bind=True,
    max_retries=2,
    retry_backoff=30,
)
def task_transform_jobs(self, batch_size: int = 200):
    from apps.intelligence.services import transform_raw_payloads
    from apps.ingestion.models import ingestion_run

    lock_key = 'ingest_lock:transform'
    if not _acquire_lock(lock_key):
        logger.warning('task_transform_jobs: already running, skipping')
        return {'skipped': True, 'reason': 'overlap'}

    try:
        with ingestion_run('transform', 'all') as run:
            result = transform_raw_payloads(run=run, batch_size=batch_size)
            return result
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        _release_lock(lock_key)
