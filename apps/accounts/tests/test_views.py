"""
Tests for the upload → matches pages.

LLM and embedder are mocked; uploads are real DOCX files built in memory.
"""
import io
import json
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import CV, CVProfile
from apps.intelligence.llm.client import LLMClient, LLMResponse
from apps.intelligence.models import Job, JobSkill, Skill

VECTOR = [0.1] * 768
CV_TEXT = 'Senior backend engineer with seven years of Python, Django and Postgres in production systems.'


def _docx(text: str) -> SimpleUploadedFile:
    import docx
    doc = docx.Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return SimpleUploadedFile('cv.docx', buf.getvalue())


def _llm(payload):
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return LLMClient(_call_fn=lambda **kw: LLMResponse(
        content=content, tokens_in=0, tokens_out=0, cost_usd=0.0, model='test'))


def _upload(client, upload, payload, **data):
    with patch('apps.accounts.cv_extraction.LLMClient', return_value=_llm(payload)), \
         patch('apps.accounts.cv_extraction._embed_batch', return_value=[VECTOR]):
        return client.post(reverse('accounts:upload'), {'file': upload, **data})


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username='alice', password='pw')


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def _job(job_factory, title, remote, skills=('Python', 'Django', 'PostgreSQL', 'Kubernetes')):
    job = job_factory(title=title, extraction_status=Job.ExtractionStatus.SUCCESS,
                      seniority='senior', embedding=VECTOR, extracted_remote_status=remote)
    for name in skills:
        skill, _ = Skill.objects.get_or_create(normalised_name=name.lower(), defaults={'name': name})
        JobSkill.objects.create(job=job, skill=skill)
    return job


@pytest.fixture
def jobs(db, job_factory):
    Skill.objects.create(name='PostgreSQL', normalised_name='postgresql')
    from apps.intelligence.models import SkillAlias
    SkillAlias.objects.create(skill=Skill.objects.get(normalised_name='postgresql'),
                              alias='Postgres', normalised='postgres')
    return {
        'remote': _job(job_factory, 'Remote Backend Engineer', 'remote'),
        'onsite': _job(job_factory, 'Onsite Backend Engineer', 'on_site'),
    }


GOOD_PROFILE = {'skills': ['Python', 'Django', 'Postgres'], 'seniority': 'senior', 'years_experience': 7}


# ── Access ────────────────────────────────────────────────────────────────

def test_login_required(client, db):
    resp = client.get(reverse('accounts:upload'))
    assert resp.status_code == 302
    assert resp['Location'].startswith(reverse('login'))


def test_other_users_cv_is_404(logged_in, db):
    other = get_user_model().objects.create_user(username='bob', password='pw')
    cv = CV.objects.create(owner=other, original_filename='bob.pdf', status='ready', extracted_text='x')
    assert logged_in.get(reverse('accounts:matches', args=[cv.pk])).status_code == 404


# ── Happy path ────────────────────────────────────────────────────────────

def test_upload_shows_ranked_matches_with_scores_and_gaps(logged_in, jobs):
    resp = _upload(logged_in, _docx(CV_TEXT), GOOD_PROFILE)
    assert resp.status_code == 302

    page = logged_in.get(resp['Location']).content.decode()
    assert 'Remote Backend Engineer' in page
    assert 'Onsite Backend Engineer' in page
    assert 'PostgreSQL' in page                     # 'Postgres' on the CV resolved to the job's skill
    assert 'missing: Kubernetes' in page            # the gap is shown
    assert '0.' in page                             # a score is shown

    cv = CV.objects.get()
    assert cv.file.name in (None, '')               # the file itself is not stored


def test_remote_only_filter_carried_from_upload(logged_in, jobs):
    resp = _upload(logged_in, _docx(CV_TEXT), GOOD_PROFILE, remote_only='on')
    assert 'remote_only=on' in resp['Location']

    page = logged_in.get(resp['Location']).content.decode()
    assert 'Remote Backend Engineer' in page
    assert 'Onsite Backend Engineer' not in page


def test_match_detail_shows_explanation_and_breakdown(logged_in, jobs):
    resp = _upload(logged_in, _docx(CV_TEXT), GOOD_PROFILE)
    cv = CV.objects.get()
    explanation = ('You have three of the four required skills for this Remote Backend Engineer role, '
                   'and the level matches yours. The one gap is Kubernetes.')
    args = [cv.pk, jobs['remote'].pk]

    # The page itself renders without calling the model…
    with patch('apps.intelligence.explain.LLMClient') as llm:
        page = logged_in.get(reverse('accounts:match_detail', args=args)).content.decode()
    llm.assert_not_called()
    assert 'required_skill' in page and 'seniority' in page
    assert 'Kubernetes' in page
    assert reverse('accounts:match_explanation', args=args) in page     # …and asks for the explanation

    with patch('apps.intelligence.explain.LLMClient', return_value=_llm(explanation)):
        fragment = logged_in.get(reverse('accounts:match_explanation', args=args)).content.decode()
    assert explanation in fragment
    assert '<html' not in fragment


