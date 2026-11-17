"""
Match explanation service.

Turns a computed MatchResult into a 2–3 sentence plain-English explanation.

Only computed facts are sent to the LLM: job title, both seniority levels,
skill names and scores. The CV text and the job description are never sent.

The LLM output is checked before it is returned (sentence count, length, no
preamble, names a missing skill when there is one). If the call fails or the
output fails the checks, a deterministic template built from the same facts is
returned instead, so callers always get something honest to show.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from apps.intelligence.llm.client import LLMClient, LLMMessage
from apps.intelligence.matching import MatchResult, _SENIORITY_RANK

logger = logging.getLogger(__name__)

PROMPT_VERSION = 'explain_match_v2'
_PROMPT = (Path(__file__).parent / 'prompts' / f'{PROMPT_VERSION}.md').read_text()

MAX_SKILLS_NAMED = 3      # missing skills named before '+N more'
MAX_MATCHED_NAMED = 6     # matched skills are listed in full up to this many
MAX_WORDS = 75            # prompt asks for < 60; small slack before rejecting

_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')
_UNLISTED = re.compile(r'not listed|another skill|other skills? you')
_PREAMBLE = re.compile(r'^(here(\'s| is)|sure|explanation:|certainly|start with|your first sentence)', re.IGNORECASE)
# Skills that appear only in the prompt's examples — mentioning one not in the facts means copying
_EXAMPLE_SKILLS = ('xero', 'ifrs', 'sage', 'power bi', 'triage', 'rostering', 'budgeting', 'cqc', 'vat')
_FLATTERY = re.compile(r'\b(strong|excellent|perfect|great|ideal|fit|good match)\b', re.IGNORECASE)
_SCORE = re.compile(r'\b0\.\d+\b|\bscore\b', re.IGNORECASE)

# Direction checks for a level gap: (must match, must not match)
_ROLE_ABOVE = (re.compile(r'above your|more senior than you|you are \w+ levels? below'),
               re.compile(r'overqualified|you are \w+ levels? above|below your'))
_ROLE_BELOW = (re.compile(r'below your|more junior than you|overqualified|you are \w+ levels? above'),
               re.compile(r'underqualified|less qualified|you are \w+ levels? below|above your'))


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

def _seniority_note(candidate: str, job: str, gap: int) -> str:
    if candidate not in _SENIORITY_RANK or job not in _SENIORITY_RANK:
        return 'unknown'
    if gap == 0:
        return 'same level'
    n = abs(gap)
    levels = 'level' if n == 1 else 'levels'
    direction = 'below' if gap > 0 else 'above'
    return f'the role is {n} {levels} {direction} your level'


def _lead(note: str, gap: int, n_have: int, n_req: int) -> str:
    """What the explanation should open with — the point that matters most."""
    if note not in ('same level', 'unknown') and abs(gap) >= 2:
        return 'the level difference'
    if n_req and n_have * 2 < n_req:
        return 'the missing skills'
    return 'the skills you have'


def build_facts(result: MatchResult) -> dict:
    """The complete set of facts the explanation may use. Nothing else is sent."""
    candidate = result.profile_seniority or ''
    job = result.job.seniority or ''
    matched, missing = result.matched_required, result.missing_required
    note = _seniority_note(candidate, job, result.seniority_gap)
    return {
        'lead': _lead(note, result.seniority_gap, len(matched), len(matched) + len(missing)),
        'job_title': result.job.title,
        'candidate_seniority': candidate or 'not stated',
        'job_seniority': job or 'not stated',
        'seniority_note': note,
        'seniority_gap': result.seniority_gap,
        'matched_required_list': list(matched),
        'missing_required_list': list(missing),
        'matched_nice_list': list(result.matched_nice),
        'matched_count': len(matched),
        'missing_count': len(missing),
        'required_count': len(matched) + len(missing),
        'total_score': round(result.total_score, 2),
        'required_skill_score': round(result.required_skill_score, 2),
    }


def _names(items: list[str], limit: int = MAX_SKILLS_NAMED) -> str:
    if not items:
        return 'none'
    shown = ', '.join(items[:limit])
    extra = len(items) - limit
    return f'{shown} (+{extra} more)' if extra > 0 else shown


def render_prompt(facts: dict) -> str:
    return _PROMPT.format(
        job_title=facts['job_title'],
        candidate_seniority=facts['candidate_seniority'],
        job_seniority=facts['job_seniority'],
        seniority_note=facts['seniority_note'],
        matched_count=facts['matched_count'],
        missing_count=facts['missing_count'],
        required_count=facts['required_count'],
        matched_required=_names(facts['matched_required_list'], MAX_MATCHED_NAMED),
        missing_required=(
            _names(facts['missing_required_list']) if facts['missing_count'] or not facts['required_count']
            else 'none — the candidate has every required skill'
        ),
        matched_nice=_names(facts['matched_nice_list'], MAX_MATCHED_NAMED),
        lead=facts['lead'],
    )


# ---------------------------------------------------------------------------
# Output checks and fallback
# ---------------------------------------------------------------------------

def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text.strip()) if s]


def validate_explanation(text: str, facts: dict) -> str | None:
    """Return the cleaned explanation, or None if it breaks the output rules."""
    text = ' '.join(text.strip().strip('"\'').split())
    if not text or _PREAMBLE.match(text):
        return None
    if not 2 <= len(_sentences(text)) <= 3:
        return None
    if len(text.split()) > MAX_WORDS:
        return None
    if _FLATTERY.search(text) or _SCORE.search(text) or _UNLISTED.search(text.lower()):
        return None
    lower = text.lower()
    allowed = {s.lower() for s in facts['matched_required_list'] + facts['missing_required_list'] + facts['matched_nice_list']}
    if any(re.search(rf'\b{re.escape(e)}\b', lower) and e not in allowed for e in _EXAMPLE_SKILLS):
        return None   # copied a skill from the prompt examples
    missing = facts['missing_required_list']
    if missing and not any(m.lower() in lower for m in missing):
        return None   # silent about the skill gap — not honest enough to show
    if not missing and re.search(r'unfortunately|missing (is |are )?none|none of the required skills|at risk', lower):
        return None   # frames "nothing missing" as a gap
    if facts['seniority_note'] not in ('same level', 'unknown'):
        must, must_not = _ROLE_ABOVE if facts['seniority_gap'] < 0 else _ROLE_BELOW
        if not must.search(lower) or must_not.search(lower):
            return None   # silent about the level gap, or states it the wrong way round
    return text


def fallback_explanation(facts: dict) -> str:
    """Deterministic 2–3 sentence explanation from the same facts."""
    title = facts['job_title']
    n_have, n_req, n_miss = facts['matched_count'], facts['required_count'], facts['missing_count']
    have, missing = facts['matched_required_list'], facts['missing_required_list']

    # Skills: lead with the strength or the gap, whichever dominates
    if n_req == 0:
        skills = [f'This {title} role does not list required skills, so the match rests on level and overall similarity.']
    elif n_miss == 0:
        skills = [f'You have all {n_req} required skills for this {title} role: {_names(have, MAX_MATCHED_NAMED)}.']
    elif n_have * 2 >= n_req:
        skills = [f'You have {n_have} of the {n_req} required skills for this {title} role, including {_names(have)}.',
                  f'Missing: {_names(missing)}.']
    else:
        skills = [f'You are missing {n_miss} of the {n_req} required skills for this {title} role: {_names(missing)}.']
        if have:
            skills.append(f'You do have {_names(have)}.')

    note = facts['seniority_note']
    if note == 'same level':
        level = f'The level ({facts["job_seniority"]}) matches yours.'
    elif note == 'unknown':
        level = 'Seniority could not be compared because a level is not stated.'
    else:
        level = f'{note[0].upper()}{note[1:]} ({facts["job_seniority"]} vs {facts["candidate_seniority"]}).'

    return ' '.join(skills + [level])


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def explain_match_with_source(
    result: MatchResult,
    client: LLMClient | None = None,
) -> tuple[str, str]:
    """
    Return (explanation, source) where source is:
      'llm'                — model output that passed validation
      'template:rejected'  — model output failed validation, template used
      'template:error'     — LLM call failed, template used
    """
    facts = build_facts(result)
    llm = client or LLMClient()
    try:
        resp = llm.chat([LLMMessage(role='user', content=render_prompt(facts))])
    except Exception as exc:
        logger.error('explain_match: LLM call failed job=%s — %s', result.job.pk, exc)
        return fallback_explanation(facts), 'template:error'

    text = validate_explanation(resp.content, facts)
    if text is None:
        logger.warning('explain_match: output rejected job=%s raw=%r', result.job.pk, resp.content[:200])
        return fallback_explanation(facts), 'template:rejected'
    return text, 'llm'


def explain_match(
    result: MatchResult,
    client: LLMClient | None = None,
    *,
    fallback: bool = True,
) -> str:
    """
    Return a 2–3 sentence plain-English explanation of a MatchResult.

    Sends only computed facts to the LLM — no CV text, no job description.
    On LLM failure or invalid output, returns the template explanation
    (or '' if fallback=False).
    """
    text, source = explain_match_with_source(result, client)
    if source != 'llm' and not fallback:
        return ''
    return text
