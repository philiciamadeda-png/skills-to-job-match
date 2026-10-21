# Skills to Job Match

A Django application that ingests remote job listings from public APIs, deduplicates them, and stores them for analysis. Built to support LLM-based skill extraction and job matching in later stages.

## Architecture

Raw job data flows through two stages. The **ingestion stage** fetches listings from external APIs (Remotive, Arbeitnow) and stores them as `RawJobPayload` rows — untouched JSON with a content hash for deduplication. The **transform stage** reads unprocessed payloads in batches, normalises company names and locations, resolves skills against a canonical vocabulary, and writes structured `Job`, `Company`, and `Location` records. Both stages run as Celery tasks on a schedule (every 2 hours for ingestion, 30 minutes later for transform), with Redis locks preventing overlapping runs and `IngestionRun` records logging every execution.

## Tech stack

- Python 3.12+, Django 6.x
- PostgreSQL 16+ (native install or Docker)
- Redis 7 — Celery broker, result backend, and distributed lock store
- Celery 5 + Celery Beat for task scheduling
- `django-environ` for environment config
- `requests` for HTTP ingestion
- `pytest` + `factory-boy` for tests

## Prerequisites

- Python 3.12 or newer
- PostgreSQL running locally (see below)
- Redis running locally or via Docker
- Git

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <repo-url>
cd skills-to-job-match
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install django django-environ psycopg2-binary requests celery redis pytest pytest-django factory-boy
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set your values. The required variables are:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key — any long random string |
| `ALLOWED_HOSTS` | Comma-separated hostnames, e.g. `localhost,127.0.0.1` |
| `DATABASE_URL` | Full Postgres URL, e.g. `postgres://skills_user:changeme@localhost:5432/skills_db` |
| `POSTGRES_DB` | Database name, e.g. `skills_db` |
| `POSTGRES_USER` | Database user, e.g. `skills_user` |
| `POSTGRES_PASSWORD` | Database password |
| `REDIS_URL` | Redis URL, e.g. `redis://localhost:6379/0` (defaults to this if unset) |

### 4. Start the containers (PostgreSQL + Redis)

```bash
docker compose up -d
```

This starts both `db` (PostgreSQL 16) and `redis` (Redis 7). To verify they are up:

```bash
docker compose ps
```

If you prefer a native PostgreSQL install instead:

```bash
sudo -u postgres psql -c "CREATE USER skills_user WITH PASSWORD 'changeme';"
sudo -u postgres psql -c "CREATE DATABASE skills_db OWNER skills_user;"
sudo -u postgres psql -c "ALTER USER skills_user CREATEDB;"
```

You will still need Redis running — `docker compose up -d redis` starts only the Redis container.

### 5. Run migrations

```bash
python manage.py migrate
```

### 6. Seed the skill vocabulary

```bash
python manage.py seed_skills
```

Loads 29 canonical skills and 73 aliases. Safe to run multiple times.

### 7. Create a superuser (optional, for admin access)

```bash
python manage.py createsuperuser
```

Then visit `http://127.0.0.1:8000/admin` after starting the server.

## Running the scheduled pipeline

Open three terminals (all with the virtualenv activated):

**Terminal 1 — Celery worker:**
```bash
celery -A config worker -l info
```

**Terminal 2 — Celery Beat scheduler:**
```bash
celery -A config beat -l info
```

**Terminal 3 — Django dev server (optional, for admin):**
```bash
python manage.py runserver
```

When everything is working you should see:

- Beat logging `task_ingest_jobs` and `task_transform_jobs` being sent every 2 hours / 30 minutes
- The worker logging `Task apps.ingestion.tasks.task_ingest_jobs succeeded`
- `IngestionRun` rows appearing in the admin at `/admin/ingestion/ingestionrun/` with `status=success` and non-zero `fetched`/`created` counts

## Running the ingestion command manually

```bash
python manage.py ingest_jobs --source remotive
python manage.py ingest_jobs --source arbeitnow --limit 300
```

Running either command a second time is safe — duplicate records are skipped automatically.

## Running the tests

```bash
pytest
pytest --cov=apps --cov-report=term-missing   # with coverage
```

All tests use a temporary test database and make no real network calls.

## Project structure

```
apps/
  core/           # Abstract base models (TimestampedModel)
  ingestion/      # RawJobPayload, IngestionRun, base source class, Remotive/Arbeitnow sources, ingest service, Celery tasks
  intelligence/   # Company, Location, Skill, SkillAlias, Job, JobSkill models; transform service; normalisation utils
  accounts/       # User accounts (placeholder)
  analytics/      # Analytics (placeholder)
config/
  celery.py       # Celery app configuration
  settings/
    base.py       # Shared settings (includes Celery Beat schedule)
    local.py      # Development overrides
    production.py # Production hardening
conftest.py       # pytest factories
pytest.ini        # pytest config
docker-compose.yml
```

## Progress

### Step 1 — Project scaffold
- Django project created with `config/` layout
- Split settings: `base.py` + `local.py`
- `django-environ` for env var management
- PostgreSQL 16 via Docker Compose (Redis stubbed for later)

