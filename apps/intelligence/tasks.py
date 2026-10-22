import html
import logging
import re
import time

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from apps.intelligence.llm.client import LLMClient, LLMMessage
from apps.intelligence.models import Job, JobSkill, ExtractionRun, extraction_run
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
    job.save(update_fields=['extraction_status', 'extraction_error'])

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
