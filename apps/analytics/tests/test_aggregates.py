from datetime import date, timedelta
from unittest.mock import patch

import pytest
from django.conf import settings
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.analytics import selectors
from apps.analytics.models import (
    HeadlineTotals,
    SeniorityDailyCount,
    SkillDailyCount,
    SourceDailyCount,
    WorkModeDailyCount,
)
from apps.analytics.services import refresh_aggregates
from apps.intelligence.models import Job, JobSkill, Location, Skill

pytestmark = pytest.mark.django_db

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


def _skill(name):
    return Skill.objects.get_or_create(normalised_name=name.lower(), defaults={'name': name})[0]


def _job(job_factory, *, day=TODAY, skills=(), nice=(), **kw):
    job = job_factory(published_date=day, **kw)
    for name in skills:
        JobSkill.objects.create(job=job, skill=_skill(name), is_required=True)
    for name in nice:
        JobSkill.objects.create(job=job, skill=_skill(name), is_required=False)
    return job


def _snapshot():
    """Every aggregate row as plain tuples, for comparing runs."""
    return {
        'skills': sorted(SkillDailyCount.objects.values_list('day', 'skill__name', 'job_count', 'required_count')),
        'seniority': sorted(SeniorityDailyCount.objects.values_list('day', 'seniority', 'job_count')),
        'work_mode': sorted(WorkModeDailyCount.objects.values_list('day', 'work_mode', 'job_count')),
        'source': sorted(SourceDailyCount.objects.values_list('day', 'source', 'job_count')),
        'headline': list(HeadlineTotals.objects.values_list('jobs_tracked', 'companies', 'distinct_skills')),
    }


@pytest.fixture
def dataset(job_factory):
    onsite = Location.objects.create(raw_text='Berlin', normalised_country='DE',
                                     normalised_city='berlin', is_remote=False)
    a = _job(job_factory, skills=['Python', 'Django'], nice=['Docker'], seniority='senior',
             extracted_remote_status='remote', source='remotive')
    b = _job(job_factory, skills=['Python'], seniority='junior', extracted_remote_status='on_site',
             source='arbeitnow', location=onsite, company=a.company)
    c = _job(job_factory, day=YESTERDAY, skills=['Python', 'React'], seniority='',
             extracted_remote_status='', source='remotive')            # remote by location only
    _job(job_factory, day=YESTERDAY, skills=['Go'], seniority='not_stated',
         extracted_remote_status='hybrid', source='arbeitnow', location=onsite)
    # A duplicate of `a` listed on another board — must never be counted
    _job(job_factory, skills=['Python', 'Rust'], seniority='senior', source='arbeitnow', canonical=a)
    return {'a': a, 'b': b, 'c': c}


# ── What gets counted ─────────────────────────────────────────────────────

def test_headline_totals(dataset):
    refresh_aggregates()
    h = selectors.headline()
    assert (h.jobs_tracked, h.companies, h.distinct_skills) == (4, 3, 5)   # Rust only on the duplicate


def test_top_skills_all_time_and_window(dataset):
    refresh_aggregates()
    top = selectors.top_skills()
    assert top[0] == {'skill_id': _skill('Python').pk, 'skill': 'Python', 'jobs': 3, 'required': 3}
    assert {r['skill'] for r in top} == {'Python', 'Django', 'Docker', 'React', 'Go'}
    docker = next(r for r in top if r['skill'] == 'Docker')
    assert (docker['jobs'], docker['required']) == (1, 0)                  # nice-to-have only

    today_only = {r['skill']: r['jobs'] for r in selectors.top_skills(days=1)}
    assert today_only == {'Python': 2, 'Django': 1, 'Docker': 1}


def test_skill_daily_trend(dataset):
    refresh_aggregates()
    python = _skill('Python').pk
    assert selectors.skill_trend([python], days=7) == {python: [(YESTERDAY, 1), (TODAY, 2)]}


def test_jobs_by_seniority_blank_and_not_stated_are_unknown(dataset):
    refresh_aggregates()
    assert selectors.jobs_by_seniority() == {'unknown': 2, 'junior': 1, 'senior': 1}


def test_work_mode_uses_extraction_then_location(dataset):
    refresh_aggregates()
    assert selectors.jobs_by_work_mode() == {'remote': 2, 'hybrid': 1, 'on_site': 1}


def test_new_jobs_per_day_per_source(dataset):
    refresh_aggregates()
    assert selectors.new_jobs_per_day(days=7) == [
        (YESTERDAY, 'arbeitnow', 1), (YESTERDAY, 'remotive', 1),
        (TODAY, 'arbeitnow', 1), (TODAY, 'remotive', 1),
    ]


