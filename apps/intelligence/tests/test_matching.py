"""
Tests for the CV-to-job matching pipeline.

Covers:
- Skill resolution: CV and job skills written differently resolve to same record
- Scoring determinism: same inputs always give same score
- Hard filters: remote-only profile never receives on_site job
- Seniority penalty: both directions (junior vs principal, senior vs intern)
- Empty/unreadable CV: no crash, clear message
- Explanation faithfulness: mocked LLM receives the correct facts
"""
import pytest
from unittest.mock import patch, MagicMock

from apps.intelligence.models import Job, Skill, SkillAlias, JobSkill
from apps.intelligence.matching import match_profile, MatchResult
from apps.intelligence.services import resolve_skill
from apps.intelligence.explain import explain_match
from apps.intelligence.llm.client import LLMResponse
from apps.accounts.extraction import extract_text
import io


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def canonical_skill(db):
    return Skill.objects.create(name='PostgreSQL', normalised_name='postgresql')


@pytest.fixture
def skill_alias(db, canonical_skill):
    return SkillAlias.objects.create(
        skill=canonical_skill, alias='Postgres', normalised='postgres'
    )


@pytest.fixture
def job_with_skills(db, canonical_skill):
    from conftest import JobFactory, CompanyFactory
    job = JobFactory(
        extraction_status=Job.ExtractionStatus.SUCCESS,
        seniority='senior',
        embedding=[0.1] * 768,
        embedding_model='nomic-embed-text',
        extracted_remote_status='remote',
    )
    # Add 3 skills so job passes MIN_JOB_SKILLS filter
    for name, norm in [('PostgreSQL', 'postgresql'), ('Python', 'python'), ('Django', 'django')]:
        skill, _ = Skill.objects.get_or_create(normalised_name=norm, defaults={'name': name})
        JobSkill.objects.get_or_create(job=job, skill=skill)
    return job


@pytest.fixture
def profile(db, canonical_skill):
    """A CVProfile-like object with skills, seniority, and embedding."""
    from django.contrib.auth import get_user_model
    from apps.accounts.models import CV, CVProfile

    User = get_user_model()
    user = User.objects.create_user(username='tester', password='x')
    cv = CV.objects.create(
        owner=user, extracted_text='Senior Python engineer', status='ready',
        original_filename='cv.pdf',
    )
    p = CVProfile.objects.create(
        cv=cv, seniority='senior', years_experience=5,
        embedding=[0.1] * 768, embedding_model='nomic-embed-text',
    )
    p.skills.add(canonical_skill)
    return p


# ---------------------------------------------------------------------------
# 1. Skill resolution — CV variant and job canonical resolve to same record
# ---------------------------------------------------------------------------

def test_skill_resolution_alias_matches_canonical(db, canonical_skill, skill_alias):
    """'Postgres' (alias) and 'PostgreSQL' (canonical) resolve to the same Skill."""
    resolved_alias     = resolve_skill('Postgres')
    resolved_canonical = resolve_skill('PostgreSQL')
    assert resolved_alias.pk == resolved_canonical.pk
    assert resolved_alias.pk == canonical_skill.pk


def test_skill_resolution_case_insensitive(db, canonical_skill):
    """Case variants resolve to the same canonical record."""
    assert resolve_skill('postgresql').pk == canonical_skill.pk
    assert resolve_skill('POSTGRESQL').pk == canonical_skill.pk


# ---------------------------------------------------------------------------
# 2. Scoring determinism
# ---------------------------------------------------------------------------

def test_scoring_is_deterministic(db, profile, job_with_skills):
    results_a = match_profile(profile)
    results_b = match_profile(profile)
    assert len(results_a) == len(results_b)
    for a, b in zip(results_a, results_b):
        assert a.total_score == b.total_score
        assert a.required_skill_score == b.required_skill_score
        assert a.semantic_score == b.semantic_score


# ---------------------------------------------------------------------------
# 3. Hard filter — remote_only excludes on_site jobs
# ---------------------------------------------------------------------------

def test_remote_only_excludes_onsite(db, profile, job_with_skills):
    job_with_skills.extracted_remote_status = 'on_site'
    job_with_skills.save(update_fields=['extracted_remote_status'])

    results = match_profile(profile, remote_only=True)
    job_ids = [r.job.pk for r in results]
    assert job_with_skills.pk not in job_ids


def test_remote_only_includes_remote(db, profile, job_with_skills):
    job_with_skills.extracted_remote_status = 'remote'
    job_with_skills.save(update_fields=['extracted_remote_status'])

    results = match_profile(profile, remote_only=True)
    job_ids = [r.job.pk for r in results]
    assert job_with_skills.pk in job_ids


