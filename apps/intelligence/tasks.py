import html
import logging
import re
import time

import requests
from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from apps.intelligence.ml_service import predict_batch

from apps.intelligence.llm.client import LLMClient, LLMMessage
from apps.intelligence.models import (
    Job, JobSkill, ExtractionRun, extraction_run,
    EmbeddingRun, embedding_run,
)
from apps.intelligence.prompts import render_extraction_prompt
from apps.intelligence.services import resolve_skill

logger = logging.getLogger(__name__)

LOCK_KEY = 'extraction_lock'
LOCK_TTL = 7200  # 2 hours
_INTER_JOB_DELAY = 1.0  # seconds between LLM calls — tune to provider rate limit


def _strip_html(text: str) -> str:
    return re.sub(r'<[^>]+>', ' ', html.unescape(text)).strip()


def _extract_one(job: Job, client: LLMClient) -> dict:
    """
    Run extraction for a single job. Returns a stats dict.
    Never raises — records failure on the job and returns.
    """
    from apps.intelligence.schemas import JobExtractionResult

    desc = _strip_html(job.description)[:3000]
    messages = [
        LLMMessage(role='system', content='You are a job data extractor.'),
        LLMMessage(role='user', content=render_extraction_prompt(desc)),
    ]

    sr = client.extract_structured(messages, JobExtractionResult)

    if sr.result is None:
        job.extraction_status = Job.ExtractionStatus.FAILED
        job.extraction_error = sr.failure_reason or 'unknown'
        job.save(update_fields=['extraction_status', 'extraction_error'])
        return {'succeeded': 0, 'failed': 1, 'retried': int(sr.retried), 'tokens_in': 0, 'tokens_out': 0, 'cost_usd': 0.0}

    result = sr.result

    # Persist skills
    now = timezone.now()
    for raw_skill in list(result.required_skills) + list(result.nice_to_have_skills):
        try:
            skill = resolve_skill(raw_skill)
            JobSkill.objects.get_or_create(
                job=job, skill=skill,
                defaults={'extraction_method': 'llm', 'extracted_at': now},
            )
        except Exception as exc:
            logger.warning('extract: skill resolve failed job=%s skill=%r — %s', job.pk, raw_skill, exc)

    job.extraction_status = Job.ExtractionStatus.SUCCESS
    job.extraction_error = ''
    job.seniority = result.seniority.value if result.seniority else ''
    job.extracted_remote_status = result.remote_status.value if result.remote_status else ''
    job.extracted_contract_type = result.contract_type.value if result.contract_type else ''
    job.save(update_fields=['extraction_status', 'extraction_error', 'seniority', 'extracted_remote_status', 'extracted_contract_type'])

    # Approximate token counts — LLMClient.chat() returns LLMResponse but
    # extract_structured doesn't expose it. We read from the last response via
    # a lightweight re-call; instead we track 0 here and note this as a known gap.
    # To get real counts, extract_structured would need to return them — future work.
    return {'succeeded': 1, 'failed': 0, 'retried': int(sr.retried), 'tokens_in': 0, 'tokens_out': 0, 'cost_usd': 0.0}


@shared_task(bind=True, max_retries=0)
def task_extract_jobs(self, batch_size: int = 50, limit: int | None = None, dry_run: bool = False):
    """
    Extract skills from all pending jobs using the LLM.

    - Resumable: only processes jobs with extraction_status='pending'
    - Concurrency guard: Redis lock prevents overlapping runs
    - Rate limiting: _INTER_JOB_DELAY seconds between calls
    - Records totals in ExtractionRun

    Args:
        batch_size: DB fetch size per iteration
        limit: cap total jobs processed (useful for sampling)
        dry_run: fetch jobs and count them but make no LLM calls
    """
    if not cache.add(LOCK_KEY, '1', LOCK_TTL):
        logger.warning('task_extract_jobs: already running, skipping')
        return {'skipped': True, 'reason': 'overlap'}

    try:
        with extraction_run() as run:
            client = LLMClient()
            qs = Job.objects.filter(
                extraction_status=Job.ExtractionStatus.PENDING,
                description__gt='',
            ).order_by('id')

            total_processed = 0
            last_id = 0

            while True:
                if limit and total_processed >= limit:
                    break

                batch = list(qs.filter(id__gt=last_id)[:batch_size])
                if not batch:
                    break

                if limit:
                    remaining = limit - total_processed
                    batch = batch[:remaining]

                for job in batch:
                    if dry_run:
                        total_processed += 1
                        run.processed += 1
                        continue

                    stats = _extract_one(job, client)
                    run.processed += 1
                    run.succeeded += stats['succeeded']
                    run.failed += stats['failed']
                    run.retried += stats['retried']
                    run.tokens_in += stats['tokens_in']
                    run.tokens_out += stats['tokens_out']
                    run.cost_usd += stats['cost_usd']
                    total_processed += 1

                    time.sleep(_INTER_JOB_DELAY)

                last_id = batch[-1].pk

            return {
                'processed': run.processed,
                'succeeded': run.succeeded,
                'failed': run.failed,
                'retried': run.retried,
                'cost_usd': float(run.cost_usd),
                'dry_run': dry_run,
            }
    finally:
        cache.delete(LOCK_KEY)


