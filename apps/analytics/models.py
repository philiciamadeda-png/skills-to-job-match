"""
Pre-computed dashboard numbers.

The dashboard reads only from these tables, never from Job / JobSkill. They are
rebuilt by apps.analytics.services.refresh_aggregates() after each transform
and extraction run.

Every daily table is keyed by (day, <dimension>) with a unique constraint, so
a row can only exist once per day and dimension — a refresh replaces rows, it
never adds to them.

`day` is the day the job was posted: Job.published_date, or the day we first
saw the job when the source gave no date. Duplicates (Job.canonical set) are
left out everywhere so a job listed on two boards is counted once.
"""
from django.db import models

from apps.intelligence.models import Skill


class DailyCount(models.Model):
    day = models.DateField(db_index=True)
    job_count = models.PositiveIntegerField()

    class Meta:
        abstract = True


class DailySkillCount(DailyCount):
    """Jobs posted on `day` that ask for `skill` (required or nice-to-have)."""
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name='daily_counts')
    required_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['day', 'skill'], name='uniq_skill_daily_count'),
        ]
        indexes = [models.Index(fields=['skill', 'day'])]


class DailySeniorityCount(DailyCount):
    seniority = models.CharField(max_length=20)   # junior … director, or 'unknown'

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['day', 'seniority'], name='uniq_seniority_daily_count'),
        ]


class DailyWorkModeCount(DailyCount):
    class WorkMode(models.TextChoices):
        REMOTE = 'remote', 'Remote'
        HYBRID = 'hybrid', 'Hybrid'
        ON_SITE = 'on_site', 'On-site'
        UNKNOWN = 'unknown', 'Not stated'

    work_mode = models.CharField(max_length=20, choices=WorkMode.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['day', 'work_mode'], name='uniq_work_mode_daily_count'),
        ]


class DailySourceCount(DailyCount):
    """New jobs per day per source (remotive, arbeitnow, …)."""
    source = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['day', 'source'], name='uniq_source_daily_count'),
        ]


class HeadlineTotals(models.Model):
    """Single row (pk=1) with the dashboard's headline numbers."""
    jobs_tracked = models.PositiveIntegerField(default=0)
    companies = models.PositiveIntegerField(default=0)
    distinct_skills = models.PositiveIntegerField(default=0)
    refreshed_at = models.DateTimeField()

    class Meta:
        verbose_name_plural = 'headline totals'

    def __str__(self):
        return f'{self.jobs_tracked} jobs, {self.companies} companies, {self.distinct_skills} skills'