def test_missing_published_date_falls_back_to_first_seen(job_factory):
    _job(job_factory, day=None, source='remotive')
    refresh_aggregates()
    assert selectors.new_jobs_per_day(days=1) == [(TODAY, 'remotive', 1)]


# ── Safe to run twice ─────────────────────────────────────────────────────

def test_refresh_twice_does_not_double_count(dataset):
    refresh_aggregates()
    first = _snapshot()
    refresh_aggregates()
    assert _snapshot() == first
    assert HeadlineTotals.objects.count() == 1


def test_refresh_reflects_changes_and_drops_stale_rows(dataset):
    refresh_aggregates()
    dataset['c'].delete()                                  # React and yesterday's remotive row go away
    Job.objects.filter(pk=dataset['b'].pk).update(seniority='senior')
    refresh_aggregates()

    assert 'React' not in {r['skill'] for r in selectors.top_skills()}
    assert selectors.jobs_by_seniority() == {'senior': 2, 'unknown': 1}
    assert (YESTERDAY, 'remotive', 1) not in selectors.new_jobs_per_day(days=7)


def test_refresh_on_empty_database():
    refresh_aggregates()
    h = selectors.headline()
    assert (h.jobs_tracked, h.companies, h.distinct_skills) == (0, 0, 0)
    assert selectors.top_skills() == []


def test_failed_refresh_keeps_the_previous_numbers(dataset):
    refresh_aggregates()
    before = _snapshot()
    with patch.object(SourceDailyCount.objects, 'bulk_create', side_effect=RuntimeError('boom')):
        with pytest.raises(RuntimeError):
            refresh_aggregates()
    assert _snapshot() == before                           # whole swap rolled back


# ── The dashboard never reads the raw tables ──────────────────────────────

def test_selectors_never_query_jobs(dataset):
    refresh_aggregates()
    with CaptureQueriesContext(connection) as ctx:
        selectors.headline()
        top = selectors.top_skills(days=30)
        selectors.skill_trend([r['skill_id'] for r in top], days=30)
        selectors.jobs_by_seniority()
        selectors.jobs_by_work_mode()
        selectors.new_jobs_per_day()
    sql = ' '.join(q['sql'] for q in ctx.captured_queries)
    assert '"intelligence_job"' not in sql
    assert '"intelligence_jobskill"' not in sql
    assert len(ctx.captured_queries) == 6                  # one per call


# ── Task and scheduling ───────────────────────────────────────────────────

def test_task_skips_when_another_refresh_holds_the_lock(dataset):
    from django.core.cache import cache
    from apps.analytics.tasks import LOCK_KEY, task_refresh_aggregates

    cache.add(LOCK_KEY, '1')
    assert task_refresh_aggregates.run() == {'skipped': True, 'reason': 'overlap'}
    assert not HeadlineTotals.objects.exists()

    cache.delete(LOCK_KEY)
    assert task_refresh_aggregates.run()['jobs_tracked'] == 4
    assert cache.get(LOCK_KEY) is None                     # released after the run


def test_transform_queues_a_refresh():
    from apps.ingestion.tasks import task_transform_jobs
    with patch('apps.analytics.tasks.task_refresh_aggregates.delay') as delay:
        task_transform_jobs.run()
    delay.assert_called_once_with()


def test_extraction_queues_a_refresh_only_when_jobs_were_extracted(job_factory):
    from apps.intelligence.tasks import task_extract_jobs
    job_factory(description='Python developer')
    ok = {'succeeded': 1, 'failed': 0, 'retried': 0, 'tokens_in': 0, 'tokens_out': 0, 'cost_usd': 0.0}

    with patch('apps.analytics.tasks.task_refresh_aggregates.delay') as delay, \
         patch('apps.intelligence.tasks.LLMClient'), \
         patch('apps.intelligence.tasks._extract_one', return_value=ok), \
         patch('apps.intelligence.tasks.time.sleep'):
        task_extract_jobs.run(dry_run=True)
        delay.assert_not_called()
        task_extract_jobs.run()
    delay.assert_called_once_with()


def test_broker_down_does_not_fail_the_transform():
    from apps.ingestion.tasks import task_transform_jobs
    with patch('apps.analytics.tasks.task_refresh_aggregates.delay', side_effect=ConnectionError):
        assert task_transform_jobs.run() == {'created': 0, 'skipped': 0, 'failed': 0}


def test_refresh_is_scheduled():
    from config.celery import app
    scheduled = {entry['task'] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
    assert 'apps.analytics.tasks.task_refresh_aggregates' in scheduled
    app.loader.import_default_modules()
    assert 'apps.analytics.tasks.task_refresh_aggregates' in app.tasks
