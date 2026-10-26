"""
Unit tests for the LLM extraction layer.

All tests use a fake _call_fn injected into LLMClient — no real network calls,
no Ollama, no OpenAI. Each test controls exactly what the model "returns".
"""
import pytest

from apps.intelligence.llm.client import LLMClient, LLMMessage, LLMResponse
from apps.intelligence.models import Job, JobSkill, Skill, SkillAlias
from apps.intelligence.tasks import _extract_one


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_client(*responses):
    """Return an LLMClient whose model returns each response in sequence."""
    it = iter(responses)

    def call_fn(**kw):
        return LLMResponse(
            content=next(it),
            tokens_in=10, tokens_out=20, cost_usd=0.0, model='test',
        )

    return LLMClient(_call_fn=call_fn)


_VALID_JSON = (
    '{"required_skills": ["Python", "Django"], '
    '"nice_to_have_skills": ["Redis"], '
    '"seniority": "senior", "years_required": 3, '
    '"remote_status": "remote", "contract_type": "full_time"}'
)

_FENCED_JSON = f"```json\n{_VALID_JSON}\n```"

_INVALID_ENUM_JSON = (
    '{"required_skills": ["Python"], '
    '"seniority": "INVALID", "years_required": "not_stated", '
    '"remote_status": "remote", "contract_type": "full_time"}'
)


# ---------------------------------------------------------------------------
# 1. Valid JSON — stored correctly, no retry
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_valid_json_stored_correctly(job_factory):
    job = job_factory(description="Senior Python/Django engineer, remote, full-time.")
    client = _fake_client(_VALID_JSON)

    stats = _extract_one(job, client)

    job.refresh_from_db()
    assert job.extraction_status == Job.ExtractionStatus.SUCCESS
    assert stats['succeeded'] == 1
    assert stats['failed'] == 0
    assert stats['retried'] == 0

    skill_names = set(JobSkill.objects.filter(job=job).values_list('skill__name', flat=True))
    assert 'Python' in skill_names
    assert 'Django' in skill_names


# ---------------------------------------------------------------------------
# 2. Fenced JSON — recovered without retry
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_fenced_json_recovered(job_factory):
    job = job_factory(description="Backend role.")
    client = _fake_client(_FENCED_JSON)

    stats = _extract_one(job, client)

    job.refresh_from_db()
    assert job.extraction_status == Job.ExtractionStatus.SUCCESS
    assert stats['retried'] == 0


# ---------------------------------------------------------------------------
# 3. Validation failure → exactly one retry → clean give-up, no exception
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_validation_failure_one_retry_then_gives_up(job_factory):
    job = job_factory(description="Some job.")
    # Both attempts return an invalid enum — retry cannot fix it
    client = _fake_client(_INVALID_ENUM_JSON, _INVALID_ENUM_JSON)

    stats = _extract_one(job, client)

    job.refresh_from_db()
    assert job.extraction_status == Job.ExtractionStatus.FAILED
    assert job.extraction_error != ''
    assert stats['succeeded'] == 0
    assert stats['failed'] == 1
    assert stats['retried'] == 1  # one retry was attempted
    assert JobSkill.objects.filter(job=job).count() == 0


# ---------------------------------------------------------------------------
# 4. Empty / no-JSON response → clean failure, no exception
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_empty_response_clean_failure(job_factory):
    job = job_factory(description="Some job.")
    client = _fake_client("Sorry, I cannot help with that.", "Still no JSON here.")

    stats = _extract_one(job, client)

    job.refresh_from_db()
    assert job.extraction_status == Job.ExtractionStatus.FAILED
    assert stats['failed'] == 1
    assert JobSkill.objects.filter(job=job).count() == 0


# ---------------------------------------------------------------------------
# 5. Skill strings resolve to existing Skill rows — no duplicates created
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_skills_resolve_to_existing_rows_no_duplicates(job_factory):
    # Seed canonical skill + alias
    canonical = Skill.objects.create(name='PostgreSQL', normalised_name='postgresql')
    SkillAlias.objects.create(skill=canonical, alias='Postgres', normalised='postgres')

    response = (
        '{"required_skills": ["Postgres", "PostgreSQL"], '
        '"nice_to_have_skills": [], '
        '"seniority": "mid", "years_required": "not_stated", '
        '"remote_status": "not_stated", "contract_type": "not_stated"}'
    )
    job = job_factory(description="Postgres role.")
    client = _fake_client(response)

    _extract_one(job, client)

    # Both "Postgres" and "PostgreSQL" must resolve to the same canonical row
    job_skills = JobSkill.objects.filter(job=job)
    assert job_skills.count() == 1
    assert job_skills.first().skill == canonical
    # No new Skill rows created
    assert Skill.objects.count() == 1
