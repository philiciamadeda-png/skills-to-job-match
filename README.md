# Skills to Job Match

A Django application that ingests remote job listings from public APIs (Remotive, Arbeitnow), deduplicates them, normalises company names and locations, resolves skills against a canonical vocabulary, runs LLM-based skill extraction, and matches uploaded CVs against the jobs with an explainable composite score.

Design decisions for the matching feature — what gets embedded, the scoring weights, hard filters, evaluation, and personal data — are in [`docs/matching-design.md`](docs/matching-design.md).

## How it works

Raw job data flows through three stages:

1. **Ingestion** — fetches listings from external APIs and stores them as `RawJobPayload` rows (untouched JSON with a content hash for deduplication).
2. **Transform** — reads unprocessed payloads in batches, normalises fields, resolves skills, and writes structured `Job`, `Company`, and `Location` records.
3. **Extraction** — runs LLM-based extraction across all unextracted jobs, resolves skills against the canonical vocabulary, and writes `JobSkill` records. Resumable after a crash — only jobs with `extraction_status=pending` are processed.

All three stages run as Celery tasks, with Redis locks preventing overlapping runs and run-log models (`IngestionRun`, `ExtractionRun`) recording every execution.

Matching then works on top of the structured jobs:

4. **Embedding** — each job is embedded from `title | seniority | skills | snippet` into pgvector. Batched, resumable, and only re-embedded when its text or the model changes.
5. **CV profile** — an uploaded PDF or DOCX is read to text, the LLM extracts skills, seniority and years of experience, skills are resolved through the same `resolve_skill()` as jobs, and the profile is embedded the same way as jobs.
6. **Matching** — hard filters run in the database, then each remaining job gets a weighted score from required skills, seniority fit, similarity, nice-to-have skills and recency. Every component is kept so the result can be explained.
7. **Explanation and page** — a short plain-English explanation is generated from the computed facts when a user opens a match. A plain upload → matches → match page ties it together.

## Tech stack

- Python 3.12+, Django 6.x
- PostgreSQL 16 + pgvector (HNSW index, cosine distance)
- Ollama — `llama3.2` for extraction and explanations, `nomic-embed-text` for embeddings
- `pdfplumber`, `python-docx` — CV text extraction
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
  intelligence/   # Company, Location, Skill, Job, JobSkill, ExtractionRun, EmbeddingRun models
                  # transform service, LLM extraction + embedding tasks, utils
    llm/
      client.py   # LLMClient — network retries, structured output with one self-correction retry
    prompts/      # Versioned prompt templates — job extraction (v1–v3), CV extraction, match explanation
    schemas.py    # Pydantic schemas: JobExtractionResult, CVExtractionResult
    matching.py   # Hard filters + composite score, MatchResult with per-component breakdown
    explain.py    # Facts-only match explanation with output checks and template fallback
    eval/
      run_eval.py                       # Standalone eval script
      compare_embedding_strategies.py   # Embedding strategy harness
      results/                          # Timestamped JSON result files per prompt version
  accounts/       # CV and CVProfile models, CV text extraction, profile service,
                  # upload → matches → match pages (views, forms, templates)
  analytics/      # Placeholder
