"""
Job matching service.

Produces a ranked list of jobs for a CVProfile with a composite score and
per-component breakdown so results are explainable.

Scoring components
------------------
Component               Weight   What it measures
required_skill_score    0.40     Proportion of job's required skills the profile has
seniority_score         0.30     Level fit — penalises gap in both directions
semantic_score          0.15     Cosine similarity of profile and job embeddings
nice_to_have_score      0.10     Bonus for desirable skills the profile has
recency_score           0.05     Slight preference for recently posted roles

Weights were tuned from the v1 proposal (semantic 0.25, seniority 0.20) after
the evaluation in docs/matching-evaluation.md.

Hard filters (applied in the database before scoring — requirements, not preferences)
-------------------------------------------------------------------------------------
- extraction_status = 'success'          job must have been processed
- embedding IS NOT NULL                  job must be embeddable
- canonical IS NULL                      job is not a known duplicate
- at least MIN_JOB_SKILLS skills         too few skills inflates coverage from one generic match
- remote_only                            excludes on_site and hybrid jobs
- countries                              job location must be in the list, or unstated / worldwide
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional

from django.db.models import Count, Prefetch, Q

from apps.intelligence.models import Job, JobSkill

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
W_SEMANTIC   = 0.15   # reduced from 0.25: semantic alone misleads on boilerplate-heavy descriptions
W_SENIORITY  = 0.30   # raised from 0.20: seniority mismatch is a hard problem, not a preference
W_NICE       = 0.10
W_RECENCY    = 0.05

WEIGHTS = {
    'required_skill': W_REQUIRED,
    'semantic':       W_SEMANTIC,
    'seniority':      W_SENIORITY,
    'nice_to_have':   W_NICE,
    'recency':        W_RECENCY,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, 'matching weights must sum to 1.0'


def resolve_weights(overrides: dict[str, float] | None = None) -> dict[str, float]:
    """
    Merge overrides into the default weights and rescale so they sum to 1.0,
    keeping total_score on a 0–1 scale. Raising one weight therefore lowers
    the others proportionally.
    """
    weights = dict(WEIGHTS)
    for name, value in (overrides or {}).items():
        if name not in WEIGHTS:
            raise ValueError(f'Unknown weight {name!r}. Choose from: {", ".join(WEIGHTS)}')
        if value < 0:
            raise ValueError(f'Weight {name!r} must be >= 0, got {value}')
        weights[name] = float(value)
    total = sum(weights.values())
    if total <= 0:
        raise ValueError('At least one weight must be positive')
    return {k: v / total for k, v in weights.items()}

# Minimum skills a job must have to be scored
# Jobs with fewer skills have inflated required_skill_score from single generic matches
MIN_JOB_SKILLS = 3

# Remote statuses excluded when the candidate can only work remotely.
# Blank / not_stated are kept: absence of information is not a mismatch.
_NOT_REMOTE = ('on_site', 'hybrid')

# Recency: exponential decay with this time constant; older than RECENCY_FLOOR scores 0
RECENCY_HALF_LIFE = 30   # days
RECENCY_FLOOR     = 180  # days


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
    weights: dict[str, float] = field(default_factory=lambda: dict(WEIGHTS))  # weights actually used
    profile_seniority: str = ''           # candidate level the seniority score was computed from

    @property
    def required_total(self) -> int:
        return len(self.matched_required) + len(self.missing_required)

    @property
    def components(self) -> dict[str, float]:
        """Raw 0–1 score per component."""
        return {
            'required_skill': self.required_skill_score,
            'semantic':       self.semantic_score,
            'seniority':      self.seniority_score,
            'nice_to_have':   self.nice_to_have_score,
            'recency':        self.recency_score,
        }

    @property
    def contributions(self) -> dict[str, float]:
        """Weighted contribution of each component; sums to total_score (± rounding)."""
        return {k: round(self.weights[k] * v, 4) for k, v in self.components.items()}


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
    score = max(0.0, 1.0 - abs(gap) * 0.4)
    return score, gap


def candidate_jobs(*, remote_only: bool = False, countries: Iterable[str] | None = None):
    """
    Apply the hard filters in the database and return the queryset that
    match_profile() scores. Exposed separately so filters can be tested and
    inspected on their own.
    """
    qs = (
        Job.objects
        .filter(
            extraction_status=Job.ExtractionStatus.SUCCESS,
            embedding__isnull=False,
            canonical__isnull=True,
        )
        .annotate(n_skills=Count('jobskill'))
        .filter(n_skills__gte=MIN_JOB_SKILLS)
    )

    if remote_only:
        qs = qs.exclude(extracted_remote_status__in=_NOT_REMOTE)

    if countries:
        codes = [c.upper() for c in countries]
        qs = qs.filter(
            Q(location__isnull=True)
            | Q(location__normalised_country='')
            | Q(location__normalised_country__in=codes)
        )

    return qs.select_related('company', 'location').prefetch_related(
        Prefetch('jobskill_set', queryset=JobSkill.objects.select_related('skill'))
    )


def match_profile(
    profile,
    *,
    remote_only: bool = False,
    countries: Iterable[str] | None = None,
    limit: int = 20,
    min_score: float = 0.0,
    weights: dict[str, float] | None = None,
    job_ids: Iterable[int] | None = None,
) -> list[MatchResult]:
    """
    Return up to `limit` jobs ranked by composite score for the given CVProfile.

    Args:
        profile:     CVProfile instance (must have skills + embedding populated)
        remote_only: hard filter — exclude on_site and hybrid jobs
        countries:   hard filter — ISO alpha-2 codes the candidate can work in;
                     jobs located elsewhere are excluded (unstated location is kept)
        limit:       max results to return
        min_score:   exclude results below this total score
        weights:     optional overrides, e.g. {'seniority': 0.4}; rescaled to sum to 1.0
        job_ids:     restrict scoring to these jobs (hard filters still apply)

    A profile with no resolved skills returns [] — there is nothing to match on.
    """
    w = resolve_weights(weights)

    profile_skill_ids = set(profile.skills.values_list('pk', flat=True))
    if not profile_skill_ids:
        # Nothing to match on — similarity and seniority alone would rank noise
        return []
    profile_vec = profile.embedding   # list[float] stored as JSONField

    jobs = candidate_jobs(remote_only=remote_only, countries=countries)
    if job_ids is not None:
        jobs = jobs.filter(pk__in=job_ids)

    results = []

    for job in jobs:
        job_skills = list(job.jobskill_set.all())     # prefetched — no query per job
        names = {js.skill_id: js.skill.name for js in job_skills}
        required_ids = {js.skill_id for js in job_skills if js.is_required}
        nice_ids     = {js.skill_id for js in job_skills if not js.is_required}

        # ── Required skill coverage ──────────────────────────────────────────
        matched_req_ids = profile_skill_ids & required_ids
        req_score = len(matched_req_ids) / len(required_ids) if required_ids else 0.5  # none listed — neutral

        # ── Semantic similarity ──────────────────────────────────────────────
        if profile_vec and job.embedding is not None:
            sem_score = max(0.0, _cosine(profile_vec, list(job.embedding)))
        else:
            sem_score = 0.0

        # ── Seniority fit ────────────────────────────────────────────────────
        sen_score, sen_gap = _seniority_fit(profile.seniority, job.seniority)

        # ── Nice-to-have ─────────────────────────────────────────────────────
        matched_nice_ids = profile_skill_ids & nice_ids
        nice_score = len(matched_nice_ids) / len(nice_ids) if nice_ids else 0.0

        # ── Recency ──────────────────────────────────────────────────────────
        rec_score = _recency(job.published_date)

        # ── Composite ────────────────────────────────────────────────────────
        total = (
            w['required_skill'] * req_score  +
            w['semantic']       * sem_score  +
            w['seniority']      * sen_score  +
            w['nice_to_have']   * nice_score +
            w['recency']        * rec_score
        )

        if total < min_score:
            continue

        results.append(MatchResult(
            job=job,
            total_score=round(total, 4),
            required_skill_score=round(req_score, 4),
            semantic_score=round(sem_score, 4),
            seniority_score=round(sen_score, 4),
            nice_to_have_score=round(nice_score, 4),
            recency_score=round(rec_score, 4),
            matched_required=sorted(names[i] for i in matched_req_ids),
            missing_required=sorted(names[i] for i in required_ids - matched_req_ids),
            matched_nice=sorted(names[i] for i in matched_nice_ids),
            seniority_gap=sen_gap,
            weights=w,
            profile_seniority=profile.seniority or '',
        ))

    results.sort(key=lambda r: (-r.total_score, r.job.pk))
    return results[:limit]


def common_gaps(results: list[MatchResult], limit: int = 5) -> list[tuple[str, int]]:
    """
    Required skills missing most often across these matches, as (skill, count),
    most frequent first. Learning the top one closes a gap in the most jobs.
    """
    counts: dict[str, int] = {}
    for r in results:
        for name in r.missing_required:
            counts[name] = counts.get(name, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