### Step 2 — `.gitignore`
- Updated to include: `.venv/`, Celery artifacts, logs, coverage, OS/editor files

### Step 3 — `production.py`
- Added `config/settings/production.py` with `DEBUG=False`, `DATABASES` from env, and HTTPS/cookie security settings

### Step 4 — Database setup
- PostgreSQL 18 installed and running natively (Docker deferred — Pika OS PPA unreliable)
- Created `skills_db` database and `skills_user` role
- `manage.py migrate` ran clean — all Django core tables applied

### Step 5 — Apps scaffold
- Created `apps/` directory with `__init__.py`
- Created five apps: `accounts`, `core`, `ingestion`, `intelligence`, `analytics`
- Fixed `name` in each `apps.py` to use full dotted path (e.g. `apps.ingestion`)
- Updated `INSTALLED_APPS` in `base.py` with built-ins / third-party / local grouping

### Step 6 — Data models
- `TimestampedModel` abstract base in `apps/core/models.py`
- `RawJobPayload` in `apps/ingestion` with content hash dedup, processed flag, FK to Job
- `Company`, `Location`, `Skill`, `Job`, `JobSkill` in `apps/intelligence`
- Unique constraints on `Job(source, source_id)`, `Company.normalised_name`, `Skill.normalised_name`, `Location(normalised_country, normalised_city)`
- `JobSkill` through table with confidence score and extraction metadata
- Salary structured fields and embedding placeholder on `Job`
- Migrations created and applied

### Step 7 — Admin
- Registered `RawJobPayload`, `Company`, `Location`, `Skill`, `Job`, `JobSkill` in admin
- `raw_data` excluded from list view, kept as readonly in detail view
- `list_display`, `list_filter`, `search_fields`, `readonly_fields` configured for dev inspection

### Step 8 — Ingestion base class
- `BaseJobSource` abstract class in `apps/ingestion/base.py`
- Abstract interface: `source_name`, `fetch_page`, `parse_listings`, `has_next_page`
- Shared logic: `fetch_all` pagination loop, `_get` HTTP wrapper with retries
- `FetchError` custom exception for unrecoverable HTTP failures
- `requests` installed

### Step 9 — RemotiveSource
- `RemotiveSource` in `apps/ingestion/sources/remotive.py`
- Fetches from `https://remotive.com/api/remote-jobs` — no auth required
- Supports optional `limit` param for dev batches
- `has_next_page` always returns `False` (single-page API)
- Verified against live API — fetched real job listings

### Step 10 — Ingestion service and management command
- `apps/ingestion/services.py` — `ingest_from_source()` with hash dedup and `bulk_create`
- `manage.py ingest_jobs --source remotive --limit N` management command
- Hash computed from stable content fields only (`id`, `title`, `company_name`, `description`, `job_type`, `salary`, `candidate_required_location`)
- Verified: first run saves, second run skips all duplicates

### Step 19 — Scheduling, retries, and failure handling
- `RateLimitError(FetchError)` added to `base.py` — raised specifically on HTTP 429, separate from generic `FetchError`; 429 removed from session-level `Retry` so task-level backoff controls it
- `CELERY_BEAT_SCHEDULE` in `base.py` — ingest both sources every 2h (dev), transform 30min later; change to `crontab(hour=2)` for production
- `CACHES` configured in `base.py` using Redis (db 1) for Django cache framework — used for distributed locks
- `task_ingest_jobs` — `autoretry_for=(FetchError,)` max 3 retries, 60s backoff; `RateLimitError` overrides to 300s countdown; Redis lock prevents overlap; `IngestionRun` records every run with counts and duration
- `task_transform_jobs` — Redis lock prevents overlap; `IngestionRun` records every run; retries on unexpected exceptions
- Lock TTL = 1 hour; atomic `cache.add()` prevents race conditions; released in `finally` block

### Step 18 — Celery + Redis
- Redis service added to `docker-compose.yml` (`redis:7-alpine`, port 6379)
- `config/celery.py` — Celery app with `autodiscover_tasks`, defaults to `config.settings.local`
- `config/__init__.py` — exports `celery_app` so Django loads it on startup
- `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, serializer settings added to `base.py`; broker URL read from `REDIS_URL` env var (default `redis://localhost:6379/0`)
- `apps/ingestion/tasks.py` — `task_ingest_jobs(source, limit, max_pages)` and `task_transform_jobs(batch_size)` as thin wrappers over existing service functions
- `celery` and `redis` packages installed

### Step 17 — Cross-source deduplication
- `normalised_title` field added to `Job` — populated by transform service and backfilled on existing rows
- `canonical` self-FK on `Job` — `null` = canonical record, non-null = duplicate pointing at its canonical; preserves both source references, fully reversible
- `deduplicate_jobs(dry_run)` in `apps/intelligence/services.py` — matches on `(normalised_title, company)` across different sources; earliest-created job wins
- `normalize_title()` added to `apps/intelligence/utils.py`
- `dry_run=True` mode counts matches without writing — use this to measure catch rate before committing
- Migration `0004_job_dedup_fields` applied
- 0 cross-source duplicates in current dataset (Remotive and Arbeitnow have non-overlapping job pools)