def test_match_explanation_respects_ownership_and_filters(logged_in, jobs):
    _upload(logged_in, _docx(CV_TEXT), GOOD_PROFILE)
    cv = CV.objects.get()
    url = reverse('accounts:match_explanation', args=[cv.pk, jobs['onsite'].pk])
    assert logged_in.get(url + '?remote_only=on').status_code == 404

    other = get_user_model().objects.create_user(username='bob', password='pw')
    logged_in.force_login(other)
    assert logged_in.get(url).status_code == 404


def test_bad_country_filter_is_explained_in_the_htmx_results(logged_in, jobs):
    _upload(logged_in, _docx(CV_TEXT), GOOD_PROFILE)
    cv = CV.objects.get()
    page = logged_in.get(reverse('accounts:matches', args=[cv.pk]), {'countries': 'Kenya'},
                         HTTP_HX_REQUEST='true').content.decode()
    assert 'Filters not applied' in page
    assert 'two-letter country codes' in page
    assert 'Remote Backend Engineer' in page                         # results still shown, unfiltered


def test_match_detail_respects_filters(logged_in, jobs):
    _upload(logged_in, _docx(CV_TEXT), GOOD_PROFILE)
    cv = CV.objects.get()
    url = reverse('accounts:match_detail', args=[cv.pk, jobs['onsite'].pk]) + '?remote_only=on'
    assert logged_in.get(url).status_code == 404


# ── Empty and unreadable CVs ──────────────────────────────────────────────

def test_empty_file_clear_message(logged_in, jobs):
    resp = _upload(logged_in, SimpleUploadedFile('cv.pdf', b''), GOOD_PROFILE)
    assert resp.status_code == 200
    assert 'empty' in resp.content.decode().lower()
    assert not CV.objects.exists()


def test_unsupported_file_clear_message(logged_in, jobs):
    resp = _upload(logged_in, SimpleUploadedFile('cv.png', b'\x89PNG\r\n' + b'x' * 100), GOOD_PROFILE)
    assert 'Unsupported file type' in resp.content.decode()
    assert not CV.objects.exists()


def test_cv_with_no_readable_text_clear_message(logged_in, jobs):
    resp = _upload(logged_in, _docx('Hi'), GOOD_PROFILE)
    assert 'No readable text found' in resp.content.decode()
    assert not CV.objects.exists()


@pytest.mark.parametrize('name,data', [
    ('cv.docx', b'PK\x03\x04' + b'not really a zip' * 50),   # Word signature, broken inside
    ('cv.pdf', b'%PDF-1.4\n' + b'not really a pdf' * 50),    # PDF signature, broken inside
])
def test_corrupt_file_clear_message_no_crash(logged_in, jobs, name, data):
    resp = _upload(logged_in, SimpleUploadedFile(name, data), GOOD_PROFILE)
    assert resp.status_code == 200
    page = resp.content.decode()
    assert 'corrupt' in page.lower()
    assert 'Backend Engineer' not in page            # no matches shown
    assert not CVProfile.objects.exists()


def test_cv_with_no_recognised_skills_shows_no_matches(logged_in, jobs):
    resp = _upload(logged_in, _docx('Lorem ipsum dolor sit amet, ' * 5),
                   {'skills': [], 'seniority': 'not_stated', 'years_experience': 'not_stated'})
    page = logged_in.get(resp['Location']).content.decode()
    assert 'find any skills we recognise' in page
    assert 'Backend Engineer' not in page            # no garbage matches


def test_llm_failure_clear_message_no_crash(logged_in, jobs):
    resp = _upload(logged_in, _docx(CV_TEXT), 'not json')
    assert resp.status_code == 200
    assert 'analyse it just now' in resp.content.decode()
    assert CV.objects.get().status == CV.Status.FAILED
    assert not CVProfile.objects.exists()


def test_bad_country_code_rejected(logged_in, jobs):
    resp = _upload(logged_in, _docx(CV_TEXT), GOOD_PROFILE, countries='Kenya')
    assert resp.status_code == 200
    assert 'two-letter country codes' in resp.content.decode()
