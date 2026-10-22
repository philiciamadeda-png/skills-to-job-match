# Skills to Job Match

A Django application that ingests remote job listings from public APIs (Remotive, Arbeitnow), deduplicates them, normalises company names and locations, resolves skills against a canonical vocabulary, runs LLM-based skill extraction, and stores structured records for job matching.

## How it works

Raw job data flows through three stages:

1. **Ingestion** — fetches listings from external APIs and stores them as `RawJobPayload` rows (untouched JSON with a content hash for deduplication).
2. **Transform** — reads unprocessed payloads in batches, normalises fields, resolves skills, and writes structured `Job`, `Company`, and `Location` records.
3. **Extraction** — runs LLM-based extraction across all unextracted jobs, resolves skills against the canonical vocabulary, and writes `JobSkill` records. Resumable after a crash — only jobs with `extraction_status=pending` are processed.

All three stages run as Celery tasks, with Redis locks preventing overlapping runs and run-log models (`IngestionRun`, `ExtractionRun`) recording every execution.

## Tech stack

- Python 3.12+, Django 6.x
- PostgreSQL 16
- Redis 7 — Celery broker, result backend, and distributed lock store
- Celery 5 + Celery Beat
- Pydantic — LLM output schema validation
- `django-environ`, `requests`
- `pytest` + `factory-boy` for tests

## Project structure

```
apps/
  core/           # Abstract base model (TimestampedModel)
  ingestion/      # RawJobPayload, IngestionRun, source classes, ingest service, Celery tasks
  intelligence/   # Company, Location, Skill, Job, JobSkill, ExtractionRun models
                  # transform service, LLM extraction task, utils
    llm/
      client.py   # LLMClient — network retries, structured output with one self-correction retry
    prompts/      # Versioned extraction prompt templates (v1, v2, v3 …)
    schemas.py    # Pydantic schema: JobExtractionResult
    eval/
      run_eval.py          # Standalone eval script
      results/             # Timestamped JSON result files per prompt version
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
pip install django django-environ psycopg2-binary requests celery redis pydantic pytest pytest-django factory-boy
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
| `OPENAI_API_KEY`    | Optional — leave unset to use local Ollama instead                |
| `LLM_BASE_URL`      | LLM endpoint, default `http://localhost:11434/v1` (Ollama)        |

### 4. Start PostgreSQL and Redis

```bash
docker compose up -d
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

## Running LLM extraction

```bash
# Sample run — 50 jobs, no LLM calls, just counts
python manage.py shell -c "
from apps.intelligence.tasks import task_extract_jobs
print(task_extract_jobs.apply(kwargs={'limit': 50, 'dry_run': True}).get())
"

# Sample run — 50 jobs with real LLM calls (estimate cost before full run)
python manage.py shell -c "
from apps.intelligence.tasks import task_extract_jobs
print(task_extract_jobs.apply(kwargs={'limit': 50}).get())
"

# Check the run record
python manage.py shell -c "
from apps.intelligence.models import ExtractionRun
r = ExtractionRun.objects.latest('started_at')
print(r.status, r.succeeded, r.failed, r.cost_usd, r.duration)
"

# Full run via Celery worker
task_extract_jobs.delay()
```

The task is resumable — re-running it only processes jobs still in `pending` state.

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

Beat dispatches `task_ingest_jobs` every 2 hours, `task_transform_jobs` 30 minutes later, with run records appearing at `/admin/ingestion/ingestionrun/` and `/admin/intelligence/extractionrun/`.

## Maintaining the skill vocabulary

Every extraction run will create new `Skill` rows flagged `is_auto_created=True` for strings that had no match in the canonical vocabulary or alias table. Some are genuinely new skills; most are variants that should be aliased. Vocabulary quality directly affects match quality — this is an ongoing maintenance job.

### 1. Run the report after each extraction batch

```bash
python manage.py report_new_skills           # top 50 by job frequency
python manage.py report_new_skills --limit 100 --min-jobs 2
```

Read the output. For each entry decide:

| Case | Action |
|------|--------|
| Variant of an existing skill (`"Postgres 15"` → PostgreSQL) | `add_skill_alias` |
| Noise / not a real skill (`"Communication"`) | `add_skill_alias --delete` |
| Genuinely new canonical skill | Add to `fixtures/skills_seed.py`, re-run `seed_skills` |

### 2. Alias a variant

```bash
python manage.py add_skill_alias "Postgres 15" --canonical "PostgreSQL"
python manage.py add_skill_alias "ReactJS" --canonical "React"
```

This creates the alias **and** re-points any existing `JobSkill` rows that landed on the auto-created skill, so historical extractions are corrected immediately.

### 3. Delete noise

```bash
python manage.py add_skill_alias "Communication" --delete
```

### 4. Add a new canonical skill

Edit `apps/intelligence/fixtures/skills_seed.py` and re-run:

```bash
python manage.py seed_skills
```

`seed_skills` is idempotent — safe to run multiple times.

## Evaluating prompt quality

The eval set lives at `apps/intelligence/fixtures/eval_set.json` (20 hand-labelled jobs).

```bash
# Score a prompt version
python manage.py score_prompt --prompt-version v1
python manage.py score_prompt --prompt-version v2

# Or run the script directly
DJANGO_SETTINGS_MODULE=config.settings.local PYTHONPATH=. \
  python apps/intelligence/eval/run_eval.py \
  --prompt=apps/intelligence/prompts/extract_job_details_v2.md
```

Results are written to `apps/intelligence/eval/results/<timestamp>_<prompt_version>.json`.

Headline metric: **skill recall** (missing a required skill is more damaging than a false positive for job matching). Report all metrics; sort prompt versions by recall.

Full iteration log — hypotheses, failure analysis, and what to try next — in [`docs/prompt-iteration.md`](docs/prompt-iteration.md).

### Prompt versions

| Version | skill_recall | false_positives | seniority_acc | contract_acc | remote_acc |
|---------|-------------|-----------------|---------------|--------------|------------|
| v1      | 0.200       | 40              | 0.526         | 0.474        | 0.579      |
| v2      | 0.400       | 60              | 0.421         | 0.316        | 0.368      |
| v3      | 0.178       | 17              | 0.526         | 0.579        | 0.474      |

## Running the tests

```bash
pytest
pytest --cov=apps --cov-report=term-missing   # with coverage
```

All tests use a temporary test database and make no real network calls.
