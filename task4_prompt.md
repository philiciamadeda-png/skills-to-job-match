
I need a transform service for my Django job pipeline that reads unprocessed `RawJobPayload` rows and writes structured `Job`, `Company`, and `Location` records.

**Models involved:**

`RawJobPayload` (`apps/ingestion/models.py`): `source`, `raw_data` (JSONField), `content_hash`, `processed` (bool), `job` (FK to Job, nullable)

`Company` (`apps/intelligence/models.py`): `name`, `normalised_name` (unique)

`Location` (`apps/intelligence/models.py`): `normalised_country`, `normalised_city`, `is_remote` — unique together on these three

`Job` (`apps/intelligence/models.py`): `source`, `source_id` (unique together), `title`, `company` (FK), `location` (FK), `job_type`, `salary_raw`, `url`, `description`, `posted_at`

**Two sources with different field names:**

Remotive raw fields: `id`, `title`, `company_name`, `job_type`, `salary`, `url`, `description`, `publication_date`, `candidate_required_location`

Arbeitnow raw fields: `slug`, `title`, `company_name`, `job_types` (list), `url`, `description`, `created_at`, `location`, `remote` (bool)

I need a mapper per source that normalises these into a common dict before writing.

**Requirements:**

1. Logic lives in `apps/intelligence/services.py` — not in a management command
2. Processes in batches (configurable batch size, default 200) — not all at once
3. Uses `normalize_company` and `normalize_location` from `apps/intelligence/utils.py` for `get_or_create` lookups
4. Re-runnable: if all payloads are reset to `processed=False` and the service runs again, it must produce identical `Job` rows with no duplicates and no errors — use `get_or_create` on `Job(source, source_id)`
5. Malformed payloads (missing required fields, mapping errors) are skipped and logged — they must not crash the batch
6. After a `Job` is successfully written, the `RawJobPayload` is marked `processed=True` and its `job` FK is set
7. Accepts an `IngestionRun` instance and updates its `created`, `skipped`, `failed` counts

Show me `apps/intelligence/services.py` with the transform service and the per-source mappers.
