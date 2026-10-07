import pytest
from unittest.mock import patch
from conftest import JobFactory, RawJobPayloadFactory
from apps.ingestion.services import compute_hash, ingest_from_source
from apps.ingestion.models import RawJobPayload


SAMPLE_JOB = {
    "id": 123,
    "title": "Backend Engineer",
    "company_name": "Acme",
    "description": "Build things.",
    "job_type": "full_time",
    "salary": "$100k",
    "candidate_required_location": "Remote",
    "url": "https://remotive.com/job/123",
    "publication_date": "2026-01-01T00:00:00",
}

REMOTIVE_RESPONSE = {"jobs": [SAMPLE_JOB], "job-count": 1}


@pytest.mark.django_db
def test_job_model_created_with_valid_data():
    job = JobFactory(title="Data Engineer", source="remotive")
    assert job.pk is not None
    assert job.title == "Data Engineer"
    assert job.source == "remotive"


def test_content_hash_stable_and_unique():
    hash1 = compute_hash(SAMPLE_JOB)
    hash2 = compute_hash(SAMPLE_JOB)
    assert hash1 == hash2  # identical input → identical hash

    different_job = {**SAMPLE_JOB, "title": "Frontend Engineer"}
    assert compute_hash(different_job) != hash1  # different input → different hash


@pytest.mark.django_db
def test_remotive_source_parses_response():
    from apps.ingestion.sources.remotive import RemotiveSource
    source = RemotiveSource(limit=1)

    with patch.object(source, '_get', return_value=REMOTIVE_RESPONSE):
        jobs = source.fetch_all()

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Backend Engineer"
    assert jobs[0]["company_name"] == "Acme"


@pytest.mark.django_db
def test_ingest_twice_no_duplicates():
    jobs = [SAMPLE_JOB]

    result1 = ingest_from_source("remotive", jobs)
    result2 = ingest_from_source("remotive", jobs)

    assert result1["saved"] == 1
    assert result2["saved"] == 0
    assert result2["skipped"] == 1
    assert RawJobPayload.objects.count() == 1
