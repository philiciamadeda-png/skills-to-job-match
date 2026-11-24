"""
The dashboard: headline numbers and four charts, each answering one question.
Reads only the aggregation tables (apps.analytics.selectors), never Job.
"""
from django.shortcuts import render

from apps.analytics import selectors
from apps.intelligence.queries import LEVELS, SENIORITY_LABELS, UNKNOWN, WORK_MODE_LABELS

TOP_SKILLS = 10
TREND_SKILLS = 5
TREND_WEEKS = 12


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def _top_skills_answer(top, jobs_tracked):
    if not top:
        return ''
    lead = top[0]
    return f"{lead['skill']} is asked for most: {lead['jobs']} of {jobs_tracked} jobs ({_pct(lead['jobs'], jobs_tracked)}%)."


def _trend_answer(names, series):
    """Compare the last 4 weeks with the 4 before for each skill; name the biggest move."""
    moves = []
    for pk, counts in series.items():
        recent, before = sum(counts[-4:]), sum(counts[-8:-4])
        if recent != before:
            moves.append((recent - before, names[pk], recent, before))
    if not moves:
        return 'No change between the last four weeks and the four before.'
    delta, name, recent, before = max(moves, key=lambda m: abs(m[0]))
    direction = 'Rising' if delta > 0 else 'Falling'
    return f'{direction} most: {name}, {recent} jobs in the last 4 weeks against {before} in the 4 before.'


def _seniority_answer(by_level):
    stated = {k: v for k, v in by_level.items() if k != UNKNOWN}
    if not stated:
        return 'None of the jobs state a level yet.'
    level, n = max(stated.items(), key=lambda kv: kv[1])
    answer = f'Of jobs that state a level, most are {SENIORITY_LABELS[level].lower()} ({n} of {sum(stated.values())}).'
    if by_level.get(UNKNOWN):
        answer += f' {by_level[UNKNOWN]} don’t say.'
    return answer


def _work_mode_answer(by_mode):
    total = sum(by_mode.values())
    if not total:
        return ''
    remote = by_mode.get('remote', 0)
    return f'{remote} of {total} jobs ({_pct(remote, total)}%) can be done fully remotely.'


def dashboard(request):
    totals = selectors.headline()
    if totals is None:
        return render(request, 'analytics/dashboard.html', {'totals': None})

    top = selectors.top_skills(limit=TOP_SKILLS)
    trend_top = top[:TREND_SKILLS]
    names = {r['skill_id']: r['skill'] for r in trend_top}
    weeks, series = selectors.weekly_skill_trend(list(names), weeks=TREND_WEEKS)
    by_level = selectors.jobs_by_seniority()
    by_mode = selectors.jobs_by_work_mode()

    level_order = LEVELS + [UNKNOWN]
    mode_order = list(WORK_MODE_LABELS)
    charts = {
        'topSkills': {
            'labels': [r['skill'] for r in top],
            'values': [r['jobs'] for r in top],
        },
        'trend': {
            'labels': [w.strftime('%d %b') for w in weeks],
            'series': [{'label': names[pk], 'values': series[pk]} for pk in names],
        },
        'seniority': {
            'labels': [SENIORITY_LABELS[k] for k in level_order],
            'values': [by_level.get(k, 0) for k in level_order],
        },
        'workMode': {
            'labels': [WORK_MODE_LABELS[k] for k in mode_order],
            'values': [by_mode.get(k, 0) for k in mode_order],
        },
    }
    return render(request, 'analytics/dashboard.html', {
        'totals': totals,
        'new_this_week': selectors.new_jobs(days=7),
        'charts': charts,
        'answers': {
            'top_skills': _top_skills_answer(top, totals.jobs_tracked),
            'trend': _trend_answer(names, series) if weeks else '',
            'seniority': _seniority_answer(by_level),
            'work_mode': _work_mode_answer(by_mode),
        },
        'trend_note': (
            f"Jobs posted per week for the top {len(names)} skills, weeks starting "
            f"{weeks[0]:%d %b} to {weeks[-1]:%d %b %Y}." if weeks else ''
        ),
    })