docs/
  matching-design.md       # Design note for the matching feature
  matching-evaluation.md   # Hand-judged results, fixes, remaining failures
  model-card-seniority.md
  prompt-iteration.md
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
- Podman (or Docker) with Compose support — for PostgreSQL+pgvector and Redis
- Ollama with `llama3.2` and `nomic-embed-text` pulled
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
pip install -r requirements.txt
```

Django 6.1 requires Python 3.12+ — a 3.11 virtualenv will fail to install it.

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

### LLM vs trained model vs keyword rule — head-to-head on hand-labelled eval set

Measured on 18 of 20 eval jobs that carry a mappable seniority label (2 are `not stated`).
Fine-grained labels (`mid`, `principal`, `director`) merged to 3-class before scoring.

| | LLM (best prompt v1/v3) | Trained model (v1) | Keyword rule |
|---|---|---|---|
| Accuracy vs hand labels | 0.526 | 0.50 | **0.72** |
| Cost per 1,000 jobs | ~$0.50–2.00 (model-dependent) | ~$0 | $0 |
| Time per 1,000 jobs | ~30–60 min (rate-limited) | ~37s | <1s |
| Needs network | Yes | No | No |
| Handles unseen title | Yes (reasoning) | Degrades gracefully | Misses if no keyword |

**What the numbers say:**

The keyword rule wins on seniority accuracy (0.72) against this eval set. The trained model (0.50) underperforms the keyword rule on non-English titles — French and German jobs make up ~40% of the eval set and the model was trained on a corpus dominated by English. The LLM (0.526) is only marginally better than the model and costs orders of magnitude more.

**Production decision:**

Use the **keyword rule for seniority** and the **LLM for skill extraction only**.

Seniority is largely a title-level signal. The keyword rule is transparent, free, instant, and outperforms both the model and the LLM on this eval set. The trained model adds value only for titles with no explicit keyword — a minority of listings — and its accuracy on non-English titles is poor enough to make it unreliable for a multilingual dataset.

The LLM's genuine advantage is skill extraction: it reads the full description and identifies skills the vocabulary would miss. That task has no cheap alternative. Reserving LLM calls for skill extraction and using the keyword rule for seniority cuts LLM cost by roughly the fraction of the prompt devoted to seniority classification — while improving seniority accuracy.

What was traded away: the model's ability to infer seniority from description context (e.g. "5+ years required" in a title-less listing). For those edge cases, the keyword rule returns `senior` as a default, which is the majority class and a reasonable fallback.

## Week 4 — Seniority classifier

### Seniority labels

All 611 jobs carry a 3-class seniority label (`junior`, `senior`, `senior_plus`).
Labels come from two sources, applied in order:

1. `backfill_seniority` — regex on job title (rule-based, fast, transparent)
2. `backfill_seniority_ml` — TF-IDF + Logistic Regression model on `not_stated` remainder

Raw fine-grained labels (`mid`, `intern`, `lead`, `principal`, `manager`) are merged into the 3-class scheme at backfill time.

```bash
python manage.py backfill_seniority       # rule-based pass
python manage.py backfill_seniority_ml    # ML pass on not_stated jobs
```

### Train/test split

Groups near-duplicate listings by `(normalised_title, company)` so they always land on the same side. Stratified on group-level majority label.

```python
from apps.intelligence.ml_split import make_split, check_leakage
X_train, X_test, y_train, y_test = make_split(df)
check_leakage(df, X_train, X_test)  # asserts zero leakage
```

Split: 491 train / 120 test. Class proportions held to within ~1%.

### Baselines (test set, n=120)

| Model | Accuracy | Macro F1 | junior F1 | senior F1 | senior_plus F1 |
|---|---|---|---|---|---|
| Majority class | 0.40 | 0.19 | 0.00 | 0.00 | 0.57 |
| Keyword rule (title) | 0.52 | 0.41 | 0.06 | 0.60 | 0.56 |

The keyword rule is the meaningful baseline to beat — macro F1 **0.41**.

### Four-way comparison (test set n=120)

| Combo | CV macro-F1 | Test acc | Test macro | junior F1 | senior F1 | senior_plus F1 |
|---|---|---|---|---|---|---|
| title-only / unbalanced | 0.754 ± 0.042 | 0.708 | 0.694 | 0.654 | 0.658 | 0.771 |
| title-only / balanced   | 0.764 ± 0.045 | 0.725 | 0.723 | 0.746 | 0.658 | 0.765 |
| title+desc / unbalanced | 0.759 ± 0.054 | 0.800 | 0.803 | 0.862 | 0.744 | 0.804 |
| title+desc / balanced   | 0.768 ± 0.054 | 0.783 | 0.787 | 0.848 | 0.725 | 0.787 |

Winner: **title+desc / unbalanced** — test macro F1 0.803, well above keyword baseline of 0.41.

### Trained model

TF-IDF (10k features, bigrams, sublinear_tf) + Logistic Regression (class_weight=unbalanced).

CV macro-F1: **0.759 ± 0.054**

Artifacts live in `ml/artifacts/`. The live version is recorded in `ml/artifacts/live.txt`.
Each artifact has a sidecar JSON with metrics, sklearn version, git commit, and training date.

Full model card (metrics, weaknesses, label provenance): [`docs/model-card-seniority.md`](docs/model-card-seniority.md)

### Training

```bash
# Train and save a new versioned artifact (sets it as live automatically)
python apps/intelligence/save_artifact.py --version v2
```

### Running predictions

```python
# Single prediction
from apps.intelligence.ml_service import predict_seniority
label = predict_seniority(title, description)

# Batch — returns label, confidence, and model version per item
from apps.intelligence.ml_service import predict_batch
results = predict_batch(["Senior Python Engineer 5yr exp", ...])
# [{'label': 'senior', 'confidence': 0.75, 'model_version': 'v1'}, ...]
```

### Batch prediction task

```bash
# Predict seniority for all jobs missing a model-based prediction
python manage.py shell -c "
from apps.intelligence.tasks import task_predict_seniority
print(task_predict_seniority.apply().get())
"
```

Each job stores `seniority`, `seniority_confidence`, and `seniority_model_version`.
The task is idempotent — re-running skips jobs that already have a `seniority_model_version`.

### Head-to-head comparison

```bash
python manage.py compare_approaches --eval-set apps/intelligence/fixtures/eval_set.json
```

### Notebooks

| Path | Purpose |
|---|---|
| `ml/notebooks/01_explore.ipynb` | EDA + full train/eval/save workflow |
| `notebooks/eda_seniority.ipynb` | Class distribution, length, source cross-tab |
| `notebooks/train_seniority_classifier.ipynb` | Step-by-step training walkthrough |

### Tests

`apps/intelligence/tests/test_ml.py` covers:
- `make_split` — no near-duplicate pair straddles the split, all rows accounted for
- `check_leakage` — passes on a clean split
- `predict_seniority` / `predict_batch` — valid labels, never raises, batch and single agree
- artifact — correct output shape and class labels
- registry — pipeline loaded exactly once across multiple calls
- version — every prediction result carries a non-empty `model_version`
- no `fit()` calls anywhere in `apps/` outside `save_artifact.py`

## Running the tests

```bash
pytest
pytest --cov=apps --cov-report=term-missing   # with coverage
```

All tests use a temporary test database and make no real network calls. The test database needs the `pgvector` extension, so run them against the project's Docker Postgres (port 5433 in `.env.example`), not a plain system Postgres.

Current suite: **136 tests, all passing** (`pytest -v`, Python 3.12, PostgreSQL + pgvector 0.6).

## Week 5 — Vector search (CV-to-job matching)

### pgvector setup

The project now uses `pgvector/pgvector:pg16` instead of plain `postgres:16`.
The container runs on **port 5433** to avoid conflicts with any native Postgres on the host.
Update your `.env`:

```
DATABASE_URL=postgres://skills_user:<password>@localhost:5433/skills_db
```

Start the container (Podman, host-network mode):

```bash
podman run -d --name skills_pgvector --network=host \
  -e POSTGRES_DB=skills_db \
  -e POSTGRES_USER=skills_user \
  -e POSTGRES_PASSWORD=<password> \
  -e PGPORT=5433 \
  -v pgvector_data:/var/lib/postgresql/data \
  docker.io/pgvector/pgvector:pg16 postgres -p 5433
