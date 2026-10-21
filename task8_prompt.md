I am adding Celery Beat scheduling, retry policies, and overlap prevention to a Django 5 pipeline. Before writing code, critique my design decisions:

**My decisions:**

1. **Schedule** — ingest runs daily at 02:00 UTC, transform at 02:30 UTC. Justification: job boards update at most daily, and Remotive's terms discourage aggressive polling.

2. **Timeout/API down** — `autoretry_for=(FetchError,)`, `max_retries=3`, `retry_backoff=60`, `retry_backoff_max=300`. The task marks the `IngestionRun` as failed after all retries are exhausted.

3. **429 handling** — `FetchError` is already raised by `BaseJobSource._get()` on HTTP 429. I rely on the same retry policy as timeouts. Is this sufficient or does 429 need its own handling?

4. **Overlap prevention** — acquire a Redis lock keyed `ingest_lock:{source}` at task start using `cache.add()` (atomic). If the lock exists, log and return immediately without creating an `IngestionRun`. Release the lock in a `finally` block. Lock TTL = 1 hour.

5. **Bad records** — already handled inside `transform_raw_payloads()` — each record is wrapped in try/except, failures increment `IngestionRun.failed`, batch continues. No additional handling at the task level.

**Critique my decisions.** Tell me what is wrong, what the edge cases are, and what you would change. Then implement:
- `CELERY_BEAT_SCHEDULE` in `config/settings/base.py`
- Updated `task_ingest_jobs` and `task_transform_jobs` in `apps/ingestion/tasks.py` with retry policy, overlap lock, and `IngestionRun` integration
- Any change needed to `BaseJobSource._get()` to distinguish 429 from other errors

Use Django's cache framework for the Redis lock (already configured as the Celery broker). Do not add a new dependency just for locking.
