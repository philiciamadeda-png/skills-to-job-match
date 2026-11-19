"""
Tests for CV profile extraction (Task 5).

Covers:
- CV skill variants resolve to the same canonical Skill as job skills
- Seniority and years_experience are stored in the job vocabulary
- The CV embedding uses the shared job embedder and model
- CV and job embed_text() are built the same way
- LLM failure and empty text return False without raising
"""
import json
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.accounts.cv_extraction import extract_cv_profile
from apps.accounts.models import CV, CVProfile
from apps.intelligence.llm.client import LLMClient, LLMResponse
from apps.intelligence.models import Job, JobSkill, Skill, SkillAlias
from apps.intelligence.services import resolve_skill
from apps.intelligence.tasks import EMBED_MODEL

FAKE_VECTOR = [0.1] * 768


def _fake_client(payload):
    content = payload if isinstance(payload, str) else json.dumps(payload)

    def call(**kwargs):
        return LLMResponse(content=content, tokens_in=0, tokens_out=0, cost_usd=0.0, model='test')

    return LLMClient(_call_fn=call)


@pytest.fixture
def postgres(db):
    skill = Skill.objects.create(name='PostgreSQL', normalised_name='postgresql')
    SkillAlias.objects.create(skill=skill, alias='Postgres', normalised='postgres')
    return skill


@pytest.fixture
def cv(db):
    user = get_user_model().objects.create_user(username='cv-tester', password='x')
    return CV.objects.create(
        owner=user,
        original_filename='cv.pdf',
        status=CV.Status.READY,
        extracted_text='Senior backend engineer. 7 years with Python and Postgres.',
    )


def _run(cv, payload, embed_return=None):
    with patch('apps.accounts.cv_extraction.LLMClient', return_value=_fake_client(payload)), \
         patch('apps.accounts.cv_extraction._embed_batch', return_value=[embed_return or FAKE_VECTOR]) as embed:
        ok = extract_cv_profile(cv)
    return ok, embed


def test_cv_skill_variant_matches_job_canonical_skill(cv, postgres, job_factory):
    """CV says 'Postgres', job says 'PostgreSQL' — both land on the same Skill."""
    job = job_factory(extraction_status=Job.ExtractionStatus.SUCCESS)
    JobSkill.objects.create(job=job, skill=resolve_skill('PostgreSQL'))

    ok, _ = _run(cv, {'skills': ['Postgres', 'Python'], 'seniority': 'senior', 'years_experience': 7})

    assert ok is True
    cv_skill_ids = set(cv.profile.skills.values_list('pk', flat=True))
    job_skill_ids = set(job.skills.values_list('pk', flat=True))
    assert postgres.pk in cv_skill_ids
    assert cv_skill_ids & job_skill_ids == {postgres.pk}


def test_seniority_and_years_stored(cv, postgres):
    ok, _ = _run(cv, {'skills': ['Python'], 'seniority': 'senior', 'years_experience': 7})

    assert ok is True
    cv.profile.refresh_from_db()
    assert cv.profile.seniority == 'senior'
    assert cv.profile.years_experience == 7


def test_years_not_stated_stored_as_null(cv, postgres):
    ok, _ = _run(cv, {'skills': ['Python'], 'seniority': 'not_stated', 'years_experience': 'not_stated'})

    assert ok is True
    cv.profile.refresh_from_db()
    assert cv.profile.years_experience is None
    assert cv.profile.seniority == 'not_stated'


def test_embedding_uses_shared_job_embedder(cv, postgres):
    ok, embed = _run(cv, {'skills': ['Postgres'], 'seniority': 'senior', 'years_experience': 7})

    assert ok is True
    embed.assert_called_once_with([cv.profile.embed_text()])
    cv.profile.refresh_from_db()
    assert cv.profile.embedding == FAKE_VECTOR
    assert cv.profile.embedding_model == EMBED_MODEL


