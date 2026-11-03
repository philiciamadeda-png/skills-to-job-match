"""
Match explanation service.

Generates a short plain-English explanation of a MatchResult using the LLM.
Only structured facts are sent — no raw CV text or job description.
"""
from __future__ import annotations

import logging
from pathlib import Path

from apps.intelligence.llm.client import LLMClient, LLMMessage
from apps.intelligence.matching import MatchResult

logger = logging.getLogger(__name__)

_PROMPT = (Path(__file__).parent / 'prompts' / 'explain_match_v1.md').read_text()


def explain_match(result: MatchResult, client: LLMClient | None = None) -> str:
    """
    Return a 2–3 sentence plain-English explanation of a MatchResult.

    Sends only computed facts to the LLM — no CV text, no job description.
    Returns an empty string on failure (caller decides whether to show a fallback).
    """
    missing = result.missing_required[:3]   # cap at 3 for the prompt
    nice    = result.matched_nice[:3]

    prompt = _PROMPT.format(
        job_title=result.job.title,
        candidate_seniority=result.job.seniority or 'not stated',
        job_seniority=result.job.seniority or 'not stated',
        seniority_gap=result.seniority_gap,
        matched_required=', '.join(result.matched_required) or 'none',
        missing_required=', '.join(missing) or 'none',
        matched_nice=', '.join(nice) or 'none',
        total_score=round(result.total_score, 2),
        required_skill_score=round(result.required_skill_score, 2),
    )

    llm = client or LLMClient()
    try:
        resp = llm.chat([LLMMessage(role='user', content=prompt)])
        return resp.content.strip()
    except Exception as exc:
        logger.error('explain_match: failed for job=%s — %s', result.job.pk, exc)
        return ''
