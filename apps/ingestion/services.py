import hashlib
import json
from datetime import datetime, timezone

from apps.ingestion.models import RawJobPayload

HASH_FIELDS = ('id', 'title', 'company_name', 'description', 'job_type', 'salary', 'candidate_required_location')


def compute_hash(job: dict) -> str:
    subset = {k: job.get(k) for k in HASH_FIELDS}
    return hashlib.sha256(json.dumps(subset, sort_keys=True).encode()).hexdigest()


def ingest_from_source(source_name: str, jobs: list[dict]) -> dict:
    existing = set(RawJobPayload.objects.filter(
        source=source_name
    ).values_list('content_hash', flat=True))

    to_create = []
    for job in jobs:
        h = compute_hash(job)
        if h not in existing:
            to_create.append(RawJobPayload(
                source=source_name,
                raw_data=job,
                content_hash=h,
                fetched_at=datetime.now(tz=timezone.utc),
            ))

    RawJobPayload.objects.bulk_create(to_create)
    return {'total': len(jobs), 'saved': len(to_create), 'skipped': len(jobs) - len(to_create)}
