"""
Query rules shared by the dashboard aggregates and the job list, so a filter
on the list always agrees with the number on the dashboard.
"""
from django.db.models import Case, CharField, F, Value, When

from apps.intelligence.schemas import RemoteStatus, Seniority

UNKNOWN = 'unknown'

LEVELS = [s.value for s in Seniority if s is not Seniority.NOT_STATED]   # junior … director
WORK_MODES = [s.value for s in RemoteStatus if s is not RemoteStatus.NOT_STATED]

SENIORITY_LABELS = {
    'junior': 'Junior', 'mid': 'Mid', 'senior': 'Senior',
    'principal': 'Principal', 'director': 'Director', UNKNOWN: 'Not stated',
}
WORK_MODE_LABELS = {'remote': 'Remote', 'hybrid': 'Hybrid', 'on_site': 'On-site', UNKNOWN: 'Not stated'}


def seniority_expression():
    """Job.seniority, with blank and 'not_stated' folded into 'unknown'."""
    return Case(When(seniority__in=LEVELS, then=F('seniority')),
                default=Value(UNKNOWN), output_field=CharField())


def work_mode_expression():
    """The LLM's reading of the description first; a 'Remote' location as the fallback."""
    return Case(
        When(extracted_remote_status__in=WORK_MODES, then=F('extracted_remote_status')),
        When(location__is_remote=True, then=Value(RemoteStatus.REMOTE.value)),
        default=Value(UNKNOWN),
        output_field=CharField(),
    )
