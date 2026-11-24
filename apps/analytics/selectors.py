"""
What the dashboard reads. Every function here queries the small aggregation
tables only — never Job or JobSkill — so page cost does not grow with the
number of jobs.

`days` limits a breakdown to jobs posted in the last N days; None means all time.
"""
from datetime import date, timedelta

from django.db.models import Max, Sum
from django.db.models.functions import TruncWeek

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


def weekly_skill_trend(skill_ids, weeks: int = 12) -> tuple[list[date], dict[int, list[int]]]:
    """
    Jobs per week for each skill over the `weeks` weeks up to the latest
    posting day in the data (not today, so a pause in ingestion doesn't
    leave the chart empty). Returns (week start dates, {skill_id: counts}).
    """
    latest = DailySkillCount.objects.aggregate(latest=Max('day'))['latest']
    if latest is None:
        return [], {pk: [] for pk in skill_ids}
    last_week = latest - timedelta(days=latest.weekday())
    week_starts = [last_week - timedelta(weeks=n) for n in range(weeks - 1, -1, -1)]

    series = {pk: [0] * weeks for pk in skill_ids}
    rows = (
        DailySkillCount.objects
        .filter(skill_id__in=skill_ids, day__gte=week_starts[0], day__lte=latest)
        .annotate(week=TruncWeek('day'))
        .values('skill_id', 'week')
        .annotate(jobs=Sum('job_count'))
    )
    index = {w: i for i, w in enumerate(week_starts)}
    for r in rows:
        week = r['week'].date() if hasattr(r['week'], 'date') else r['week']
        series[r['skill_id']][index[week]] = r['jobs']
    return week_starts, series


def new_jobs(days: int = 7) -> int:
    """Jobs posted in the last `days` days, all sources."""
    return _since(DailySourceCount.objects, days).aggregate(n=Sum('job_count'))['n'] or 0


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
