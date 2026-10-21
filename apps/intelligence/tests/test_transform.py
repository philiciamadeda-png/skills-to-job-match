import json
import logging
from datetime import timezone, datetime
from pathlib import Path

import pytest

from apps.ingestion.models import RawJobPayload
from apps.intelligence.models import Company, Job, Skill, SkillAlias
from apps.intelligence.services import transform_raw_payloads

FIXTURES = Path(__file__).parent / "fixtures"


def _make_payload(source, raw_data):
    from apps.ingestion.services import compute_hash
    return RawJobPayload.objects.create(
        source=source,
        raw_data=raw_data,
        content_hash=compute_hash(raw_data),
        fetched_at=datetime.now(tz=timezone.utc),
    )


# ---------------------------------------------------------------------------
# 1. Idempotency — running transform twice produces no duplicate Job rows
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_transform_twice_no_duplicate_jobs():
    raw = json.loads((FIXTURES / "remotive_backend_engineer.json").read_text())
    _make_payload("remotive", raw)

    result1 = transform_raw_payloads()
    # Reset processed flag to simulate a re-run
    RawJobPayload.objects.update(processed=False)
    result2 = transform_raw_payloads()

    assert Job.objects.count() == 1
    assert result1["created"] == 1
    assert result2["created"] == 0
    assert result2["skipped"] == 1


# ---------------------------------------------------------------------------
# 2. Normalisation collapses company and skill variants to one record
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_normalisation_collapses_variants():
    # Two payloads with the same company under different raw names
    raw1 = json.loads((FIXTURES / "remotive_backend_engineer.json").read_text())
    raw2 = {**raw1, "id": 9002, "company_name": "Acme Corp, Inc."}

    _make_payload("remotive", raw1)
    _make_payload("remotive", raw2)
    transform_raw_payloads()

    assert Company.objects.count() == 1

    # Skill normalisation: "PostgreSQL" and "Postgres" resolve to the same Skill
    canonical = Skill.objects.create(name="PostgreSQL", normalised_name="postgresql")
    SkillAlias.objects.create(skill=canonical, alias="Postgres", normalised="postgres")

    from apps.intelligence.services import resolve_skill
    assert resolve_skill("PostgreSQL") == canonical
    assert resolve_skill("Postgres") == canonical
    assert Skill.objects.count() == 1


# ---------------------------------------------------------------------------
# 3. Same job from two sources → two Job rows, dedup links them
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_cross_source_dedup_links_jobs():
    remotive_raw = json.loads((FIXTURES / "remotive_backend_engineer.json").read_text())
    arbeitnow_raw = json.loads((FIXTURES / "arbeitnow_backend_engineer.json").read_text())

    _make_payload("remotive", remotive_raw)
    _make_payload("arbeitnow", arbeitnow_raw)
    transform_raw_payloads()

    assert Job.objects.count() == 2

    from apps.intelligence.services import deduplicate_jobs
    result = deduplicate_jobs()

    assert result["duplicate_groups"] == 1
    assert result["duplicates_marked"] == 1

    # The canonical job is the earliest-created one (remotive)
    canonical = Job.objects.get(source="remotive", source_id="9001")
    duplicate = Job.objects.get(source="arbeitnow", source_id="backend-engineer-acme-corp")
    assert duplicate.canonical == canonical
    assert canonical.canonical is None


# ---------------------------------------------------------------------------
# 4. Malformed payload in a batch does not block the rest
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_malformed_payload_skipped_rest_processed(caplog):
    good_raw = json.loads((FIXTURES / "remotive_backend_engineer.json").read_text())
    bad_raw = {"id": None, "title": ""}  # missing id → _map_remotive raises ValueError

    _make_payload("remotive", bad_raw)
    _make_payload("remotive", good_raw)

    with caplog.at_level(logging.ERROR, logger="apps.intelligence.services"):
        result = transform_raw_payloads()

    assert result["failed"] == 1
    assert result["created"] == 1
    assert Job.objects.count() == 1