# ---------------------------------------------------------------------------
# 4. Seniority penalises both directions
# ---------------------------------------------------------------------------

def test_seniority_junior_vs_principal_scores_low(db, profile, job_with_skills):
    profile.seniority = 'junior'
    profile.save(update_fields=['seniority'])
    job_with_skills.seniority = 'principal'
    job_with_skills.save(update_fields=['seniority'])
    profile.refresh_from_db()

    results = match_profile(profile)
    r = next(x for x in results if x.job.pk == job_with_skills.pk)
    assert r.seniority_score <= 0.2
    assert r.seniority_gap < 0


def test_seniority_senior_vs_junior_scores_low(db, profile, job_with_skills):
    profile.seniority = 'senior'
    profile.save(update_fields=['seniority'])
    job_with_skills.seniority = 'junior'
    job_with_skills.save(update_fields=['seniority'])
    profile.refresh_from_db()

    results = match_profile(profile)
    r = next(x for x in results if x.job.pk == job_with_skills.pk)
    assert r.seniority_score <= 0.6
    assert r.seniority_gap > 0


def test_seniority_match_scores_full(db, profile, job_with_skills):
    profile.seniority = 'senior'
    profile.save(update_fields=['seniority'])
    job_with_skills.seniority = 'senior'
    job_with_skills.save(update_fields=['seniority'])
    profile.refresh_from_db()

    results = match_profile(profile)
    r = next(x for x in results if x.job.pk == job_with_skills.pk)
    assert r.seniority_score == 1.0
    assert r.seniority_gap == 0


# ---------------------------------------------------------------------------
# 5. Empty and unreadable CVs
# ---------------------------------------------------------------------------

def test_empty_file_returns_error():
    result = extract_text(io.BytesIO(b''))
    assert not result.ok
    assert result.error


def test_scanned_pdf_flagged_not_crashed():
    minimal_pdf = (
        b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj '
        b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj '
        b'3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj\n'
        b'xref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n'
        b'0000000058 00000 n\n0000000115 00000 n\n'
        b'trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF'
    )
    result = extract_text(io.BytesIO(minimal_pdf))
    assert not result.ok
    assert result.is_scanned
    assert 'scanned' in result.error.lower()


def test_unsupported_type_rejected():
    result = extract_text(io.BytesIO(b'\x89PNG\r\n' + b'x' * 100))
    assert not result.ok
    assert 'Unsupported' in result.error


def test_profile_with_no_skills_returns_no_matches(db, job_with_skills):
    """A profile with zero skills must not crash and must not return garbage matches."""
    from django.contrib.auth import get_user_model
    from apps.accounts.models import CV, CVProfile

    User = get_user_model()
    user = User.objects.create_user(username='empty_user', password='x')
    cv = CV.objects.create(
        owner=user, extracted_text='', status='ready', original_filename='empty.pdf',
    )
    p = CVProfile.objects.create(
        cv=cv, seniority='senior', embedding=[0.1] * 768,
        embedding_model='nomic-embed-text',
    )
    assert match_profile(p) == []


# ---------------------------------------------------------------------------
# 6. Explanation faithfulness — mocked LLM receives correct facts
# ---------------------------------------------------------------------------

def test_explain_match_sends_correct_facts(db, profile, job_with_skills):
    """The explanation prompt must contain the actual matched/missing skill names."""
    captured = {}

    def fake_call(model, messages, timeout):
        captured['messages'] = messages  # list of dicts: [{"role": ..., "content": ...}]
        return LLMResponse(
            content='Good match.', tokens_in=10, tokens_out=5, cost_usd=0.0, model='test',
        )

    from apps.intelligence.llm.client import LLMClient
    client = LLMClient(_call_fn=fake_call)

    result = MatchResult(
        job=job_with_skills,
        total_score=0.85,
        required_skill_score=1.0,
        semantic_score=0.8,
        seniority_score=1.0,
        nice_to_have_score=0.0,
        recency_score=0.5,
        matched_required=['PostgreSQL'],
        missing_required=[],
        matched_nice=[],
        seniority_gap=0,
    )

    explain_match(result, client=client)

    assert captured, 'LLM was never called'
    prompt_text = captured['messages'][0]['content']
    assert 'PostgreSQL' in prompt_text
    assert '(1 of 1)' in prompt_text   # required skill coverage as counts
    assert '0.85' not in prompt_text   # scores are not quoted to the candidate


# ---------------------------------------------------------------------------
# 7. Required vs nice-to-have are scored separately
# ---------------------------------------------------------------------------