```

Or with podman-compose (after `pip install podman-compose`):

```bash
podman-compose up -d
```

### Migration 0008 — what it does

`apps/intelligence/migrations/0008_pgvector_job_embedding.py`:

1. `CREATE EXTENSION IF NOT EXISTS vector` — enables pgvector in the DB (idempotent).
2. Drops the old `JSONField` placeholder and adds a real `VectorField(dimensions=768)` — sized for `nomic-embed-text` (local Ollama). Change to 1536 for `text-embedding-3-small`.
3. Adds `embedding_model` (CharField) — records which model produced each embedding so rows can be invalidated when the model changes.
4. Creates an **HNSW** index with `vector_cosine_ops`.

### Index choice — HNSW vs IVFFlat

| | HNSW | IVFFlat |
|---|---|---|
| Query speed | Faster (graph traversal, no training) | Slightly slower |
| Build time | Slower, more memory during build | Fast, low memory |
| Needs training step | No | Yes (`lists` must be set before inserting data) |
| Recall | Higher by default | Tunable via `probes` |
| Best for | Dataset that grows incrementally | Large static datasets |

**Decision: HNSW.** At a few thousand jobs growing slowly, HNSW is the right choice — no training step, better recall out of the box, and new rows are indexed immediately on insert.

Parameters used: `m=16, ef_construction=64` — sensible defaults for this scale. Raise `ef_construction` (e.g. 128) if recall needs improving later.

### Distance metric — cosine vs inner product

| | Cosine (`vector_cosine_ops`) | Inner product (`vector_ip_ops`) |
|---|---|---|
| Normalisation required | No | Yes (vectors must be unit-length) |
| Meaning | Angle between vectors — ignores magnitude | Dot product — magnitude matters |
| Use case | General-purpose similarity | Slightly faster when vectors are pre-normalised |

**Decision: cosine distance.** Embedding models (OpenAI, sentence-transformers) do not guarantee unit-length output. Cosine is robust to that and is the standard choice for semantic similarity. Switch to inner product only if you pre-normalise every vector and need the marginal speed gain.

### Changing embedding model later

When you switch models (e.g. `text-embedding-3-small` → `text-embedding-3-large`, or to a local model):

- The new vectors live in a different geometric space — **old and new embeddings are not comparable**.
- The HNSW index becomes invalid for mixed-model rows.
- Query results will be silently wrong if you mix models.

**What `embedding_model` buys you:**

```python
# Invalidate only the rows from the old model — re-embed in batches
Job.objects.filter(embedding_model='text-embedding-3-small').update(embedding=None, embedding_model='')
```

- You can re-embed incrementally without touching rows already on the new model.
- You can filter queries to only rows with a specific model version while migration is in progress.
- After full re-embedding, `REINDEX INDEX CONCURRENTLY job_embedding_hnsw` rebuilds the index without downtime.

**Also store now:** the embedding dimensions (1536 here, baked into the field). If you move to a different-dimension model you will need a new `VectorField` with the new dimension and a new index — plan for that as a separate migration.

### Embedding task

`task_embed_jobs` generates and stores embeddings for every job that doesn't yet have a current one.

```bash
# Embed all jobs with extracted skills
python manage.py shell -c "
from apps.intelligence.tasks import task_embed_jobs
print(task_embed_jobs.apply().get())
"

# Check the run record
python manage.py shell -c "
from apps.intelligence.models import EmbeddingRun
r = EmbeddingRun.objects.latest('started_at')
print(r.status, r.model, r.succeeded, r.failed, r.duration)
"
```

**"Already current" means all three conditions hold:**
1. `embedding` is not null
2. `embedding_model` matches the configured model
3. `embedding_hash` matches `SHA-256(embed_text())` — the hash of the exact text fed to the embedder

Only the third condition catches content changes. The hash is computed from `embed_text()` (title + seniority + skills + first 400 chars of description). Unrelated field changes — salary, contract type, source metadata — do not affect `embed_text()` and therefore do not trigger a re-embed. The task is fully resumable: a crash mid-batch leaves already-written rows untouched; the next run picks up from the first job whose hash is still stale.

### Embedding strategy comparison

Three strategies were tested for what text represents a job:

| Strategy | What it feeds to the embedder | Risk |
|---|---|---|
| `full_description` | Raw job description | Boilerplate (benefits, EEO statements) dominates — unrelated jobs match on culture text |
| `skills_only` | Comma-joined canonical skill names | Loses context — "Python" matches everything; sparse skills hurt recall |
| `title_skills` | `{title} \| {seniority} \| skills: {skills} \| {first 400 chars}` | Best signal-to-noise — requirements with enough context to disambiguate |

**Decision: `title_skills`** — confirmed by running the harness below.

The `full_description` failure mode is visible in the output: a generic agency listing (Lemon.io) scores 0.529 on a "Python data engineer" query because its description contains paragraphs about remote work culture that match the query's context words, not its technical requirements.

### Running the comparison harness

```bash
DJANGO_SETTINGS_MODULE=config.settings.local PYTHONPATH=. \
  python apps/intelligence/eval/compare_embedding_strategies.py \
  --query "Python data engineer with Spark and AWS" \
  --n 10 --top 5
