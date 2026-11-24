"""
What the dashboard reads. Every function here queries the small aggregation
tables only — never Job or JobSkill — so page cost does not grow with the
number of jobs.

`days` limits a breakdown to jobs posted in the last N days; None means all time.
"""
from datetime import date, timedelta

from django.db.models import Sum

from apps.analytics.models import (
    HeadlineTotals,
    DailySeniorityCount,
    DailySkillCount,
    DailySourceCount,
    DailyWorkModeCount,
)


def _since(qs, days: int | None):
    if days is None:
        return qs
    return qs.filter(day__gt=date.today() - timedelta(days=days))


def headline() -> HeadlineTotals | None:
    return HeadlineTotals.objects.filter(pk=1).first()


def top_skills(days: int | None = None, limit: int = 20) -> list[dict]:
    """[{'skill_id', 'skill': name, 'jobs', 'required'}, …] most requested first."""
    qs = (
        _since(DailySkillCount.objects, days)
        .values('skill_id', 'skill__name')
        .annotate(jobs=Sum('job_count'), required=Sum('required_count'))
        .order_by('-jobs', 'skill__name')[:limit]
    )
    return [
        {'skill_id': r['skill_id'], 'skill': r['skill__name'], 'jobs': r['jobs'], 'required': r['required']}
        for r in qs
    ]


def skill_trend(skill_ids, days: int = 30) -> dict[int, list[tuple[date, int]]]:
    """Daily job counts per skill, oldest day first. Days with no jobs are absent."""
    trend: dict[int, list[tuple[date, int]]] = {pk: [] for pk in skill_ids}
    qs = (
        _since(DailySkillCount.objects, days)
        .filter(skill_id__in=skill_ids)
        .order_by('day')
        .values_list('skill_id', 'day', 'job_count')
    )
    for skill_id, day, n in qs:
        trend[skill_id].append((day, n))
    return trend


def _breakdown(model, field: str, days: int | None) -> dict[str, int]:
    qs = _since(model.objects, days).values(field).annotate(jobs=Sum('job_count')).order_by('-jobs', field)
    return {r[field]: r['jobs'] for r in qs}


def jobs_by_seniority(days: int | None = None) -> dict[str, int]:
    return _breakdown(DailySeniorityCount, 'seniority', days)


def jobs_by_work_mode(days: int | None = None) -> dict[str, int]:
    return _breakdown(DailyWorkModeCount, 'work_mode', days)


def new_jobs_per_day(days: int = 30) -> list[tuple[date, str, int]]:
    """(day, source, jobs) rows, oldest day first."""
    return list(
        _since(DailySourceCount.objects, days)
        .order_by('day', 'source')
        .values_list('day', 'source', 'job_count')
    )
