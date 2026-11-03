"""
Job matching service.

Produces a ranked list of jobs for a CVProfile with a composite score and
per-component breakdown so results are explainable.

Scoring components
------------------
Component               Weight   What it measures
required_skill_score    0.40     Proportion of job's required skills the profile has
semantic_score          0.25     Cosine similarity of profile and job embeddings
seniority_score         0.20     Level fit — penalises gap in both directions
nice_to_have_score      0.10     Bonus for desirable skills the profile has
recency_score           0.05     Slight preference for recently posted roles

Hard filters (applied before scoring — not a preference, a requirement)
---------------------------------------------------------------------------
- extraction_status = 'success'          (job must have been processed)
- embedding IS NOT NULL                  (job must be embeddable)
- remote_filter: if profile requests remote-only, exclude on_site jobs
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from apps.intelligence.models import Job

# ---------------------------------------------------------------------------
# Seniority ordering — used for gap calculation
# ---------------------------------------------------------------------------
_SENIORITY_RANK = {
    'junior': 1,
    'mid': 2,
    'senior': 3,
    'principal': 4,
    'director': 5,
}

# ---------------------------------------------------------------------------
# Weights — must sum to 1.0
# ---------------------------------------------------------------------------
W_REQUIRED   = 0.40
W_SEMANTIC   = 0.25
W_SENIORITY  = 0.20
W_NICE       = 0.10
W_RECENCY    = 0.05

# Recency: full score within this many days, decays to 0 at RECENCY_FLOOR
RECENCY_HALF_LIFE = 30   # days
RECENCY_FLOOR     = 180  # days — older than this scores 0


@dataclass
class MatchResult:
    job: Job
    total_score: float                    # 0.0 – 1.0
    required_skill_score: float           # proportion of required skills matched
    semantic_score: float                 # cosine similarity
    seniority_score: float                # 0.0 – 1.0
    nice_to_have_score: float             # proportion of nice-to-have matched
    recency_score: float                  # 0.0 – 1.0
    matched_required: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    matched_nice: list[str] = field(default_factory=list)
    seniority_gap: int = 0                # signed: positive = overqualified


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _recency(published_date: Optional[date]) -> float:
    if not published_date:
        return 0.5   # unknown — neutral
    age_days = (date.today() - published_date).days
    if age_days <= 0:
        return 1.0
    if age_days >= RECENCY_FLOOR:
        return 0.0
    # Exponential decay
    return math.exp(-age_days / RECENCY_HALF_LIFE)


def _seniority_fit(profile_level: str, job_level: str) -> tuple[float, int]:
    """
    Returns (score 0–1, signed gap).
    Gap > 0 means profile is more senior than job (overqualified).
    Gap < 0 means profile is less senior than job (underqualified).
    Penalises both directions — a gap of 1 gives 0.6, gap of 2 gives 0.2, gap ≥ 3 gives 0.
    """
    pr = _SENIORITY_RANK.get(profile_level, 0)
    jr = _SENIORITY_RANK.get(job_level, 0)

    if pr == 0 or jr == 0:
        return 0.5, 0   # one side unknown — neutral

    gap = pr - jr
    abs_gap = abs(gap)
    score = max(0.0, 1.0 - abs_gap * 0.4)
    return score, gap


def match_profile(
    profile,
    *,
    remote_only: bool = False,
    limit: int = 20,
    min_score: float = 0.0,
) -> list[MatchResult]:
    """
    Return up to `limit` jobs ranked by composite score for the given CVProfile.

    Args:
        profile:     CVProfile instance (must have skills + embedding populated)
        remote_only: hard filter — exclude on_site jobs
        limit:       max results to return
        min_score:   exclude results below this total score
    """
    # ── Hard filters ────────────────────────────────────────────────────────
    qs = Job.objects.filter(
        extraction_status=Job.ExtractionStatus.SUCCESS,
        embedding__isnull=False,
    ).prefetch_related('skills')

    if remote_only:
        qs = qs.exclude(extracted_remote_status='on_site')

    jobs = list(qs)
    if not jobs:
        return []

    # ── Profile data ─────────────────────────────────────────────────────────
    profile_skill_ids = set(profile.skills.values_list('pk', flat=True))
    profile_vec = profile.embedding   # list[float] stored as JSONField

    results = []

    for job in jobs:
        job_skill_ids = set(job.skills.values_list('pk', flat=True))

        # Required skills — from JobSkill where extraction_method='llm'
        # We treat all skills on the job as required for now (no confidence split)
        # because the JobSkill table doesn't distinguish required vs nice-to-have
        # at query time without joining through the LLM extraction result.
        # Use all job skills as required; nice-to-have = empty (conservative).
        required_ids = job_skill_ids
        nice_ids: set[int] = set()

        # ── Required skill coverage ──────────────────────────────────────────
        if required_ids:
            matched_req_ids = profile_skill_ids & required_ids
            req_score = len(matched_req_ids) / len(required_ids)
        else:
            matched_req_ids = set()
            req_score = 0.5   # no required skills listed — neutral

        # ── Semantic similarity ──────────────────────────────────────────────
        if profile_vec and job.embedding:
            sem_score = max(0.0, _cosine(profile_vec, list(job.embedding)))
        else:
            sem_score = 0.0

        # ── Seniority fit ────────────────────────────────────────────────────
        sen_score, sen_gap = _seniority_fit(profile.seniority, job.seniority)

        # ── Nice-to-have ─────────────────────────────────────────────────────
        if nice_ids:
            matched_nice_ids = profile_skill_ids & nice_ids
            nice_score = len(matched_nice_ids) / len(nice_ids)
        else:
            matched_nice_ids = set()
            nice_score = 0.0

        # ── Recency ──────────────────────────────────────────────────────────
        rec_score = _recency(job.published_date)

        # ── Composite ────────────────────────────────────────────────────────
        total = (
            W_REQUIRED  * req_score  +
            W_SEMANTIC  * sem_score  +
            W_SENIORITY * sen_score  +
            W_NICE      * nice_score +
            W_RECENCY   * rec_score
        )

        if total < min_score:
            continue

        # Resolve skill names for explanation
        skill_name_map = {s.pk: s.name for s in job.skills.all()}
        matched_req_names  = [skill_name_map[i] for i in matched_req_ids if i in skill_name_map]
        missing_req_names  = [skill_name_map[i] for i in (required_ids - matched_req_ids) if i in skill_name_map]
        matched_nice_names = [skill_name_map[i] for i in matched_nice_ids if i in skill_name_map]

        results.append(MatchResult(
            job=job,
            total_score=round(total, 4),
            required_skill_score=round(req_score, 4),
            semantic_score=round(sem_score, 4),
            seniority_score=round(sen_score, 4),
            nice_to_have_score=round(nice_score, 4),
            recency_score=round(rec_score, 4),
            matched_required=sorted(matched_req_names),
            missing_required=sorted(missing_req_names),
            matched_nice=sorted(matched_nice_names),
            seniority_gap=sen_gap,
        ))

    results.sort(key=lambda r: r.total_score, reverse=True)
    return results[:limit]