```

The script embeds N jobs under all three strategies using `nomic-embed-text` (local Ollama), runs cosine similarity against the query, and prints ranked results side-by-side with the exact text fed to the embedder.

## CV upload and text extraction

### What was built

- `apps/accounts/models.py` — `CV` model: file field, extracted text, status (`pending/ready/failed`), `delete_file()` helper
- `apps/accounts/extraction.py` — extraction service: magic byte detection, PDF + DOCX support, scanned PDF detection
- `apps/accounts/forms.py` — `CVUploadForm`: size limit + magic byte validation (not extension-based)

### Libraries chosen

| Library | Used for | What it's bad at |
|---|---|---|
| `pdfplumber` | PDF text extraction | Scanned/image PDFs (returns empty string — no OCR); complex multi-column layouts can scramble word order |
| `python-docx` | DOCX text extraction | Only reads `.docx` (not `.doc`); ignores text in headers, footers, and text boxes |

`python-magic` (libmagic bindings) was the first choice for MIME detection but requires the `libmagic` system library which wasn't available. Magic bytes are checked directly instead — covers all cases needed here.

### File type validation

Validated by reading the first 4 bytes of the file content, not by extension or `Content-Type` header. Both are trivially spoofable. A `.exe` with a `%PDF` header passes; a `.pdf` with a PNG header is rejected.

### Scanned PDF detection

After extraction, if `len(text.strip()) < 50` the result is flagged `is_scanned=True` with a clear message. This catches image-based PDFs that pdfplumber opens successfully but returns no text from.

### Privacy

- `CV.__str__` never includes filename or text content — safe in logs and admin
- `logger.exception` in the extraction service logs the exception class only, never file contents
- `CV.delete_file()` removes the stored file once text has been processed — call it after a successful extraction

### Usage

```python
from apps.accounts.extraction import extract_text
from apps.accounts.models import CV

# In a view, after form.is_valid():
result = extract_text(form.cleaned_data['file'])
if not result.ok:
    # show result.error to the user
    ...
else:
    cv = CV.objects.create(owner=request.user, extracted_text=result.text, status='ready', ...)
    cv.delete_file()  # remove the file once text is stored
