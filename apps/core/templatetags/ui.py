from django import template

from apps.intelligence.queries import SENIORITY_LABELS, UNKNOWN, WORK_MODE_LABELS

register = template.Library()


@register.filter
def work_mode_label(value: str) -> str:
    return WORK_MODE_LABELS.get(value or UNKNOWN, value)


@register.filter
def seniority_label(value: str) -> str:
    return SENIORITY_LABELS.get(value or UNKNOWN, SENIORITY_LABELS[UNKNOWN])


@register.filter
def percent(value: float) -> int:
    """0.734 -> 73"""
    return round((value or 0) * 100)