def test_cv_and_job_embed_text_share_structure(cv, postgres, job_factory):
    """Both sides: <head> | <seniority> | skills: ... | <first 400 chars>."""
    job = job_factory(seniority='senior', description='Backend role using Postgres.')
    JobSkill.objects.create(job=job, skill=postgres)
    _run(cv, {'skills': ['Postgres'], 'seniority': 'senior', 'years_experience': 7})

    cv_parts = cv.profile.embed_text().split(' | ')
    job_parts = job.embed_text().split(' | ')

    assert len(cv_parts) == len(job_parts) == 4
    assert cv_parts[1] == job_parts[1] == 'senior'
    assert cv_parts[2] == job_parts[2] == 'skills: PostgreSQL'


def test_llm_failure_returns_false(cv):
    ok, embed = _run(cv, 'not json at all')

    assert ok is False
    embed.assert_not_called()
    assert not CVProfile.objects.filter(cv=cv).exists()


def test_empty_text_returns_false(cv):
    cv.extracted_text = '   '
    cv.save()
    ok, embed = _run(cv, {'skills': [], 'seniority': 'junior', 'years_experience': 1})

    assert ok is False
    embed.assert_not_called()


def test_build_profile_returns_profile_with_canonical_names(cv, postgres):
    from apps.accounts.services import build_profile

    with patch('apps.accounts.cv_extraction.LLMClient',
               return_value=_fake_client({'skills': ['Postgres'], 'seniority': 'senior', 'years_experience': 7})), \
         patch('apps.accounts.cv_extraction._embed_batch', return_value=[FAKE_VECTOR]):
        p = build_profile(cv.pk)

    assert [s.canonical_name for s in p.skills.all()] == ['PostgreSQL']
    assert p.seniority == 'senior'
    assert p.years_experience == 7


def test_build_profile_raises_on_failure(cv):
    from apps.accounts.services import ProfileBuildError, build_profile

    cv.extracted_text = ''
    cv.save()
    with pytest.raises(ProfileBuildError):
        build_profile(cv.pk)


def test_embed_failure_is_non_fatal(cv, postgres):
    with patch('apps.accounts.cv_extraction.LLMClient',
               return_value=_fake_client({'skills': ['Postgres'], 'seniority': 'mid', 'years_experience': 3})), \
         patch('apps.accounts.cv_extraction._embed_batch', side_effect=RuntimeError('ollama down')):
        ok = extract_cv_profile(cv)

    assert ok is True
    cv.profile.refresh_from_db()
    assert cv.profile.embedding is None
    assert list(cv.profile.skills.all()) == [postgres]


# ── Skills the CV never mentions are dropped ──────────────────────────────

def test_invented_skills_dropped_before_matching(cv, postgres):
    """The model added 'Agile' and 'Scrum' (from the prompt's own examples) to CVs without them."""
    ok, _ = _run(cv, {'skills': ['Postgres', 'Python', 'Agile', 'Scrum'], 'seniority': 'senior', 'years_experience': 7})

    assert ok is True
    names = set(cv.profile.skills.values_list('name', flat=True))
    assert names == {'PostgreSQL', 'Python'}


@pytest.mark.parametrize('skill,text,kept', [
    ('Python', 'Built APIs in Python.', True),
    ('python', 'Built APIs in PYTHON.', True),                      # case-insensitive
    ('CI/CD with GitHub Actions', 'Set up CI/CD with\nGitHub  Actions.', True),   # whitespace differences
    ('C++', 'Wrote firmware in C++ and C.', True),
    ('Node.js', 'Services in Node.js', True),
    ('Agile', 'Python developer.', False),
    ('Go', 'Good at Google Sheets.', False),                        # whole words only
    ('Java', 'JavaScript developer.', False),
])
def test_skills_in_text(skill, text, kept):
    from apps.intelligence.services import skills_in_text
    assert skills_in_text([skill], text) == (([skill], []) if kept else ([], [skill]))


def test_prompt_has_no_skill_examples_to_copy():
    from apps.accounts.cv_extraction import _render_cv_prompt
    prompt = _render_cv_prompt('CV TEXT')
    assert 'Agile' not in prompt and 'Scrum' not in prompt
    assert prompt.rstrip().endswith('CV TEXT')