```

## Week 5 — CV profile extraction (Task 5)

### What was built

- `apps/intelligence/schemas.py` — `CVExtractionResult` schema (skills, seniority, years_experience)
- `apps/intelligence/prompts/extract_cv_v2.md` — CV extraction prompt (v1 kept for comparison)
- `apps/accounts/models.py` — `CVProfile` model: resolved skills (M2M to canonical `Skill`), seniority, years_experience, embedding
- `apps/accounts/cv_extraction.py` — `extract_cv_profile()` service
- `apps/accounts/services.py` — `build_profile(cv_id)` public entry point (loads the CV, runs extraction, returns the `CVProfile`; raises `ProfileBuildError` on failure)
- `Skill.canonical_name` — read-only property returning the canonical skill name (no migration)
- `apps/accounts/tests/test_cv_extraction.py` — tests for the above

### How it reuses existing machinery

Nothing new was written for the LLM call, retries, or validation — `LLMClient` and `extract_structured()` are reused directly. `resolve_skill()` is called for every skill the LLM returns, exactly as the job extraction pipeline does. The embedding call reuses `_embed_batch()` and `EMBED_MODEL` from `apps/intelligence/tasks.py`, so CVs and jobs are always embedded by the same model and endpoint — changing the model in one place changes it for both. The only genuinely new code is the CV prompt and `CVExtractionResult` schema.

Cost: `LLMClient` holds the cost table, but `extract_structured()` does not return token counts, so per-CV cost is not recorded yet. This is the same known gap as job extraction (see `_extract_one()` in `tasks.py`); with the local Ollama model the cost is 0.

### Invented skills are dropped

With v1 of the prompt, llama3.2 added "Agile" and "Scrum" to every tech CV in the evaluation set, although none of them mention either. The words came from the prompt's own example ("domain-specific (e.g. "Agile", "Scrum")"). Common skills like these inflate required-skill coverage for every tech job. Two fixes:

- **Prompt v2** has no skill names in its rules, and says each skill must appear word for word in the CV.
- **`skills_in_text()`** drops any returned skill that doesn't appear as a whole word or phrase in the CV text the model was shown (case- and whitespace-insensitive), and logs what it dropped. The prompt asks; the code enforces.

Re-run on the 4 evaluation CVs: Agile/Scrum gone from all of them, every real skill kept, and one more invented name caught ("Postgres" on CVs that only say "PostgreSQL"). Trade-off: a skill the model rewords (e.g. "Postgres" for a CV that says "PostgreSQL") is dropped rather than kept. That's safe here because the model also returns the wording that is in the text, and the warning in the log shows anything dropped.

**The same bug in job extraction.** Loading 250 real jobs for the Task 7 evaluation showed 13 unrelated jobs (a Senior Product Manager, an Intelligence Officer, a Director of Enterprise Planning…) all requiring exactly Python, Django and PostgreSQL with Redis as a bonus, which is the worked example in `extract_job_details.md`. None of those adverts mention Django, PostgreSQL or Redis, and they filled most of the top 10 for three of the four evaluation CVs. `skills_in_text()` now lives in `apps/intelligence/services.py` next to `resolve_skill()`, and `_extract_one()` applies it to the description the model saw. Checking the 246 already-extracted jobs found invented skills on 90 of them (227 links, led by PostgreSQL ×24, Redis ×24, Python ×15, Django ×15). Those links were removed and the jobs re-embedded.

### Seniority vocabulary

CV seniority uses the same `Seniority` enum as jobs (`junior`, `mid`, `senior`, `principal`, `director`, `not_stated`) and is stored the same way (`result.seniority.value`), so the matcher compares like with like. `years_experience` is capped at 50; `not_stated` is stored as `NULL`.

### Why resolve_skill() matters here

If a CV says "Postgres" and a job says "PostgreSQL" and both go through `resolve_skill()`, they resolve to the same canonical `Skill` record and the match works. Without this step, the skill overlap calculation silently returns zero for any variant spelling.

### Embedding strategy — same as jobs

`CVProfile.embed_text()` mirrors `Job.embed_text()` exactly:

```
CV | {seniority} | skills: {skill1}, {skill2}, ... | {first 400 chars of CV text}
```

Both sides must be constructed the same way. Embedding jobs as "title + skills + requirements" and CVs as raw document text puts them in different parts of the vector space — similarity scores become meaningless. The only difference is the first segment: jobs use their title, CVs use the literal `CV` (a CV has no single title).

### Tests

`apps/accounts/tests/test_cv_extraction.py` (LLM and embedder are mocked — no network calls):
- CV "Postgres" and job "PostgreSQL" resolve to the same canonical `Skill`
- seniority and years stored in the job vocabulary; `not_stated` years → `NULL`
- embedding goes through the shared `_embed_batch()` and records `EMBED_MODEL`
- CV and job `embed_text()` have the same four-part structure
- LLM failure or empty CV text returns `False` without raising
- embedding failure is non-fatal — skills and seniority are still saved
- `build_profile(cv_id)` returns the profile with canonical skill names, and raises `ProfileBuildError` on failure

```bash
pytest apps/accounts/tests/test_cv_extraction.py -v
```

### Usage / verification

Requires PostgreSQL (`docker compose up -d`), Ollama running with `llama3.2` and `nomic-embed-text`, and `python manage.py seed_skills`.

```python
python manage.py shell
>>> from apps.accounts.services import build_profile
>>> p = build_profile(cv_id)
>>> print([s.canonical_name for s in p.skills.all()], p.seniority, p.years_experience)
>>> print(len(p.embedding or []), p.embedding_model)   # expect: 768 nomic-embed-text
```

Expected: variant spellings come back canonical (a CV saying "Postgres" lists `PostgreSQL`), seniority is one of the job values, and years is an integer or `None`. `build_profile()` raises `ProfileBuildError` if the CV has no text or the LLM fails; an embedding failure is non-fatal (`p.embedding` is `None` but skills are saved).

Lower-level call, if you already have the CV object:

```python
from apps.accounts.cv_extraction import extract_cv_profile
ok = extract_cv_profile(cv)   # True/False; cv.profile is created/updated
```

## Week 5 — Matching algorithm (Task 6)

Code: `apps/intelligence/matching.py`. Design prompt (proposal sent for critique): [`task6_prompt.md`](task6_prompt.md).

Vector similarity alone is not used — nearest-neighbour search has no notion of a missing required skill or a wrong seniority level. Instead: hard filters first, then a weighted composite score.

### Scoring components

| Component | Proposed weight | Current weight | What it measures |
|---|---|---|---|
| `required_skill_score` | 0.40 | 0.40 | Matched required skills ÷ job's required skills (0.5 if the job lists none) |
| `seniority_score` | 0.20 | **0.30** | Level fit — penalises gap in both directions |
| `semantic_score` | 0.25 | **0.15** | Cosine similarity of profile and job embeddings, floored at 0 |
| `nice_to_have_score` | 0.10 | 0.10 | Matched nice-to-have ÷ job's nice-to-have skills (0 if none) |
| `recency_score` | 0.05 | 0.05 | `exp(−age_days / 30)` from `published_date`; 0 after 180 days, 0.5 if no date |

The weights were tuned from the proposal after the matching evaluation (see below): semantic similarity was over-rewarding boilerplate-heavy descriptions, and a 2-level seniority gap was being masked.

Seniority penalises in both directions — `score = 1 − 0.4 × |gap|`, so a gap of 1 level gives 0.6, 2 gives 0.2, ≥ 3 gives 0. A graduate shown a principal role and a senior shown an internship both score low. If either side is `not_stated` the score is a neutral 0.5.

**Required vs nice-to-have.** `JobSkill.is_required` (migration `0010`) records which list the LLM put each skill in; a skill in both lists is stored as required. Rows extracted before this migration default to `is_required=True`, so they behave as before (all skills required, nice-to-have score 0) until re-extracted:

```bash
python manage.py migrate
# Re-extract to populate the split (re-runs the LLM on every successful job)
python manage.py shell -c "
from apps.intelligence.models import Job
from apps.intelligence.tasks import task_extract_jobs
Job.objects.filter(extraction_status='success').update(extraction_status='pending')
print(task_extract_jobs.apply().get())
"
```

Re-extraction may change `seniority` and skills on some jobs, which changes their `embed_text()`; run `task_embed_jobs` afterwards — it only re-embeds jobs whose text hash changed.

### Hard filters

Applied in the database before scoring — these are requirements, not preferences (`candidate_jobs()`):

| Filter | Rule |
|---|---|
| processed | `extraction_status = 'success'` and `embedding IS NOT NULL` |
| not a duplicate | `canonical IS NULL` |
| enough skills | at least `MIN_JOB_SKILLS = 3` extracted skills |
| `remote_only=True` | excludes `on_site` and `hybrid`; keeps `remote` and unstated |
| `countries=['KE', ...]` | job location country must be in the list; jobs with no stated country (worldwide) are kept |

Filtering, skill counting and skill loading all happen in one query plus one prefetch — there is no per-job database query.

### Explainability

Each `MatchResult` keeps every component separately:

- `required_skill_score`, `semantic_score`, `seniority_score`, `nice_to_have_score`, `recency_score` — raw 0–1 scores
- `components` — the same as a dict; `contributions` — each weighted, summing to `total_score`
- `matched_required`, `missing_required`, `matched_nice` — skill names
- `seniority_gap` — signed, positive = overqualified

Ties are broken by job id, so the same inputs always give the same order.

### Usage

```python
from apps.intelligence.matching import match_profile

