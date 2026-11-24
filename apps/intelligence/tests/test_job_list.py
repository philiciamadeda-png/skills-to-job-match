from datetime import date, timedelta

import pytest
from django.urls import reverse

from apps.analytics import selectors
from apps.analytics.services import refresh_aggregates
from apps.intelligence.models import Company, JobSkill, Location, Skill

pytestmark = pytest.mark.django_db

URL = reverse('jobs:list')
HTMX = {'HTTP_HX_REQUEST': 'true'}


def _job(job_factory, title, *, skills=(), **kw):
    job = job_factory(title=title, **kw)
    for name in skills:
        skill, _ = Skill.objects.get_or_create(normalised_name=name.lower(), defaults={'name': name})
        JobSkill.objects.create(job=job, skill=skill)
    return job


@pytest.fixture
def jobs(job_factory):
    berlin = Location.objects.create(raw_text='Berlin', normalised_country='DE', normalised_city='berlin')
    acme = Company.objects.create(name='Acme Analytics', normalised_name='acme analytics')
    a = _job(job_factory, 'Senior Python Engineer', skills=['Python', 'Django'], seniority='senior',
             extracted_remote_status='remote', source='remotive')
    _job(job_factory, 'Junior Data Analyst', skills=['SQL'], seniority='junior', company=acme,
         extracted_remote_status='on_site', location=berlin, source='arbeitnow')
    _job(job_factory, 'Frontend Developer', skills=['React'], seniority='', extracted_remote_status='',
         source='remotive')                                                 # remote by location only
    _job(job_factory, 'Senior Python Engineer (repost)', skills=['Python'], canonical=a, source='arbeitnow')
    return a


def _titles(resp):
    return [j.title for j in resp.context['page'].object_list]


def test_public_full_page(client, jobs):
    resp = client.get(URL)
    assert resp.status_code == 200
    assert '<html' in resp.content.decode()
    assert sorted(_titles(resp)) == ['Frontend Developer', 'Junior Data Analyst', 'Senior Python Engineer']


def test_duplicates_are_hidden(client, jobs):
    assert 'Senior Python Engineer (repost)' not in _titles(client.get(URL))


def test_htmx_request_gets_only_the_results_partial(client, jobs):
    resp = client.get(URL, {'q': 'python'}, **HTMX)
    page = resp.content.decode()
    assert '<html' not in page and '<nav class="mx-auto' not in page
    assert 'Senior Python Engineer' in page
    assert 'HX-Request' in resp['Vary']


def test_history_restore_gets_the_full_page(client, jobs):
    resp = client.get(URL, **HTMX, HTTP_HX_HISTORY_RESTORE_REQUEST='true')
    assert '<html' in resp.content.decode()


@pytest.mark.parametrize('q, expected', [
    ('engineer', ['Senior Python Engineer']),       # title
    ('acme', ['Junior Data Analyst']),              # company
    ('react', ['Frontend Developer']),              # skill
    ('cobol', []),
])
def test_search(client, jobs, q, expected):
    assert _titles(client.get(URL, {'q': q})) == expected


@pytest.mark.parametrize('params, expected', [
    ({'seniority': 'senior'}, ['Senior Python Engineer']),
    ({'seniority': 'unknown'}, ['Frontend Developer']),
    ({'work_mode': 'on_site'}, ['Junior Data Analyst']),
    ({'work_mode': 'remote'}, ['Frontend Developer', 'Senior Python Engineer']),
    ({'source': 'arbeitnow'}, ['Junior Data Analyst']),
    ({'source': 'remotive', 'seniority': 'senior'}, ['Senior Python Engineer']),
])
def test_filters(client, jobs, params, expected):
    assert sorted(_titles(client.get(URL, params))) == expected


def test_invalid_filter_value_is_ignored_not_an_error(client, jobs):
    resp = client.get(URL, {'seniority': 'wizard'})
    assert resp.status_code == 200


def test_remote_filter_agrees_with_dashboard(client, jobs):
    refresh_aggregates()
    listed = client.get(URL, {'work_mode': 'remote'}).context['page'].paginator.count
    assert listed == selectors.jobs_by_work_mode()['remote']


def test_pagination_keeps_filters_and_orders_newest_first(client, job_factory):
    today = date.today()
    for i in range(25):
        job_factory(title=f'Role {i:02}', published_date=today - timedelta(days=i), source='remotive')
    job_factory(title='Other board', source='arbeitnow')

    first = client.get(URL, {'source': 'remotive'})
    assert first.context['page'].paginator.count == 25
    assert _titles(first)[:2] == ['Role 00', 'Role 01']
    assert len(_titles(first)) == 20
    assert 'source=remotive&amp;page=2' in first.content.decode()

    second = client.get(URL, {'source': 'remotive', 'page': 2}, **HTMX)
    assert _titles(second) == [f'Role {i}' for i in range(20, 25)]


def test_out_of_range_page_shows_last_page(client, jobs):
    assert client.get(URL, {'page': 99}).status_code == 200
