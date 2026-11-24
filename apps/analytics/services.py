"""
Rebuild the dashboard aggregation tables from Job / JobSkill.

Safe to run twice: each run recomputes every number from the source tables and
replaces the old rows inside one transaction. Nothing is ever incremented, so
running it again gives the same rows, not double counts. Readers see the old
rows until the transaction commits, so the dashboard is never empty mid-refresh.
"""
import logging

from django.db import transaction
from django.db.models import Case, CharField, Count, F, Q, Value, When
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from apps.analytics.models import (
    HeadlineTotals,
    DailySeniorityCount,
    DailySkillCount,
    DailySourceCount,
    DailyWorkModeCount,
)
from apps.intelligence.models import Job, JobSkill
from apps.intelligence.schemas import RemoteStatus, Seniority

logger = logging.getLogger(__name__)

UNKNOWN = 'unknown'
_LEVELS = [s.value for s in Seniority if s is not Seniority.NOT_STATED]
_WORK_MODES = [s.value for s in RemoteStatus if s is not RemoteStatus.NOT_STATED]


def _posted_day(prefix: str = ''):
    """Day the job was posted; the day we first saw it when the source gave no date."""
    return Coalesce(F(f'{prefix}published_date'), TruncDate(f'{prefix}created_at'))


def _jobs():
    """Jobs counted on the dashboard: everything except known duplicates."""
    return Job.objects.filter(canonical__isnull=True).annotate(day=_posted_day())


def _seniority_rows() -> list[DailySeniorityCount]:
    level = Case(When(seniority__in=_LEVELS, then=F('seniority')),
                 default=Value(UNKNOWN), output_field=CharField())
    qs = _jobs().annotate(level=level).values('day', 'level').annotate(n=Count('id'))
    return [DailySeniorityCount(day=r['day'], seniority=r['level'], job_count=r['n']) for r in qs]


def _work_mode_rows() -> list[DailyWorkModeCount]:
    # The LLM's reading of the description wins; a "Remote" location is the fallback.
    mode = Case(
        When(extracted_remote_status__in=_WORK_MODES, then=F('extracted_remote_status')),
        When(location__is_remote=True, then=Value(RemoteStatus.REMOTE.value)),
        default=Value(UNKNOWN),
        output_field=CharField(),
    )
    qs = _jobs().annotate(mode=mode).values('day', 'mode').annotate(n=Count('id'))
    return [DailyWorkModeCount(day=r['day'], work_mode=r['mode'], job_count=r['n']) for r in qs]


def _source_rows() -> list[DailySourceCount]:
    qs = _jobs().values('day', 'source').annotate(n=Count('id'))
    return [DailySourceCount(day=r['day'], source=r['source'], job_count=r['n']) for r in qs]


def _skill_rows() -> list[DailySkillCount]:
    qs = (
        JobSkill.objects
        .filter(job__canonical__isnull=True)
        .annotate(day=_posted_day('job__'))
        .values('day', 'skill_id')
        .annotate(n=Count('id'), required=Count('id', filter=Q(is_required=True)))
    )
    return [
        DailySkillCount(day=r['day'], skill_id=r['skill_id'], job_count=r['n'], required_count=r['required'])
        for r in qs
    ]


def _headline() -> dict:
    totals = Job.objects.filter(canonical__isnull=True).aggregate(
        jobs_tracked=Count('id'),
        companies=Count('company', distinct=True),
    )
    totals['distinct_skills'] = (
        JobSkill.objects.filter(job__canonical__isnull=True).values('skill').distinct().count()
    )
    return totals


def refresh_aggregates() -> dict:
    """Recompute every dashboard table and swap the new rows in atomically."""
    started = timezone.now()
    tables = {
        DailySkillCount: _skill_rows(),
        DailySeniorityCount: _seniority_rows(),
        DailyWorkModeCount: _work_mode_rows(),
        DailySourceCount: _source_rows(),
    }
    headline = _headline()

    with transaction.atomic():
        for model, rows in tables.items():
            model.objects.all().delete()
            model.objects.bulk_create(rows, batch_size=1000)
        HeadlineTotals.objects.update_or_create(pk=1, defaults={**headline, 'refreshed_at': timezone.now()})

    counts = {model._meta.model_name: len(rows) for model, rows in tables.items()}
    counts.update(headline)
    counts['seconds'] = round((timezone.now() - started).total_seconds(), 2)
    logger.info('refresh_aggregates: %s', counts)
    return counts