def test_nice_to_have_scored_separately(db, profile, job_with_skills):
    redis = Skill.objects.create(name='Redis', normalised_name='redis')
    JobSkill.objects.create(job=job_with_skills, skill=redis, is_required=False)
    profile.skills.add(redis)

    r = next(x for x in match_profile(profile) if x.job.pk == job_with_skills.pk)

    assert r.required_skill_score == round(1 / 3, 4)    # PostgreSQL of PostgreSQL/Python/Django
    assert r.nice_to_have_score == 1.0
    assert r.matched_nice == ['Redis']
    assert 'Redis' not in r.matched_required + r.missing_required


def test_contributions_sum_to_total(db, profile, job_with_skills):
    r = next(x for x in match_profile(profile) if x.job.pk == job_with_skills.pk)
    assert set(r.components) == {'required_skill', 'semantic', 'seniority', 'nice_to_have', 'recency'}
    assert abs(sum(r.contributions.values()) - r.total_score) < 0.001


# ---------------------------------------------------------------------------
# 8. Hard filters
# ---------------------------------------------------------------------------

def _ids(results):
    return {r.job.pk for r in results}


def test_remote_only_excludes_hybrid(db, profile, job_with_skills):
    job_with_skills.extracted_remote_status = 'hybrid'
    job_with_skills.save(update_fields=['extracted_remote_status'])
    assert job_with_skills.pk not in _ids(match_profile(profile, remote_only=True))
    assert job_with_skills.pk in _ids(match_profile(profile, remote_only=False))


def test_countries_filter(db, profile, job_with_skills):
    from apps.intelligence.models import Location

    job_with_skills.location = Location.objects.create(
        raw_text='Berlin, Germany', normalised_country='DE', normalised_city='berlin',
    )
    job_with_skills.save(update_fields=['location'])

    assert job_with_skills.pk not in _ids(match_profile(profile, countries=['KE']))
    assert job_with_skills.pk in _ids(match_profile(profile, countries=['ke', 'de']))


def test_countries_filter_keeps_unstated_location(db, profile, job_with_skills):
    job_with_skills.location = None
    job_with_skills.save(update_fields=['location'])
    assert job_with_skills.pk in _ids(match_profile(profile, countries=['KE']))


def test_duplicate_jobs_excluded(db, profile, job_with_skills):
    from conftest import JobFactory
    original = JobFactory()
    job_with_skills.canonical = original
    job_with_skills.save(update_fields=['canonical'])
    assert job_with_skills.pk not in _ids(match_profile(profile))


def test_jobs_with_too_few_skills_excluded(db, profile, job_with_skills):
    JobSkill.objects.filter(job=job_with_skills, skill__normalised_name='django').delete()
    assert job_with_skills.pk not in _ids(match_profile(profile))


# ---------------------------------------------------------------------------
# 9. Weight overrides
# ---------------------------------------------------------------------------

def test_resolve_weights_defaults_and_rescale():
    from apps.intelligence.matching import WEIGHTS, resolve_weights

    assert resolve_weights() == pytest.approx(WEIGHTS)

    w = resolve_weights({'seniority': 0.6})
    assert sum(w.values()) == pytest.approx(1.0)
    assert w['seniority'] > WEIGHTS['seniority']
    assert w['required_skill'] < WEIGHTS['required_skill']


def test_resolve_weights_rejects_bad_input():
    from apps.intelligence.matching import resolve_weights

    with pytest.raises(ValueError):
        resolve_weights({'salary': 0.2})
    with pytest.raises(ValueError):
        resolve_weights({'seniority': -0.1})


def test_weight_override_changes_score_and_contributions(db, profile, job_with_skills):
    job_with_skills.seniority = 'junior'          # gap 2 → seniority_score 0.2
    job_with_skills.save(update_fields=['seniority'])

    before = next(x for x in match_profile(profile) if x.job.pk == job_with_skills.pk)
    after = next(
        x for x in match_profile(profile, weights={'seniority': 0.6})
        if x.job.pk == job_with_skills.pk
    )

    assert after.seniority_score == before.seniority_score   # raw component unchanged
    assert after.total_score != before.total_score            # weighting changed
    assert abs(sum(after.contributions.values()) - after.total_score) < 0.001


# ---------------------------------------------------------------------------
# 10. Task 9 — end-to-end guarantees
# ---------------------------------------------------------------------------

def _fake_llm(content):
    from apps.intelligence.llm.client import LLMClient
    return LLMClient(_call_fn=lambda **kw: LLMResponse(
        content=content, tokens_in=0, tokens_out=0, cost_usd=0.0, model='test'))


