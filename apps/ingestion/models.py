from contextlib import contextmanager
from django.db import models
from django.utils import timezone
from apps.core.models import TimestampedModel


class RawJobPayload(TimestampedModel):
    source = models.CharField(max_length=100, db_index=True)
    raw_data = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True, db_index=True)
    fetched_at = models.DateTimeField()
    processed = models.BooleanField(default=False, db_index=True)
    job = models.ForeignKey(
        'intelligence.Job', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='raw_payloads'
    )

    class Meta:
        indexes = [
            models.Index(fields=['source', 'fetched_at']),
        ]


class IngestionRun(models.Model):
    class Stage(models.TextChoices):
        INGEST = 'ingest', 'Ingest'
        TRANSFORM = 'transform', 'Transform'

    class Status(models.TextChoices):
        RUNNING = 'running', 'Running'
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'

    stage = models.CharField(max_length=20, choices=Stage.choices)
    source = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    fetched = models.PositiveIntegerField(default=0)
    created = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)

    @property
    def duration(self):
        if self.finished_at and self.started_at:
            return self.finished_at - self.started_at
        return None

    class Meta:
        indexes = [
            models.Index(fields=['status', '-started_at']),
        ]

    def __str__(self):
        return f"{self.stage}:{self.source} [{self.status}] {self.started_at:%Y-%m-%d %H:%M}"


@contextmanager
def ingestion_run(stage, source):
    run = IngestionRun.objects.create(stage=stage, source=source)
    try:
        yield run
        run.status = IngestionRun.Status.SUCCESS
    except Exception as exc:
        run.status = IngestionRun.Status.FAILED
        run.error = str(exc)
        raise
    finally:
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'finished_at', 'fetched', 'created', 'skipped', 'failed', 'error'])
