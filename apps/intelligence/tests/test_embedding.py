"""
Tests for the job embedding task and its place in the scheduled pipeline.

The embedder is always mocked — no Ollama calls.
"""
from unittest.mock import patch

import pytest
from django.conf import settings

from apps.intelligence.models import EmbeddingRun, Job
from apps.intelligence.tasks import EMBED_MODEL, task_embed_jobs

VECTOR = [0.1] * 768


def _fake_embed(texts):
    return [VECTOR for _ in texts]


def _run():
    with patch('apps.intelligence.tasks._embed_batch', side_effect=_fake_embed) as embed:
        result = task_embed_jobs.run(batch_size=2)
    return result, embed


@pytest.fixture
def extracted_jobs(job_factory):
    return [job_factory(title=f'Backend Engineer {i}', extraction_status=Job.ExtractionStatus.SUCCESS)
            for i in range(3)]


def test_every_extracted_job_embedded_with_model_hash_and_date(extracted_jobs, job_factory):
    pending = job_factory(title='Not extracted yet')   # extraction_status defaults to pending

    result, _ = _run()

    assert result['succeeded'] == 3
    for job in extracted_jobs:
        job.refresh_from_db()
        assert job.embedding is not None
        assert job.embedding_model == EMBED_MODEL
        assert job.embedding_hash == job.embed_text_hash()
        assert job.embedded_at is not None
    pending.refresh_from_db()
    assert pending.embedding is None                   # only extracted jobs are embedded

    run = EmbeddingRun.objects.get()
    assert run.status == EmbeddingRun.Status.SUCCESS
    assert run.model == EMBED_MODEL
    assert run.started_at and run.finished_at


def test_rerun_skips_current_embeddings(extracted_jobs):
    _run()
    result, embed = _run()

    assert result['succeeded'] == 0
    embed.assert_not_called()


def test_changed_text_is_re_embedded(extracted_jobs):
    _run()
    job = extracted_jobs[0]
    job.refresh_from_db()
    first = job.embedded_at
    job.title = 'Data Engineer'
    job.save(update_fields=['title'])

    result, embed = _run()

    assert result['succeeded'] == 1
    assert embed.call_args.args[0] == [job.embed_text()]
    job.refresh_from_db()
    assert job.embedded_at > first


def test_failed_batch_is_retried_on_next_run(extracted_jobs):
    with patch('apps.intelligence.tasks._embed_batch', side_effect=RuntimeError('ollama down')):
        result = task_embed_jobs.run(batch_size=10)
    assert result['failed'] == 3
    assert not Job.objects.exclude(embedding=None).exists()

    result, _ = _run()                                 # resumes: nothing was marked done
    assert result['succeeded'] == 3


@pytest.mark.parametrize('task', [
    'apps.ingestion.tasks.task_ingest_jobs',
    'apps.ingestion.tasks.task_transform_jobs',
    'apps.intelligence.tasks.task_extract_jobs',
    'apps.intelligence.tasks.task_embed_jobs',
])
def test_pipeline_stage_is_scheduled(task):
    from config.celery import app
    scheduled = {entry['task'] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
    assert task in scheduled
    app.loader.import_default_modules()
    assert task in app.tasks                           # the name resolves to a registered task