def test_cv_and_job_skill_written_differently_match_end_to_end(db, canonical_skill, skill_alias):
    """CV says 'Postgres', job says 'PostgreSQL' — both pipelines run, and the match counts it."""
    import json
    from conftest import JobFactory
    from django.contrib.auth import get_user_model
    from apps.accounts.cv_extraction import extract_cv_profile
    from apps.accounts.models import CV
    from apps.intelligence.tasks import _extract_one

    job = JobFactory(description='Backend role.')
    _extract_one(job, _fake_llm(json.dumps({
        'required_skills': ['PostgreSQL', 'Python', 'Docker'], 'nice_to_have_skills': [],
        'seniority': 'senior', 'years_required': 'not_stated',
        'remote_status': 'remote', 'contract_type': 'full_time',
    })))
    job.embedding = [0.1] * 768
    job.save(update_fields=['embedding'])

    user = get_user_model().objects.create_user(username='e2e', password='x')
    cv = CV.objects.create(owner=user, original_filename='cv.pdf', status='ready',
                           extracted_text='Senior engineer, 6 years of Postgres.')
    with patch('apps.accounts.cv_extraction.LLMClient', return_value=_fake_llm(json.dumps(
            {'skills': ['Postgres'], 'seniority': 'senior', 'years_experience': 6}))), \
         patch('apps.accounts.cv_extraction._embed_batch', return_value=[[0.1] * 768]):
        assert extract_cv_profile(cv)

    r = next(x for x in match_profile(cv.profile) if x.job.pk == job.pk)
    assert r.matched_required == ['PostgreSQL']
    assert 'PostgreSQL' not in r.missing_required
    assert r.required_skill_score == round(1 / 3, 4)


def test_scoring_is_deterministic_across_many_jobs(db, profile, job_with_skills):
    from conftest import JobFactory
    for i, (level, vec) in enumerate([('mid', 0.2), ('junior', 0.3), ('senior', 0.1), ('principal', 0.05)]):
        job = JobFactory(extraction_status=Job.ExtractionStatus.SUCCESS, seniority=level,
                         embedding=[vec] * 384 + [0.0] * 384)
        for name in ('PostgreSQL', 'Python', 'Django', f'Extra{i}'):
            skill, _ = Skill.objects.get_or_create(normalised_name=name.lower(), defaults={'name': name})
            JobSkill.objects.get_or_create(job=job, skill=skill)

    runs = [[(r.job.pk, r.total_score, r.components) for r in match_profile(profile)] for _ in range(5)]
    assert len(runs[0]) == 5
    assert all(run == runs[0] for run in runs)


@pytest.mark.parametrize('status', ['on_site', 'hybrid'])
def test_remote_only_never_returns_onsite_even_perfect_match(db, profile, job_with_skills, status):
    """The best-scoring job in the database is still excluded if it isn't remote."""
    for skill in job_with_skills.skills.all():
        profile.skills.add(skill)                      # 100% required coverage, same level, same vector
    job_with_skills.extracted_remote_status = status
    job_with_skills.save(update_fields=['extracted_remote_status'])

    unfiltered = match_profile(profile, limit=1000)
    assert unfiltered[0].job.pk == job_with_skills.pk   # it would rank first
    assert unfiltered[0].required_skill_score == 1.0

    filtered = match_profile(profile, remote_only=True, limit=1000, min_score=0.0)
    assert job_with_skills.pk not in _ids(filtered)


def test_explanation_describes_the_facts_of_a_real_match(db, profile, job_with_skills):
    """Facts from match_profile() reach the model unchanged; nothing else does."""
    from apps.intelligence.llm.client import LLMClient

    job_with_skills.seniority = 'principal'
    job_with_skills.description = 'CONFIDENTIAL JOB DESCRIPTION'
    job_with_skills.save(update_fields=['seniority', 'description'])
    profile.seniority = 'junior'
    profile.save(update_fields=['seniority'])

    r = next(x for x in match_profile(profile) if x.job.pk == job_with_skills.pk)
    captured = {}

    def fake_call(model, messages, timeout):
        captured['prompt'] = messages[0]['content']
        return LLMResponse(content='x', tokens_in=0, tokens_out=0, cost_usd=0.0, model='test')

    text = explain_match(r, client=LLMClient(_call_fn=fake_call))
    prompt = captured['prompt']

    assert 'Candidate level: junior' in prompt
    assert 'Job level: principal' in prompt
    assert 'the role is 3 levels above your level' in prompt
    assert '(1 of 3): PostgreSQL' in prompt
    assert '(2 of 3): Django, Python' in prompt
    assert 'CONFIDENTIAL JOB DESCRIPTION' not in prompt
    assert profile.cv.extracted_text not in prompt
    # 'x' fails validation, so the template is used — and it describes the same facts
    assert 'Django' in text and 'Python' in text and 'above your level' in text
