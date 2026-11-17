"""
Public entry points for the accounts app.

Thin wrappers only — the extraction logic lives in cv_extraction.py.
"""
from __future__ import annotations

from apps.accounts.cv_extraction import extract_cv_profile
from apps.accounts.models import CV, CVProfile


class ProfileBuildError(Exception):
    """Raised when a CV profile cannot be built."""


def build_profile(cv_id: int) -> CVProfile:
    """
    Build (or rebuild) the structured profile for a CV and return it.

    Raises CV.DoesNotExist if the id is unknown, ProfileBuildError if the
    CV has no text or the LLM extraction fails.
    """
    cv = CV.objects.get(pk=cv_id)
    if not extract_cv_profile(cv):
        raise ProfileBuildError(
            f'Could not build profile for CV {cv_id} — empty text or LLM failure (see logs).'
        )
    return CVProfile.objects.prefetch_related('skills').get(cv=cv)