@shared_task
def task_predict_seniority(batch_size: int = 200) -> dict:
    """
    Predict seniority for all jobs missing a model-based prediction.
    Stores label, confidence, and model version on each Job row.
    Idempotent — skips jobs that already have seniority_model_version set.
    """
    from apps.intelligence.models import Job

    qs = Job.objects.filter(seniority_model_version="").only(
        "id", "title", "description"
    )
    total = updated = 0
    last_id = 0

    while True:
        batch = list(qs.filter(id__gt=last_id).order_by("id")[:batch_size])
        if not batch:
            break

        texts = [f"{j.title} {j.description}" for j in batch]
        predictions = predict_batch(texts)

        for job, pred in zip(batch, predictions):
            job.seniority = pred["label"]
            job.seniority_confidence = pred["confidence"]
            job.seniority_model_version = pred["model_version"]

        Job.objects.bulk_update(
            batch, ["seniority", "seniority_confidence", "seniority_model_version"],
            batch_size=batch_size,
        )
        updated += len(batch)
        total += len(batch)
        last_id = batch[-1].pk

    logger.info("task_predict_seniority: updated %d jobs", updated)
    return {"updated": updated}


# ---------------------------------------------------------------------------
# Embedding task
# ---------------------------------------------------------------------------

EMBED_LOCK_KEY = 'embedding_lock'
EMBED_LOCK_TTL = 3600
EMBED_MODEL = 'nomic-embed-text'
EMBED_BATCH_SIZE = 32
OLLAMA_EMBED_URL = 'http://localhost:11434/api/embed'


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Call Ollama embed endpoint for a batch of texts. Raises on HTTP error."""
    resp = requests.post(
        OLLAMA_EMBED_URL,
        json={'model': EMBED_MODEL, 'input': texts},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()['embeddings']


@shared_task(bind=True, max_retries=0)
def task_embed_jobs(self, batch_size: int = EMBED_BATCH_SIZE, limit: int | None = None):
    """
    Generate and store embeddings for every job that doesn't yet have a
    current one.

    "Current" means: embedding is not null AND embedding_hash matches the
    SHA-256 of the job's current embed_text() AND embedding_model matches
    EMBED_MODEL.  Any of those three being wrong triggers a re-embed.

    - Batches API calls (batch_size texts per request)
    - Resumable: cursor-based pagination, picks up where it left off after a crash
    - Records the run in EmbeddingRun
    - Skips jobs whose embedding is already current
    """
    if not cache.add(EMBED_LOCK_KEY, '1', EMBED_LOCK_TTL):
        logger.warning('task_embed_jobs: already running, skipping')
        return {'skipped': True, 'reason': 'overlap'}

    try:
        with embedding_run(EMBED_MODEL) as run:
            # Jobs needing (re-)embedding: null vector, wrong model, or stale hash.
            # The hash check for staleness happens in Python after fetching the batch
            # (avoids a computed-column migration). We over-fetch slightly on the
            # wrong-model / null cases; the hash check filters the rest.
            qs = (
                Job.objects
                .filter(extraction_status=Job.ExtractionStatus.SUCCESS)
                .prefetch_related('skills')
                .order_by('id')
            )

            total = 0
            last_id = 0

            while True:
                if limit and total >= limit:
                    break

                page = list(qs.filter(id__gt=last_id)[:batch_size])
                if not page:
                    break

                # Filter to only stale jobs
                stale = [
                    j for j in page
                    if (
                        j.embedding is None
                        or j.embedding_model != EMBED_MODEL
                        or j.embedding_hash != j.embed_text_hash()
                    )
                ]

                if stale:
                    texts = [j.embed_text() for j in stale]
                    try:
                        vectors = _embed_batch(texts)
                    except Exception as exc:
                        logger.error('task_embed_jobs: batch embed failed — %s', exc)
                        run.failed += len(stale)
                        run.processed += len(stale)
                        last_id = page[-1].pk
                        total += len(page)
                        continue

                    now = timezone.now()
                    for job, vec, text in zip(stale, vectors, texts):
                        import hashlib
                        job.embedding = vec
                        job.embedding_model = EMBED_MODEL
                        job.embedding_hash = hashlib.sha256(text.encode()).hexdigest()

                    Job.objects.bulk_update(
                        stale,
                        ['embedding', 'embedding_model', 'embedding_hash'],
                        batch_size=batch_size,
                    )
                    run.succeeded += len(stale)

                run.processed += len(page)
                total += len(page)
                last_id = page[-1].pk

            return {
                'processed': run.processed,
                'succeeded': run.succeeded,
                'failed': run.failed,
                'model': EMBED_MODEL,
            }
    finally:
        cache.delete(EMBED_LOCK_KEY)