### Step 16 — Skill vocabulary layer
- `SkillAlias` model added to `apps/intelligence/models.py` — maps many raw strings to one canonical `Skill`
- `is_auto_created` flag on `Skill` — skills created by the resolver at runtime are flagged for human review
- `normalize_skill(raw)` in `apps/intelligence/utils.py` — strips non-alphanumeric, lowercases; `"PostgreSQL"` and `"Postgres"` both produce `"postgresql"`
- `resolve_skill(raw)` in `apps/intelligence/services.py` — lookup order: alias table → canonical key → auto-create; idempotent
- `apps/intelligence/fixtures/skills_seed.py` — 29 canonical skills, 73 aliases across databases, languages, frameworks, cloud, and data tools
- `python manage.py seed_skills` loads seed data idempotently
- Migration `0003_skill_alias` applied

### Step 15 — Transform service
- `apps/intelligence/services.py` — `transform_raw_payloads(run, batch_size)` reads unprocessed `RawJobPayload` rows in batches and writes `Job`, `Company`, `Location`
- Per-source mappers (`_map_remotive`, `_map_arbeitnow`) normalise different field names into a common dict before writing
- `get_or_create` on `Job(source, source_id)` — fully re-runnable; resetting all payloads to `processed=False` and rerunning produces identical rows, no duplicates
- Malformed payloads are caught, logged, and counted as `failed` — batch continues
- `RawJobPayload.processed` and `.job` FK set only after successful write
- Accepts optional `IngestionRun` instance and updates `created`, `skipped`, `failed` counts
- Fixed `Job.contract_type` max_length 50→100 and `Job.external_url` max_length 200→500 to handle real Arbeitnow data; migration `0002_fix_field_lengths` applied

### Step 14 — Normalisation utilities
- `apps/intelligence/utils.py` — two pure functions, no DB access, fully idempotent
- `normalize_company(name)` — collapses whitespace, strips legal suffixes (Inc, LLC, Ltd, GmbH, Pty Ltd, BV, SA, AB), lowercases; `"Google LLC"` and `"Google, Inc."` both produce `"google"`
- `normalize_location(text)` — returns `{is_remote, country, city, raw}`; detects remote keywords, maps country hints to ISO 3166-1 alpha-2, extracts city from `"City, Country"` pattern; unparseable input preserved in `raw`

### Step 13 — ArbeitnowSource and pagination fix
- `fetch_all(max_pages)` parameter added to `BaseJobSource` — minimal change to support paginated sources without redesigning the base class
- `ArbeitnowSource` in `apps/ingestion/sources/arbeitnow.py`
- Fetches from `https://www.arbeitnow.com/api/job-board-api` — no auth required, 300 jobs/page
- Pagination driven by `links.next` in the response (`None` = last page)
- `max_pages` constructor arg caps pages fetched during development
- Verified: 2-page cap returns 600 listings with correct field shape


- `IngestionRun` model in `apps/ingestion/models.py` to log every pipeline run
- `Stage` choices: `ingest`, `transform`; `Status` choices: `running`, `success`, `failed` — both use `TextChoices` for human-readable DB values
- Tracks `started_at`, `finished_at`, counts (`fetched`, `created`, `skipped`, `failed`), and `error` text
- `duration` is a computed `@property` (no stored field) derived from `finished_at - started_at`
- Composite index on `(status, -started_at)` for efficient "last N failed runs" queries
- `ingestion_run(stage, source)` context manager handles run lifecycle: creates the record, sets `success`/`failed` status, captures exception message, saves on exit
- Migration `0002_ingestion_run` created and applied

### Step 11 — Tests
- `pytest`, `pytest-django`, `factory-boy` installed
- `conftest.py` with `CompanyFactory`, `LocationFactory`, `JobFactory`, `RawJobPayloadFactory`
- 4 tests in `apps/ingestion/tests/test_ingestion.py` — all passing
- Covers: model creation, content hash stability, mocked HTTP parsing, dedup on double ingest

### Step 20 — Transform service tests
- 4 tests in `apps/intelligence/tests/test_transform.py` — all passing (8 total across suite)
- JSON fixtures in `apps/intelligence/tests/fixtures/` — `remotive_backend_engineer.json` and `arbeitnow_backend_engineer.json` store realistic per-source payloads for the same role; preferred over inline dicts because they mirror real API contracts, are reusable across test files, and produce clean git diffs
- `test_transform_twice_no_duplicate_jobs` — resets `processed=False` and re-runs transform; asserts `Job.objects.count() == 1`
- `test_normalisation_collapses_variants` — `"Acme Corp"` and `"Acme Corp, Inc."` collapse to one `Company`; `"PostgreSQL"` and `"Postgres"` resolve to one `Skill` via alias table
- `test_cross_source_dedup_links_jobs` — two payloads for the same role from different sources produce 2 `Job` rows; `deduplicate_jobs()` links the arbeitnow duplicate to the remotive canonical; asserts on `source_id` values, not just count (guards against false positives)
- `test_malformed_payload_skipped_rest_processed` — payload with `id=None` fails, good payload in same batch succeeds, error is captured in logs
