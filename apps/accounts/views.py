"""
Plain upload → matches pages. Styling comes later; these only need to work.

The CV file itself is never stored — only the extracted text.
"""
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.accounts.extraction import extract_text
from apps.accounts.forms import CVUploadWithFiltersForm, MatchFilterForm
from apps.accounts.models import CV, CVProfile
from apps.accounts.services import ProfileBuildError, build_profile
from apps.intelligence.matching import match_profile

MATCH_LIMIT = 20

NO_SKILLS_MESSAGE = (
    "We read your CV but couldn't find any skills we recognise, so we can't match it to jobs. "
    "Check that the CV lists your skills, tools and technologies as text, then upload it again."
)
PROFILE_FAILED_MESSAGE = (
    "We read your CV but couldn't analyse it just now. Please try again in a minute."
)


def _filter_query(remote_only: bool, countries: list[str]) -> str:
    params = {}
    if remote_only:
        params['remote_only'] = 'on'
    if countries:
        params['countries'] = ','.join(countries)
    return f'?{urlencode(params)}' if params else ''


def _filters(request):
    form = MatchFilterForm(request.GET or None)
    if form.is_bound and form.is_valid():
        return form, form.cleaned_data['remote_only'], form.cleaned_data['countries']
    return form, False, []


@login_required
def upload(request):
    if request.method == 'POST':
        form = CVUploadWithFiltersForm(request.POST, request.FILES)
        if form.is_valid():
            upload_file = form.cleaned_data['file']
            result = extract_text(upload_file)
            if not result.ok:
                form.add_error('file', result.error)
            else:
                cv = CV.objects.create(
                    owner=request.user,
                    original_filename=upload_file.name[:255],
                    extracted_text=result.text,
                    status=CV.Status.READY,
                )
                try:
                    build_profile(cv.pk)
                except ProfileBuildError:
                    cv.status = CV.Status.FAILED
                    cv.failure_reason = 'profile extraction failed'
                    cv.save(update_fields=['status', 'failure_reason'])
                    form.add_error(None, PROFILE_FAILED_MESSAGE)
                else:
                    query = _filter_query(form.cleaned_data['remote_only'], form.cleaned_data['countries'])
                    return redirect(reverse('accounts:matches', args=[cv.pk]) + query)
    else:
        form = CVUploadWithFiltersForm()

    previous = CV.objects.filter(owner=request.user, status=CV.Status.READY)[:10]
    return render(request, 'accounts/upload.html', {'form': form, 'previous': previous})


def _own_profile(request, cv_id):
    cv = get_object_or_404(CV, pk=cv_id, owner=request.user)
    try:
        return cv, cv.profile
    except CVProfile.DoesNotExist:
        return cv, None


@login_required
def matches(request, cv_id):
    cv, profile = _own_profile(request, cv_id)
    filter_form, remote_only, countries = _filters(request)

    message, results, skills = '', [], []
    if profile is None:
        message = PROFILE_FAILED_MESSAGE
    else:
        skills = sorted(profile.skills.values_list('name', flat=True))
        if not skills:
            message = NO_SKILLS_MESSAGE
        else:
            results = match_profile(profile, remote_only=remote_only, countries=countries, limit=MATCH_LIMIT)
            if not results:
                message = 'No jobs pass your filters. Try removing a filter.'

    return render(request, 'accounts/matches.html', {
        'cv': cv,
        'profile': profile,
        'skills': skills,
        'results': results,
        'message': message,
        'filter_form': filter_form,
        'filter_query': _filter_query(remote_only, countries),
    })


@login_required
def match_detail(request, cv_id, job_id):
    from apps.intelligence.explain import explain_match_with_source

    cv, profile = _own_profile(request, cv_id)
    _, remote_only, countries = _filters(request)
    if profile is None:
        raise Http404('This CV has no profile.')

    found = match_profile(profile, remote_only=remote_only, countries=countries, job_ids=[job_id], limit=1)
    if not found:
        raise Http404('This job is not a match for this CV with the current filters.')
    result = found[0]

    # Generated on demand, only for the match the user opened
    explanation, source = explain_match_with_source(result)

    rows = [
        (name, result.components[name], result.weights[name], result.contributions[name])
        for name in result.components
    ]
    return render(request, 'accounts/match_detail.html', {
        'cv': cv,
        'profile': profile,
        'r': result,
        'rows': rows,
        'explanation': explanation,
        'explanation_source': source,
        'filter_query': _filter_query(remote_only, countries),
    })