results = match_profile(profile, remote_only=True, countries=['KE'], limit=20)
for r in results:
    print(r.total_score, r.job.title)
    print('  contributions:', r.contributions)
    print('  matched:', r.matched_required, ' missing:', r.missing_required, ' bonus:', r.matched_nice)
    print('  seniority_gap:', r.seniority_gap)
```

```bash
python manage.py match --cv 1 --top 10 --explain --remote-only --countries KE,GB
```

### Tuning weights

Weights can be overridden per run without editing code, from the command line (`--weight NAME=VALUE`, repeatable) or in Python (`match_profile(profile, weights={...})`). Names: `required_skill`, `semantic`, `seniority`, `nice_to_have`, `recency`. Weights are rescaled to sum to 1 so `total_score` stays 0–1 — raising one weight lowers the others proportionally. The command prints the effective weights at the top of every run, and each `MatchResult.weights` records the weights used, so `contributions` always sums to `total_score`.

Before/after check on your own CV:

```bash
python manage.py match --cv <id> --top 10 --explain                          # before (default weights)
python manage.py match --cv <id> --top 10 --explain --weight seniority=0.5   # after: one weight adjusted
```

What to compare: which jobs entered or left the top ten, whether jobs with a large `gap` moved down (when raising `seniority`) or jobs with many `missing` skills moved down (when raising `required_skill`), and that the raw component scores (`req`, `sem`, `sen`, …) are identical between runs — only the totals and order should change. If they're not identical, the change isn't coming from the weights. Once a change is confirmed as an improvement, make it permanent by editing the `W_*` constants in `matching.py` and record it in `docs/matching-evaluation.md`.

### Tests

`apps/intelligence/tests/test_matching.py` and `apps/intelligence/tests/test_extraction.py`:
- seniority penalised both ways (junior→principal, senior→junior) and full score on exact match
- `remote_only` excludes `on_site` and `hybrid`; `countries` excludes other countries but keeps unstated
- duplicates and jobs with fewer than 3 skills are excluded
- nice-to-have skills are scored separately from required skills
- component contributions sum to the total; scoring is deterministic
- extraction stores `is_required` correctly, including a skill listed in both lists
- weight overrides are validated and rescaled; changing a weight changes totals but not raw component scores

```bash
pytest apps/intelligence/tests/test_matching.py apps/intelligence/tests/test_extraction.py -v
```

## Week 5 — Match explanations

Each match gets a 2–3 sentence plain-English explanation generated **only from computed facts** — never from the CV text or the job description.

- Prompt: `apps/intelligence/prompts/explain_match_v2.md` (v1 kept for history)
- Service: `apps/intelligence/explain.py` — `explain_match(result)`
- Tests: `apps/intelligence/tests/test_explain.py`

### What is sent to the LLM

| Fact | Source |
|---|---|
| Job title | `Job.title` |
| Candidate level, job level, level difference in words | `MatchResult.profile_seniority`, `Job.seniority`, `seniority_gap` |
| Required skills matched / missing, with counts (`3 of 4`) | `matched_required`, `missing_required` (max 3 names, then `+N more`) |
| Nice-to-have skills matched | `matched_nice` |
| What to lead with | level gap ≥ 2 → the level; under half the skills → the gaps; otherwise → the strengths |

Scores are not sent, so they can't be quoted back to the user.

### Output checks

The LLM output is validated before it's returned. It is rejected if it:
- is not 2–3 sentences, or is over 75 words
- has a preamble ("Here is…", "Start with…") or quotes a score
- uses flattering words (`strong`, `excellent`, `perfect`, `great`, `ideal`, `fit`)
- doesn't name a missing skill when one is missing
- doesn't mention a level gap, or states it the wrong way round ("you are three levels above" a principal role, for a junior)
- mentions a skill copied from the prompt's examples

Rejected output, or an LLM error, falls back to a deterministic template built from the same facts, so the user always gets an honest explanation. Pass `fallback=False` to get `''` instead.

```python
from apps.intelligence.explain import explain_match
text = explain_match(result)          # result: a MatchResult from match_profile()
```

Use `explain_match_with_source(result)` to also get where the text came from: `llm`, `template:rejected` (model output failed the checks) or `template:error` (LLM call failed).

### Verification

```bash
python manage.py match --cv <id> --top 3 --explain --narrate
```

Requires PostgreSQL and Ollama (`llama3.2`) running. Each result prints its component breakdown, then the explanation and its source and time, e.g.:

```
1    0.712   Backend Engineer          Acme        senior
      req=0.75  sem=0.62  sen=1.00 (gap=+0)  nice=0.00  recency=0.41
      matched : Django, PostgreSQL, Python
      missing : Kubernetes
      → You have three of the four required skills for this Backend Engineer role, including Django and PostgreSQL, and the level matches yours. The one gap is Kubernetes.
        [llm, 3.1s]

