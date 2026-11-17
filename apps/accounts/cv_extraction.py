"""
CV profile extraction service.

Reuses LLMClient, resolve_skill, and the job embedding helper (_embed_batch,
EMBED_MODEL) — no new client wrappers. The only new thing is the CV prompt
and CVExtractionResult schema.
"""
from __future__ import annotations

import logging
from pathlib import Path

from apps.intelligence.llm.client import LLMClient, LLMMessage
from apps.intelligence.schemas import CVExtractionResult
from apps.intelligence.services import resolve_skill
from apps.intelligence.tasks import EMBED_MODEL, _embed_batch

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / 'intelligence' / 'prompts' / 'extract_cv_v1.md'


def _render_cv_prompt(cv_text: str) -> str:
    return _PROMPT_PATH.read_text().replace('{cv_text}', cv_text[:4000])


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

    # Resolve skills through the same canonical table jobs use
    resolved_skills = []
    for raw in result.skills:
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
