from django.core.paginator import Paginator
from django.db.models import Exists, F, OuterRef, Prefetch, Q
from django.shortcuts import render
from django.views.decorators.vary import vary_on_headers

from apps.core.htmx import is_htmx
from apps.intelligence.forms import JobFilterForm
from apps.intelligence.models import Job, JobSkill
from apps.intelligence.queries import LEVELS, UNKNOWN, work_mode_expression

PAGE_SIZE = 20


def filtered_jobs(q: str = '', seniority: str = '', work_mode: str = '', source: str = ''):
    """Jobs for the list page, duplicates hidden, newest first, with everything the row shows."""
    jobs = (
        Job.objects
        .filter(canonical__isnull=True)
        .annotate(work_mode=work_mode_expression())
        .select_related('company', 'location')
        .prefetch_related(Prefetch(
            'jobskill_set',
            queryset=JobSkill.objects.select_related('skill').order_by('-is_required', 'skill__name'),
        ))
        .order_by(F('published_date').desc(nulls_last=True), '-pk')
    )
    if q:
        has_skill = JobSkill.objects.filter(job=OuterRef('pk'), skill__name__icontains=q)
        jobs = jobs.filter(Q(title__icontains=q) | Q(company__name__icontains=q) | Exists(has_skill))
    if seniority == UNKNOWN:
        jobs = jobs.exclude(seniority__in=LEVELS)
    elif seniority:
        jobs = jobs.filter(seniority=seniority)
    if work_mode:
        jobs = jobs.filter(work_mode=work_mode)
    if source:
        jobs = jobs.filter(source=source)
    return jobs


@vary_on_headers('HX-Request')
def job_list(request):
    form = JobFilterForm(request.GET or None)
    filters = form.cleaned_data if form.is_valid() else {}
    page = Paginator(filtered_jobs(**filters), PAGE_SIZE).get_page(request.GET.get('page'))

    context = {'form': form, 'page': page, 'filtered': any(filters.values())}
    template = 'intelligence/_job_results.html' if is_htmx(request) else 'intelligence/job_list.html'
    return render(request, template, context)
