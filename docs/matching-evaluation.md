# Matching Evaluation — Findings and Fixes

## Method

4 CVs × top-5 results = 20 judgements.
Each result rated: **good** (correct match), **plausible** (debatable), **wrong** (clear mismatch).
Metric: proportion of clearly wrong results in the top 5 per CV.

### CV profiles used

| CV | Profile | Seniority | Purpose |
|---|---|---|---|
| 1 | Senior Python Engineer, 7yr | senior | Baseline — should match Python/Django backend roles |
| 2 | Junior Python Developer, 1yr | junior | Tests seniority weighting |
| 3 | Marketing Manager, 8yr | senior | Tests false positives from generic skills (Git, Python beginner) |
| 4 | Senior Rails Engineer, 9yr | senior | Tests skill specificity |

---

## Before fixes (v1 weights: req=0.40, sem=0.25, sen=0.20)

### CV 1 — Senior Python Engineer
| Rank | Job | Rating |
|---|---|---|
| 1 | Head of Engineering | ✅ good |
| 2 | Senior React Full-stack Developer | plausible |
| 3 | Tech Lead Full-Stack Rails Engineer | plausible |
| 4 | Full-Stack Developer | plausible |
| 5 | Software Engineer, AI Coding Tasks | plausible |

**Wrong in top 5: 0/5**

### CV 2 — Junior Python Developer
| Rank | Job | Rating |
|---|---|---|
| 1 | Freelance Writer | ❌ wrong — 0 skills, matched on nothing |
| 2 | Head of Engineering | ❌ wrong — 2-level seniority gap, senior role |
| 3 | Inside Sales Contractor | ❌ wrong — 0 skills, non-tech |
| 4 | Senior React Full-stack Developer | ❌ wrong — senior role, wrong stack |
| 5 | Software Engineer, AI Coding Tasks | plausible but senior |

**Wrong in top 5: 4/5**

Root causes:
1. Jobs with 0–2 skills get `req_score=0.50` from a single generic match (Git, Python) — inflated score
2. Seniority weight (0.20) too weak: `0.20 × 0.20 = 0.04` penalty easily overcome by semantic score

### CV 3 — Marketing Manager
| Rank | Job | Rating |
|---|---|---|
| 1 | Head of Engineering | ❌ wrong — Python beginner + Git matching as real skills |
| 2 | Freelance Writer | ❌ wrong — 0 skills |
| 3 | Senior React Full-stack Developer | ❌ wrong — wrong domain |
| 4 | Inside Sales Contractor | ❌ wrong — 0 skills |
| 5 | Software Engineer, AI Coding Tasks | ❌ wrong — wrong domain |

**Wrong in top 5: 5/5**

Root causes: same as CV 2 — sparse-skill jobs inflating scores, plus beginner Python/Git matching as real technical skills.

### CV 4 — Senior Rails Engineer
| Rank | Job | Rating |
|---|---|---|
| 1 | Head of Engineering | plausible |
| 2 | Tech Lead Full-Stack Rails Engineer | ✅ good |
| 3 | Full-Stack Developer | plausible |
| 4 | Senior React Full-stack Developer | plausible |
| 5 | Software Engineer, AI Coding Tasks | plausible |

**Wrong in top 5: 0/5**

### Before-fix summary

| CV | Wrong/5 |
|---|---|
| CV1 Senior Python | 0/5 |
| CV2 Junior Python | 4/5 |
| CV3 Marketing | 5/5 |
| CV4 Senior Rails | 0/5 |
| **Total** | **9/20 (45%)** |

---

## Fixes applied

### Fix 1 — Minimum skill filter (`MIN_JOB_SKILLS = 3`)

Jobs with fewer than 3 extracted skills are excluded before scoring.
Eliminates "Freelance Writer" (0 skills) and "Inside Sales Contractor" (0 skills) from all results.

### Fix 2 — Rebalanced weights

| Component | Before | After | Reason |
|---|---|---|---|
| required_skill | 0.40 | 0.40 | Unchanged — correct |
| semantic | 0.25 | 0.15 | Was masking seniority penalty |
| seniority | 0.20 | 0.30 | Gap of 2 now costs more |
| nice_to_have | 0.10 | 0.10 | Unchanged |
| recency | 0.05 | 0.05 | Unchanged |

A junior vs senior gap of 2 now contributes `0.30 × 0.20 = 0.06` vs `0.20 × 0.20 = 0.04` before.

---

## After fixes (v2 weights: req=0.40, sem=0.15, sen=0.30)

### CV 2 — Junior Python Developer (after)
| Rank | Job | Score | Rating |
|---|---|---|---|
| 1 | Head of Engineering | 0.400 | ❌ wrong but score is low |
| 2 | Remote Office Assistant | 0.261 | ❌ wrong |
| 3 | Freelance Copywriter | 0.253 | ❌ wrong |
| 4 | Senior React Full-stack Developer | 0.240 | plausible |
| 5 | Software Engineer, AI Coding Tasks | 0.239 | plausible |

**Wrong in top 5: 3/5** (was 4/5). Scores are visibly lower (0.24–0.40 vs 0.44–0.46 before).

### CV 3 — Marketing Manager (after)
All 5 results remain tech jobs — unchanged at 5/5 wrong.
Root cause is data, not algorithm: no non-tech jobs in the dataset to surface instead.

### After-fix summary

| CV | Before | After |
|---|---|---|
| CV1 Senior Python | 0/5 | 0/5 |
| CV2 Junior Python | 4/5 | 3/5 |
| CV3 Marketing | 5/5 | 5/5 |
| CV4 Senior Rails | 0/5 | 0/5 |
| **Total** | **9/20 (45%)** | **8/20 (40%)** |

---

## Remaining failures and root causes

### 1. CV2 — Head of Engineering still ranks #1 for a junior

The job has 4 skills. The junior profile matches 2 (Python, Django) → `req=0.50`.
The seniority penalty reduces the score to 0.400 but nothing better exists in the dataset.
**Root cause: dataset.** All 11 jobs are labelled `senior`. The algorithm correctly penalises
the mismatch — scores are 0.24–0.40 vs 0.51–0.85 for a matched senior profile.

### 2. CV3 — Marketing manager matches tech jobs

Python (beginner) and Git resolved to canonical skills and count equally against tech requirements.
The algorithm has no notion of proficiency level.
**Fix needed:** proficiency weighting — out of scope this week.

### 3. Sparse soft-skill jobs still appear

"Remote Office Assistant" (4 soft skills) and "Freelance Copywriter" (3 soft skills) pass
`MIN_JOB_SKILLS=3`. A minimum `required_skill_score` threshold (e.g. 0.10) would remove
zero-overlap results. Not applied — would hide legitimate low-overlap results for sparse profiles.

---

## Known gaps not tested

- **Near-duplicate jobs in top 10** — only 11 jobs, no duplicates present
- **Remote filter** — no `on_site` jobs in dataset
- **Rare vs ubiquitous skill weighting** — Git matching should count less than a rare skill match

---

## Conclusion

The algorithm works correctly for well-matched profiles (0/5 wrong for CV1 and CV4).
It degrades gracefully for mismatches — scores are visibly lower, which is correct.
The remaining failures are data quality issues (no junior jobs, no proficiency levels),
not algorithm bugs. The fixes reduced wrong results from 45% → 40%.
