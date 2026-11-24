"""
N+1 guards: each page or task must run the same number of queries with 3 rows
as with 30. A loop that touches job.company (or job.skills) without
select_related / prefetch_related adds one query per row and fails here.
"""
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import CV, CVProfile
from apps.intelligence.models import Job, JobSkill, Skill

pytestmark = pytest.mark.django_db

VECTOR = [0.1] * 768
FEW, MANY = 3, 30


def _skills():
    return [Skill.objects.get_or_create(normalised_name=n.lower(), defaults={'name': n})[0]
            for n in ('Python', 'Django', 'PostgreSQL')]


def _make_jobs(job_factory, n, **kw):
    skills = _skills()
    for _ in range(n):
        job = job_factory(extraction_status=Job.ExtractionStatus.SUCCESS, seniority='senior',
                          extracted_remote_status='remote', **kw)
        for s in skills:
            JobSkill.objects.create(job=job, skill=s)


def _count(fn) -> int:
    with CaptureQueriesContext(connection) as ctx:
        fn()
    return len(ctx.captured_queries)


def _counts_for(job_factory, fn, **kw) -> tuple[int, int]:
    """Query count of fn() with FEW jobs, then with MANY."""
    _make_jobs(job_factory, FEW, **kw)
    few = _count(fn)
    _make_jobs(job_factory, MANY - FEW, **kw)
    assert Job.objects.count() == MANY
    return few, _count(fn)


@pytest.fixture
def admin_client(client):
    user = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw')
    client.force_login(user)
    return client


def test_matches_page_query_count_does_not_grow(client, job_factory):
    user = get_user_model().objects.create_user(username='alice', password='pw')
    client.force_login(user)
    cv = CV.objects.create(owner=user, original_filename='cv.docx', status=CV.Status.READY, extracted_text='x')
    profile = CVProfile.objects.create(cv=cv, seniority='senior', embedding=VECTOR)
    profile.skills.set(_skills())

    def load():
        resp = client.get(reverse('accounts:matches', args=[cv.pk]))
        assert resp.status_code == 200

    few, many = _counts_for(job_factory, load, embedding=VECTOR)
    assert many == few
    assert many <= 10


def test_job_list_query_count_does_not_grow(client, job_factory):
    def load():
        assert client.get(reverse('jobs:list'), {'q': 'job'}).status_code == 200

    few, many = _counts_for(job_factory, load)
    assert many == few
    assert many <= 10


def test_profile_page_query_count_does_not_grow(client, job_factory):
    user = get_user_model().objects.create_user(username='alice', password='pw')
    client.force_login(user)
    for name in ('a.docx', 'b.docx', 'c.docx'):
        cv = CV.objects.create(owner=user, original_filename=name, status=CV.Status.READY, extracted_text='x')
        CVProfile.objects.create(cv=cv, seniority='senior', embedding=VECTOR).skills.set(_skills())

    def load():
        assert client.get(reverse('accounts:profile')).status_code == 200

    few, many = _counts_for(job_factory, load, embedding=VECTOR)
    assert many == few
    assert many <= 10


@pytest.mark.parametrize('url_name', [
    'admin:intelligence_job_changelist',
    'admin:intelligence_jobskill_changelist',
])
def test_admin_list_query_count_does_not_grow(admin_client, job_factory, url_name):
    def load():
        assert admin_client.get(reverse(url_name)).status_code == 200

    few, many = _counts_for(job_factory, load)
    assert many == few


def test_embedding_task_query_count_does_not_grow(job_factory):
    from apps.intelligence.tasks import task_embed_jobs

    def run():
        Job.objects.update(embedding=None)
        with patch('apps.intelligence.tasks._embed_batch', side_effect=lambda texts: [VECTOR] * len(texts)):
            task_embed_jobs.run(batch_size=50)

    few, many = _counts_for(job_factory, run)
    assert many == few
