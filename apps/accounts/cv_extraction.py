"""
CV profile extraction service.

Reuses LLMClient, resolve_skill, and the job embedding helper (_embed_batch,
EMBED_MODEL) — no new client wrappers. The only new thing is the CV prompt
and CVExtractionResult schema.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from apps.intelligence.llm.client import LLMClient, LLMMessage
from apps.intelligence.schemas import CVExtractionResult
from apps.intelligence.services import resolve_skill
from apps.intelligence.tasks import EMBED_MODEL, _embed_batch

logger = logging.getLogger(__name__)

PROMPT_VERSION = 'extract_cv_v2'
_PROMPT_PATH = Path(__file__).parent.parent / 'intelligence' / 'prompts' / f'{PROMPT_VERSION}.md'
MAX_CV_CHARS = 4000


def _render_cv_prompt(cv_text: str) -> str:
    return _PROMPT_PATH.read_text().replace('{cv_text}', cv_text[:MAX_CV_CHARS])


def _normalise(text: str) -> str:
    return ' '.join(text.lower().split())


def skills_in_text(skills: list[str], cv_text: str) -> tuple[list[str], list[str]]:
    """
    Split extracted skills into (kept, dropped): a skill is kept only if it
    appears as a whole word or phrase in the CV text the model was shown.
    The model has added skills from the prompt's own examples ("Agile",
    "Scrum") to CVs that never mention them; this stops that reaching matching.
    """
    text = _normalise(cv_text[:MAX_CV_CHARS])
    kept, dropped = [], []
    for skill in skills:
        name = _normalise(skill)
        if name and re.search(rf'(?<!\w){re.escape(name)}(?!\w)', text):
            kept.append(skill)
        else:
            dropped.append(skill)
    return kept, dropped


def extract_cv_profile(cv) -> bool:
    """
    Run LLM extraction on cv.extracted_text, resolve skills, build embedding,
    and write a CVProfile record.

    Returns True on success, False on failure.
    Never raises — logs errors and returns False.
    """
    from apps.accounts.models import CVProfile

    if not cv.extracted_text.strip():
        logger.warning('extract_cv_profile: cv=%s has no extracted text', cv.pk)
        return False

    client = LLMClient()
    messages = [
        LLMMessage(role='system', content='You are a CV data extractor.'),
        LLMMessage(role='user', content=_render_cv_prompt(cv.extracted_text)),
    ]

    sr = client.extract_structured(messages, CVExtractionResult)

    if sr.result is None:
        logger.error('extract_cv_profile: cv=%s LLM failed — %s', cv.pk, sr.failure_reason)
        return False

    result = sr.result

    skills, invented = skills_in_text(result.skills, cv.extracted_text)
    if invented:
        logger.warning('extract_cv_profile: cv=%s dropped %d skill(s) not in the CV text: %s',
                       cv.pk, len(invented), invented)

    # Resolve skills through the same canonical table jobs use
    resolved_skills = []
    for raw in skills:
        try:
            resolved_skills.append(resolve_skill(raw))
        except Exception as exc:
            logger.warning('extract_cv_profile: cv=%s skill resolve failed %r — %s', cv.pk, raw, exc)

    # Build or update CVProfile
    profile, _ = CVProfile.objects.get_or_create(cv=cv)
    profile.seniority = result.seniority.value if result.seniority else ''
    profile.years_experience = (
        result.years_experience
        if isinstance(result.years_experience, int)
        else None
    )
    profile.save(update_fields=['seniority', 'years_experience', 'updated_at'])

    profile.skills.set(resolved_skills)

    # Embed with the same text strategy, model and endpoint as jobs
    try:
        vector = _embed_batch([profile.embed_text()])[0]
        profile.embedding = vector
        profile.embedding_model = EMBED_MODEL
        profile.save(update_fields=['embedding', 'embedding_model', 'updated_at'])
    except Exception as exc:
        logger.error('extract_cv_profile: cv=%s embed failed — %s', cv.pk, exc)
        # Embedding failure is non-fatal — profile is still usable for skill matching

    return True
