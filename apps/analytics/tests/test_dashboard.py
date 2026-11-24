import json
from datetime import date, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.analytics import selectors
from apps.analytics.models import DailySkillCount
from apps.analytics.services import refresh_aggregates
from apps.intelligence.models import JobSkill, Skill

pytestmark = pytest.mark.django_db

QUESTIONS = [
    'Which skills are employers asking for most?',
    'Is demand for those skills rising or falling?',
    'What level are employers hiring at?',
    'How many roles can be done remotely?',
]


def _skill(name):
    return Skill.objects.get_or_create(normalised_name=name.lower(), defaults={'name': name})[0]


@pytest.fixture
def data(job_factory):
    today = date.today()
    for i, (skills, level, remote) in enumerate([
        (['Python', 'Django'], 'senior', 'remote'),
        (['Python', 'React'], 'senior', 'remote'),
        (['Python'], 'junior', 'on_site'),
        (['Go'], '', 'hybrid'),
    ]):
        job = job_factory(published_date=today - timedelta(days=i * 10), seniority=level,
                          extracted_remote_status=remote)
        for s in skills:
            JobSkill.objects.create(job=job, skill=_skill(s))
    refresh_aggregates()


def _chart_data(resp):
    html = resp.content.decode()
    start = html.index('<script id="chart-data" type="application/json">') + len('<script id="chart-data" type="application/json">')
    return json.loads(html[start:html.index('</script>', start)])


def test_dashboard_before_first_refresh(client):
    resp = client.get(reverse('analytics:dashboard'))
    assert resp.status_code == 200
    assert 'No numbers yet' in resp.content.decode()
    assert 'chart-data' not in resp.content.decode()


def test_dashboard_is_public_and_answers_four_questions(client, data):
    resp = client.get(reverse('analytics:dashboard'))
    page = resp.content.decode()
    assert resp.status_code == 200
    for q in QUESTIONS:
        assert q in page
    assert page.count('<canvas') == 4                          # four charts, not five
    assert 'Jobs tracked' in page and 'New in the last 7 days' in page


def test_dashboard_chart_data(client, data):
    charts = _chart_data(client.get(reverse('analytics:dashboard')))
    assert charts['topSkills']['labels'][0] == 'Python'
    assert charts['topSkills']['values'][0] == 3
    assert charts['seniority']['labels'] == ['Junior', 'Mid', 'Senior', 'Principal', 'Director', 'Not stated']
    assert charts['seniority']['values'] == [1, 0, 2, 0, 0, 1]
    assert dict(zip(charts['workMode']['labels'], charts['workMode']['values'])) == {
        'Remote': 2, 'Hybrid': 1, 'On-site': 1, 'Not stated': 0,
    }
    assert len(charts['trend']['labels']) == 12
    python = next(s for s in charts['trend']['series'] if s['label'] == 'Python')
    assert sum(python['values']) == 3


def test_dashboard_states_the_answers(client, data):
    page = client.get(reverse('analytics:dashboard')).content.decode()
    assert 'Python is asked for most: 3 of 4 jobs (75%).' in page
    assert 'most are senior (2 of 3)' in page
    assert '2 of 4 jobs (50%) can be done fully remotely.' in page


def test_dashboard_never_reads_raw_jobs(client, data):
    with CaptureQueriesContext(connection) as ctx:
        client.get(reverse('analytics:dashboard'))
    sql = ' '.join(q['sql'] for q in ctx.captured_queries)
    assert '"intelligence_job"' not in sql
    assert '"intelligence_jobskill"' not in sql
    assert len(ctx.captured_queries) <= 10


def test_weekly_trend_buckets_by_week_up_to_latest_data():
    skill = _skill('Python')
    monday = date(2026, 3, 2)
    DailySkillCount.objects.bulk_create([
        DailySkillCount(day=monday, skill=skill, job_count=2),
        DailySkillCount(day=monday + timedelta(days=3), skill=skill, job_count=1),      # same week
        DailySkillCount(day=monday + timedelta(days=14), skill=skill, job_count=4),     # two weeks on
    ])
    weeks, series = selectors.weekly_skill_trend([skill.pk], weeks=4)
    assert weeks == [monday - timedelta(weeks=1), monday, monday + timedelta(weeks=1), monday + timedelta(weeks=2)]
    assert series[skill.pk] == [0, 3, 0, 4]


def test_weekly_trend_with_no_data():
    assert selectors.weekly_skill_trend([1], weeks=12) == ([], {1: []})