Explanations: 3/3 from the LLM, 0 from the template fallback.
```

Check each explanation against the `matched` / `missing` / `gap` lines directly above it: every skill it names must appear there, a missing skill must be named if there is one, a non-zero `gap` must be stated in the right direction (negative = role above your level), and there should be no praise and no score. `template:error` on every row means Ollama isn't reachable.

### Live check (llama3.2 via Ollama, 3 cases × 5 runs)

| | |
|---|---|
| Accepted by the checks | 11 / 15 — the 4 rejections were correct (wrong direction ×2, missing skills not named, "fit") |
| Latency | ~2–4 s warm, ~12 s on the first call after the model loads |
| Tokens | ~700 in, ~40 out per explanation |

Before the v2 checks, outputs that passed included "multiple skills are missing: Kubernetes" (one skill), "you are three levels above" a principal role for a junior candidate, and a skill (Redis) copied from the prompt example. Known residual: the checks are pattern-based, so a sentence can still contradict a fact in wording they don't cover (e.g. "you do not have any of the required skills" next to a matched skill).

**Count check (added with the cache).** A live run accepted "You are missing five of the six required skills" for a job where the candidate had 0 of 4. The model had copied the count from the prompt's Head of Nursing example. Every number in the output (digits or words up to twenty) must now be one of the computed counts, and "X of Y" must use the real required total. Numbers inside the job title or skill names ("Web3", "Python 3") are ignored. On the same 3 demo matches, llama3.2 then had 0/3 accepted, and all 3 rejections were correct: a wrong count, a "missing none" gap, and an unstated level difference. The template was shown instead. A low acceptance rate is the honest outcome with a 3B model. The next lever is the prompt itself (e.g. examples whose counts can't be confused with real ones), measured with the live check above.

### When to generate: on demand vs background

| | On demand (when a user opens a match) | Background (top N after each match run) |
|---|---|---|
| **Cost** | Only matches that are opened — typically a few of the top ten. Each explanation ~700 in / 40 out tokens: free on local Ollama, ≈ $0.00013 on gpt-4o-mini. | N per profile on every re-match, whether opened or not, plus regeneration whenever a profile, job or weight changes. Several times the on-demand volume. |
| **Latency** | 2–4 s wait on open (local model), ~12 s on a cold model. Hidden by showing the template text instantly and replacing it when the LLM returns. | Zero on open — already computed. |
| **Complexity** | Low: one call in the request path plus a cache. | Higher: a Celery task per match run, storage, invalidation when facts change, and handling users who open a result before it's ready (still needs the on-demand path as backup). |

**Recommendation: on demand, cached.** Add background pre-generation for the top 3 only if usage shows most users open those and the 2–4 s wait is a real complaint. A later improvement: show `fallback_explanation()` immediately and swap in the LLM text when it arrives (not built).

### Explanation cache

`explain_match_with_source()` caches each result in the Django cache (Redis) for a week:

- **Key:** `explain:<PROMPT_VERSION>:checks<CHECKS_VERSION>:sha256(model + rendered prompt)`. `CHECKS_VERSION` is bumped whenever `validate_explanation()` changes, so text accepted by older, weaker checks is never served. The rendered prompt contains every fact the explanation may use, so a new explanation is generated only when a fact, the prompt or the model changes. Score changes alone (e.g. new recency or weights) don't trigger a new call, because scores are never sent to the model. Two CVs with identical facts for the same job share one entry. The key contains no CV text.
- **What is cached:** accepted LLM output (`llm`) and rejected output replaced by the template (`template:rejected`), so the model isn't asked again for the same facts. A failed call (`template:error`) is **not** cached, so the next view retries.
- **Cache down:** reads and writes are wrapped, so the page still gets an explanation, just without caching.
- Reopening a match goes from 2–4 s to near-instant, and `match --narrate` on the same results makes no model calls on a second run.

## Week 5 — Matching evaluation

Full findings, every rating and the earlier round in [`docs/matching-evaluation.md`](docs/matching-evaluation.md).

### Evaluation 2 (current): 4 CVs × top 10 on real jobs

Four CVs (mine as a junior Business IT student, plus a senior backend engineer, a mid data analyst and a senior marketing manager) were matched against 110 eligible real jobs (Remotive + Arbeitnow, extracted with llama3.2). Each top-10 result was rated good / plausible / clearly wrong.

**Two extraction bugs had to be fixed before the results could be rated.** Both prompts' worked examples were being copied into the output: Python/Django/PostgreSQL + Redis onto 13 unrelated jobs (90 of 246 jobs had at least one invented skill), and Agile/Scrum onto every tech CV. `skills_in_text()` now drops any extracted skill that isn't in the text.

| CV | Clearly wrong in top 5 (weights 0.40 / 0.30 / 0.15 / 0.10 / 0.05) | With required_skill = 0.50 |
|---|---|---|
| Me, junior student | 1/5 | 2/5 |
| Senior backend engineer | 0/5 | 0/5 |
| Data analyst | 0/5 | 0/5 |
| Marketing manager | 0/5 | 0/5 |
| **Total** | **1/20 (5%)** | **2/20 (10%): worse, reverted** |

The ratings for the data analyst and marketing manager are lenient (software roles rated good), so 5% is a lower bound.

**Found and not fixed yet:**
- Jobs listing **no required skills get a free 0.5** coverage and reach the top 5 for 3 of 4 CVs.
- **No language filter:** 7 jobs need French or German.
- A **company name extracted as a skill** ("Docker" on a sales job at Docker).
- **Common skills** (Python) pull in unrelated senior roles.
- Student projects counted as **years of experience**.

## Week 5 — Tests and the page (Task 9)

### What the tests guarantee

| Guarantee | Tests |
|---|---|
| **Skill resolution across both sides** — a CV skill and a job skill written differently resolve to the same record | `test_cv_and_job_skill_written_differently_match_end_to_end` runs the real CV extraction (CV says "Postgres") and the real job extraction (job says "PostgreSQL") with a mocked LLM, then `match_profile()` — the match lists `PostgreSQL` as matched. Also `test_skill_resolution_*`, `apps/accounts/tests/test_cv_extraction.py`, and the upload page test. |
| **Scoring is deterministic** | `test_scoring_is_deterministic`, `test_scoring_is_deterministic_across_many_jobs` (5 jobs × 5 runs: identical order, totals and components) |
| **Hard filters exclude properly, at any score** | `test_remote_only_never_returns_onsite_even_perfect_match[on_site/hybrid]` — a job with 100% skills, same level and identical embedding ranks first unfiltered, and is still absent with `remote_only=True`, `min_score=0`, `limit=1000`. Plus countries, duplicates and min-skills filter tests, and `test_match_detail_respects_filters` for the page. |
| **Seniority penalises both ways** | `test_seniority_junior_vs_principal_scores_low` (≤ 0.2), `test_seniority_senior_vs_junior_scores_low`, `test_seniority_match_scores_full` |
| **Empty and unreadable CVs** — no crash, clear message, no garbage matches | Extraction: empty file, unsupported type, scanned PDF. Page: empty upload, PNG upload, DOCX with no readable text, LLM failure (all show a message, no CV stored or marked failed). A CV with no recognised skills gets a message and **no matches** — `match_profile()` now returns `[]` for a profile with no skills instead of ranking jobs on similarity alone. |
| **Explanations are faithful** | `test_explanation_describes_the_facts_of_a_real_match` — a real `match_profile()` result passed to a mocked model: the prompt carries exactly its levels, gap and skill lists, and never the job description or CV text; the text returned describes those same facts. Plus `apps/intelligence/tests/test_explain.py`. |

```bash
pytest                                              # all 136
pytest apps/intelligence/tests/test_matching.py apps/intelligence/tests/test_explain.py apps/accounts/tests -v
```

Fixed along the way: `conftest.py`'s `LocationFactory` created a new blank `Location` per job, violating the `(normalised_country, normalised_city)` unique constraint — any test needing two jobs crashed. It now reuses the row.

### The page

Plain HTML, no styling — it needs to work, not look finished.

| URL | What it does |
|---|---|
| `/` | Upload a PDF or DOCX, optionally tick **Remote only** and enter **Countries** (ISO codes, e.g. `KE,GB`). Lists your previous CVs. |
| `/cv/<id>/` | Your extracted profile (level, years, skills), the filters, and up to 20 ranked matches: total score, required-skill coverage with matched ✓ and missing ✗ skills, seniority with the gap ("role is 2 levels above you"), nice-to-have, similarity and recency. |
| `/cv/<id>/job/<job_id>/` | One match: the explanation (generated on demand, only for the match opened), the component table (score, weight, contribution), and the facts it was built from. |

Code: `apps/accounts/views.py`, `apps/accounts/urls.py`, `apps/accounts/forms.py` (`MatchFilterForm`), templates in `apps/accounts/templates/accounts/`.

Behaviour:
- **Sign-in required.** There's no sign-up flow yet; `LOGIN_URL` points at the admin login. Create a user with `python manage.py createsuperuser`. You only ever see your own CVs — anyone else's is a 404.
- **The file is never stored**, only the extracted text.
- Upload runs extraction and profile building in the request — a few seconds with the local model.
- Error messages: unsupported or empty file, no readable text (scanned PDF), "couldn't analyse it just now" (LLM failure — CV marked `failed`), "couldn't find any skills we recognise" (no matches shown), "No jobs pass your filters".

### Running it

```bash
docker compose up -d
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
# open http://localhost:8000/ and sign in
```

Ollama must be running with `llama3.2` and `nomic-embed-text`, and jobs must be extracted and embedded (see "Running LLM extraction" and "Embedding task").

### Live check

End-to-end on a throwaway Postgres + pgvector with the real local model and three sample jobs: a CV mentioning "Postgres" was resolved to `PostgreSQL`; with **Remote only** ticked the on-site job was excluded; the senior remote backend role ranked first at 0.85 with 4/4 required skills, and the principal data role second at 0.31 with every required skill listed as missing and "role is 1 level above you". The detail page showed the component breakdown and an explanation. The run surfaced two wording issues that were then fixed: the gap read "role is 1 above you", and the model wrote "Unfortunately, you are missing none of the required skills" when nothing was missing (now prevented in the prompt and rejected by the checks).

### Verification — `pytest -v` and `runserver`

- `pytest -v`: **136 passed, 0 failed.**
- `python manage.py runserver`, driven over HTTP exactly as a browser would (throwaway Postgres + pgvector, local llama3.2 and nomic-embed-text, three sample jobs):

| Step | Result |
|---|---|
| `GET /` signed out | 302 → `/admin/login/?next=/` |
| Sign in through the admin login form | 302 → `/`, upload form shown |
| Upload `sam_cv.docx` with **Remote only** | 302 → `/cv/<id>/?remote_only=on` in ~4 s. Profile: senior, skills Django, Docker, Git, Linux, PHP, PostgreSQL, Python ("Postgres" on the CV resolved to PostgreSQL) |
| Matches | 1. Senior Backend Engineer 0.85 — 4/4 required, same level. 2. Principal Data Engineer 0.30 — all 4 required missing, "role is 1 level above you". The on-site Nairobi role was filtered out. |
| Open match 1 | 200 in ~2 s: explanation, component table (contributions sum to 0.85), facts |
| Upload a PNG | 200 with "Unsupported file type. Upload a PDF or DOCX." |
| Server log | no tracebacks, no 500s |

Found and fixed during this check: the prompt shortened *matched* skills to "Django, Docker, PostgreSQL (+1 more)", so the model invented "another skill that is not listed". Matched skills are now listed in full (up to 6); only missing skills are cut to 3. The output checks now also reject "good match", invented "not listed" skills, and "missing is none"-style phrasing.

Known limits seen in the live run: years of experience is approximate (a CV running 2014–present came back as 7–8 years); and for an all-skills-matched job llama3.2 often fails the checks, so the template explanation is shown — accurate, but plainer.
