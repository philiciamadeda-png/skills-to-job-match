from unittest.mock import patch

from django.core.management import call_command


def test_pipeline_runs_every_stage_in_order():
    from apps.ingestion.management.commands.start_pipeline import pipeline
    steps = [(s.task, s.args, s.kwargs, s.immutable) for s in pipeline().tasks]
    assert steps == [
        ('apps.ingestion.tasks.task_ingest_jobs', ('remotive',), {}, True),
        ('apps.ingestion.tasks.task_ingest_jobs', ('arbeitnow',), {'max_pages': 3}, True),
        ('apps.ingestion.tasks.task_transform_jobs', (), {}, True),
        ('apps.intelligence.tasks.task_extract_jobs', (), {}, True),
        ('apps.intelligence.tasks.task_embed_jobs', (), {}, True),
    ]


def test_command_only_queues(capsys):
    with patch('celery.canvas._chain.apply_async') as queue:
        queue.return_value.id = 'abc'
        call_command('start_pipeline')
    queue.assert_called_once()
    assert 'Queued ingest → transform → extract → embed (abc)' in capsys.readouterr().out
