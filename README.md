# Skills to Job Match

A Django application that ingests remote job listings from public APIs (Remotive, Arbeitnow), deduplicates them, normalises company names and locations, resolves skills against a canonical vocabulary, and stores structured records for later LLM-based skill extraction and job matching.

## How it works

Raw job data flows through two stages:

1. **Ingestion** — fetches listings from external APIs and stores them as `RawJobPayload` rows (untouched JSON with a content hash for deduplication).
2. **Transform** — reads unprocessed payloads in batches, normalises fields, resolves skills, and writes structured `Job`, `Company`, and `Location` records.

Both stages run as Celery tasks on a schedule, with Redis locks preventing overlapping runs and `IngestionRun` records logging every execution.

## Tech stack

- Python 3.12+, Django 6.x
- PostgreSQL 16
- Redis 7 — Celery broker, result backend, and distributed lock store
- Celery 5 + Celery Beat
- `django-environ`, `requests`
- `pytest` + `factory-boy` for tests

## Project structure

```
apps/
  core/           # Abstract base model (TimestampedModel)
  ingestion/      # RawJobPayload, IngestionRun, source classes, ingest service, Celery tasks
  intelligence/   # Company, Location, Skill, Job, JobSkill models; transform service; utils
  accounts/       # Placeholder
  analytics/      # Placeholder
config/
  celery.py
  settings/
    base.py
    local.py
    production.py
conftest.py
pytest.ini
docker-compose.yml
```

## Prerequisites

- Python 3.12 or newer
- Docker and Docker Compose (for PostgreSQL and Redis)
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

Open `.env` and set your values:

| Variable            | Description                                                        |
|---------------------|--------------------------------------------------------------------|
| `SECRET_KEY`        | Any long random string                                             |
| `ALLOWED_HOSTS`     | Comma-separated hostnames, e.g. `localhost,127.0.0.1`             |
| `DATABASE_URL`      | e.g. `postgres://skills_user:changeme@localhost:5432/skills_db`   |
| `POSTGRES_DB`       | Database name, e.g. `skills_db`                                   |
| `POSTGRES_USER`     | Database user, e.g. `skills_user`                                 |
| `POSTGRES_PASSWORD` | Database password                                                  |
| `REDIS_URL`         | e.g. `redis://localhost:6379/0` (this is the default if unset)    |

### 4. Start PostgreSQL and Redis

```bash
docker compose up -d
```

Verify both containers are running:

```bash
docker compose ps
```

### 5. Run migrations

```bash
python manage.py migrate
```

### 6. Seed the skill vocabulary

```bash
python manage.py seed_skills
```

Loads 29 canonical skills and 73 aliases. Safe to run multiple times.

### 7. Create a superuser (optional)

```bash
python manage.py createsuperuser
```

Then visit `http://127.0.0.1:8000/admin` after starting the dev server.

## Running the ingestion command manually

```bash
python manage.py ingest_jobs --source remotive
python manage.py ingest_jobs --source arbeitnow --limit 300
```

Running either command a second time is safe — duplicates are skipped automatically.

## Running the scheduled pipeline

Open three terminals (all with the virtualenv activated):

```bash
# Terminal 1 — Celery worker
celery -A config worker -l info

# Terminal 2 — Celery Beat scheduler
celery -A config beat -l info

# Terminal 3 — Django dev server (optional, for admin)
python manage.py runserver
```

When everything is working you should see Beat dispatching `task_ingest_jobs` every 2 hours and `task_transform_jobs` 30 minutes later, with the worker logging successful task completions and `IngestionRun` rows appearing at `/admin/ingestion/ingestionrun/`.

## Running the tests

```bash
pytest
pytest --cov=apps --cov-report=term-missing   # with coverage
```

All tests use a temporary test database and make no real network calls.
