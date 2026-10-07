from django.db import models
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
