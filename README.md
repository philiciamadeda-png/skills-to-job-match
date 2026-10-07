# Skills to Job Match

A Django application that ingests remote job listings from public APIs, deduplicates them, and stores them for analysis. Built to support LLM-based skill extraction and job matching in later stages.

## Tech stack

- Python 3.12+, Django 6.x
- PostgreSQL 16+ (native install or Docker)
- `django-environ` for environment config
- `requests` for HTTP ingestion
- `pytest` + `factory-boy` for tests

## Prerequisites

- Python 3.12 or newer
- PostgreSQL running locally (see below)
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
pip install django django-environ psycopg2-binary requests pytest pytest-django factory-boy
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

### 4. Create the database

If you have PostgreSQL installed natively:

```bash
sudo -u postgres psql -c "CREATE USER skills_user WITH PASSWORD 'changeme';"
sudo -u postgres psql -c "CREATE DATABASE skills_db OWNER skills_user;"
sudo -u postgres psql -c "ALTER USER skills_user CREATEDB;"
```

If you prefer Docker:

```bash
docker compose up -d
```

### 5. Run migrations

```bash
python manage.py migrate
```

### 6. Create a superuser (optional, for admin access)

```bash
python manage.py createsuperuser
```

Then visit `http://127.0.0.1:8000/admin` after starting the server.

## Running the ingestion command

Fetch job listings from Remotive and store them as raw payloads:

```bash
python manage.py ingest_jobs --source remotive
```

Running it a second time is safe — duplicate records are skipped automatically.

## Running the tests

```bash
pytest
```

All tests use a temporary test database and make no real network calls.

## Project structure

```
apps/
  core/           # Abstract base models (TimestampedModel)
  ingestion/      # RawJobPayload model, base source class, RemotiveSource, ingest service
  intelligence/   # Company, Location, Skill, Job, JobSkill models
  accounts/       # User accounts (placeholder)
  analytics/      # Analytics (placeholder)
config/
  settings/
    base.py       # Shared settings
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

### Step 11 — Tests
- `pytest`, `pytest-django`, `factory-boy` installed
- `conftest.py` with `CompanyFactory`, `LocationFactory`, `JobFactory`, `RawJobPayloadFactory`
- 4 tests in `apps/ingestion/tests/test_ingestion.py` — all passing
- Covers: model creation, content hash stability, mocked HTTP parsing, dedup on double ingest
