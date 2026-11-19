# Matching Evaluation — Findings and Fixes

## Evaluation 2 — real jobs, four CVs, top 10 (November 2026)

### Method

1. **CVs:** four CVs chosen to trigger the failures the brief lists, including my own.

   | CV | Profile | Extracted level | What it tests |
   |---|---|---|---|
   | 13 | Me: Business IT student, Kiriri Women's University | junior, "2 years" | A junior profile shown senior roles |
   | 14 | Senior backend engineer: Python, Django, Go, AWS, Kubernetes | senior, 7 years | Baseline: should match backend roles |
   | 15 | Data analyst: SQL, Excel, Power BI, Tableau | mid, 4 years | Matches on common skills (Python, SQL, Excel) |
   | 16 | Senior marketing manager: SEO, Google Ads, HubSpot | senior, 9 years | A non-tech CV against a mostly-tech job set |

2. **Jobs:** 616 fetched (Remotive's free feed returned only 16, Arbeitnow 600). 250 extracted with llama3.2: 246 succeeded and 4 failed on invalid JSON. **110 were eligible for matching** after the hard filters (3+ skills, embedded, not a duplicate).
3. **Ratings:** I ran `match --cv <id> --top 10` and rated each result **G** (good), **P** (plausible) or **W** (clearly wrong).
4. **Number:** clearly wrong results in the top 5, summed over the four CVs.
5. **One weight change:** re-ran with a single weight changed and compared the number.

### Bugs found before rating — and fixed

The first run could not be rated honestly. Two extraction bugs were deciding the ranking:

| Bug | Evidence | Fix |
|---|---|---|
| **Job extraction copied its prompt example.** The worked example in `extract_job_details.md` is "Python and Django … PostgreSQL required. Redis is a plus." | 13 unrelated jobs (Senior Product Manager, Intelligence Officer, Director Enterprise Planning…) required exactly Python, Django and PostgreSQL with Redis as a bonus. None of the adverts mention Django, PostgreSQL or Redis. These jobs filled 6–7 of the top 10 for CVs 13, 14 and 15. Across all jobs, **90 of 246** had at least one skill their advert never mentions (227 links). | `skills_in_text()`: a skill is kept only if it appears as a whole word or phrase in the text the model saw. It applies to both jobs and CVs. The 227 invented links were removed and the jobs re-embedded. |
| **CV extraction copied its prompt example** ("domain-specific (e.g. "Agile", "Scrum")"). | Agile and Scrum appeared on all three tech CVs; none of them mention either. | Prompt `extract_cv_v2.md` has no example skill names, plus the same `skills_in_text()` check. |

The three "Demo Co" jobs left over from an earlier page test were also excluded, since they are not real adverts. The ratings below are on the corrected data.

### Ratings (weights: required 0.40, seniority 0.30, semantic 0.15, nice-to-have 0.10, recency 0.05)

**CV 13 — me, junior**

| # | Job | Job level | Score | Rating |
|---|---|---|---|---|
| 1 | Reporting & Data Analyst (6-Month FTC) | junior | 0.689 | G |
| 2 | Freelance Copywriter | not stated | 0.465 | P |
| 3 | Sr Renewals Manager | mid | 0.421 | P |
| 4 | Freelance, Recovery Operations | junior | 0.415 | P |
| 5 | Stage - Service client : Onboarding | junior | 0.415 | **W** |
| 6 | Werkstudent:in Business Consultancy | junior | 0.410 | W |
| 7 | Backend Engineer / DevOps | mid | 0.410 | W |
| 8 | (Junior) E-Commerce Kaufmann (w/m/d) | junior | 0.408 | W |
| 9 | Engineer - .NET Backend (London) | mid | 0.401 | W |
| 10 | Senior React Full-stack Developer | senior | 0.391 | W |

**CV 14 — senior backend engineer**

| # | Job | Job level | Score | Rating |
|---|---|---|---|---|
| 1 | Senior Back-end Developer | senior | 0.833 | P |
| 2 | Member of Technical Staff — Infrastructure | senior | 0.709 | P |
| 3 | Hands-on Engineering Manager DevOps (GCP/Kubernetes) | senior | 0.691 | P |
| 4 | Senior Data Engineer | senior | 0.689 | P |
| 5 | Backend Engineer (Golang) | senior | 0.684 | P |
| 6 | Senior React Full-stack Developer | senior | 0.681 | P |
| 7 | Solutions Architect - Travel, Transport, Hospitality | senior | 0.633 | P |
| 8 | Senior AI Enabled Software Engineer | senior | 0.630 | P |
| 9 | Software-Developer Simulation HMI (m/w/d) | senior | 0.614 | P |
| 10 | Senior Backend Engineer / DevOps | senior | 0.606 | P |

**CV 15 — data analyst, mid**

| # | Job | Job level | Score | Rating |
|---|---|---|---|---|
| 1 | Reporting & Data Analyst (6-Month FTC) | junior | 0.577 | G |
| 2 | Senior React Full-stack Developer | senior | 0.509 | G |
| 3 | Engineer - .NET Backend (London) | mid | 0.504 | G |
| 4 | Solutions Architect - Travel, Transport, Hospitality | senior | 0.503 | P |
| 5 | Senior AI Enabled Software Engineer | senior | 0.495 | G |
| 6 | Software-Developer Simulation HMI (m/w/d) | senior | 0.485 | G |
| 7 | Senior Data Engineer | senior | 0.476 | P |
| 8 | Freelance Copywriter | not stated | 0.465 | G |
| 9 | Backend Engineer / DevOps | mid | 0.459 | G |
| 10 | US Remote Patient Care Advocate (Customer Service) | mid | 0.428 | G |

**CV 16 — senior marketing manager**

| # | Job | Job level | Score | Rating |
|---|---|---|---|---|
| 1 | Senior AI Enabled Software Engineer | senior | 0.621 | G |
| 2 | Sales Manager - French Market | senior | 0.522 | P |
| 3 | Freelance Copywriter | not stated | 0.470 | P |
| 4 | Senior Category Manager – Marketing | senior | 0.436 | P |
| 5 | Indirect Procurement Senior Manager - Marketing | senior | 0.435 | P |
| 6 | Senior Data Engineer | senior | 0.432 | G |
| 7 | Senior CRM & Lifecycle Analyst (B2C) – Marketing | senior | 0.431 | G |
| 8 | Tech Lead Full-Stack Rails Engineer | senior | 0.430 | G |
| 9 | Senior React Full-stack Developer | senior | 0.428 | G |
| 10 | Senior Consultant (Strategy & Data/AI Transformation) | senior | 0.424 | G |

### The number

| CV | Clearly wrong in top 5 |
|---|---|
| 13 — me | 1 / 5 |
| 14 — backend engineer | 0 / 5 |
| 15 — data analyst | 0 / 5 |
| 16 — marketing manager | 0 / 5 |
| **Total** | **1 / 20 (5%)** |

**Caveat on the ratings.** The same job was rated differently for different CVs. Senior React Full-stack Developer is **W** for me but **G** for the data analyst and the marketing manager, and Senior AI Enabled Software Engineer is **G** for the marketing manager. Software engineering roles rated good for non-engineering profiles make the 5% look lower than it should be, so treat it as a lower bound. A second rater, or a short written rule for what "good" means, would make the number more trustworthy.

### One weight change: required skills 0.40 → 0.50

`match --weight required_skill=0.5` (the other weights are rescaled so the total stays 1: required 0.455, seniority 0.273, semantic 0.136, nice-to-have 0.091, recency 0.045).

| CV | Wrong in top 5 before | After | What changed |
|---|---|---|---|
| 13 — me | 1 | **2** | Two French junior admin roles (P, W) dropped out; Senior React Full-stack Developer and Backend Engineer / DevOps (both W) moved up to #4 and #5 |
| 14 | 0 | 0 | No change |
| 15 | 0 | 0 | .NET Backend swapped for Software-Developer Simulation (both G) |
| 16 | 0 | 0 | No change |
| **Total** | **1 / 20** | **2 / 20** | **Worse — reverted, weights stay at 0.40** |

Raising the skill weight helps when a job is right for the level but wrong for the skills. It hurts when a senior coding job shares one skill with a junior: Python on my CV pulled in a senior React role. The seniority weight is what keeps those out, so it should not be traded away for skill coverage.

### The four failures the brief asks about

| Failure | Seen? | Evidence | Status |
|---|---|---|---|
| **Junior profile matched to senior roles** | Yes, mildly | Senior React Full-stack Developer is #10 for me; with skills weighted higher it rises to #4. | Seniority weight 0.30 is doing its job; keep it. |
| **Jobs matched on a common skill** | Yes | Python alone puts Senior React Full-stack Developer (missing React) in the top 10 for CVs 13, 14 and 15. It is also #9 for the marketing manager with no skill matched at all, on level and similarity only. **Docker** matched me to a *sales* job (Sr Renewals Manager) because the company is called Docker: the advert says "Docker" 14 times and the model extracted the company name as a skill. | Not fixed. Next: weight rare skills above ubiquitous ones (inverse document frequency over JobSkill), and drop skills equal to the company name. |
| **Near-identical duplicates in the top 10** | No | 0 jobs marked as duplicates, and none visible in any top 10. | Nothing to fix on this data. |
| **A strong match the person could never take** | Yes | **7 eligible jobs require a language** (French, German) and nothing filters on it: Sales Manager - French Market (native French required) is #2 for the marketing manager; French and German junior roles are in my top 10. The Patient Care Advocate role is US-only. | Missing filter: a "languages I speak" hard filter, matched against language skills on the job. |

### Other findings

- **Jobs with no required skills get a free 0.5 for required-skill coverage.** Only 2 of 110 eligible jobs have no required skills (Freelance Copywriter and Senior AI Enabled Software Engineer), yet they appear in the top 5 for three of the four CVs, and Senior AI Enabled Software Engineer is #1 for the marketing manager. The 0.5 default from the matching design rewards a job for saying nothing. Next: use 0, or exclude jobs with no required skills, then re-measure.
- **My CV was read as "2 years" of experience.** The model counted student projects and volunteering as professional experience. The level (junior) is still right, but `years_experience` should not count non-employment entries.
- **The job set is mostly tech, senior and German- or French-language** (Arbeitnow). A non-tech CV (16) can only be matched against what exists, so its list is mostly plausible-at-best.

### What was fixed in this round

| Fix | Effect |
|---|---|
| `skills_in_text()` on job and CV extraction | Removed 227 invented job–skill links from 90 jobs; the fake Python/Django/PostgreSQL jobs disappeared from every top 10 |
| CV prompt v2 (no example skills) | Agile/Scrum gone from all CVs |
| Explanation count check | Stops explanations like "missing five of the six" for a 0-of-4 match (see README) |
| Weight change tested and **rejected** | Required 0.50 made the number worse (1 → 2 wrong in the top 5) |

---

## Evaluation 1 — 11 jobs, top 5 (October 2026)

Kept for history. It predates the required/nice-to-have split and was run on 11 jobs, all labelled senior.

### Method

4 CVs × top-5 results = 20 judgements.
Each result rated: **good** (correct match), **plausible** (debatable), **wrong** (clear mismatch).
Metric: proportion of clearly wrong results in the top 5 per CV.

#### CV profiles used

| CV | Profile | Seniority | Purpose |
|---|---|---|---|
| 1 | Senior Python Engineer, 7yr | senior | Baseline — should match Python/Django backend roles |
| 2 | Junior Python Developer, 1yr | junior | Tests seniority weighting |
| 3 | Marketing Manager, 8yr | senior | Tests false positives from generic skills (Git, Python beginner) |
| 4 | Senior Rails Engineer, 9yr | senior | Tests skill specificity |

---

### Before fixes (v1 weights: req=0.40, sem=0.25, sen=0.20)

#### CV 1 — Senior Python Engineer
| Rank | Job | Rating |
|---|---|---|
| 1 | Head of Engineering | ✅ good |
| 2 | Senior React Full-stack Developer | plausible |
| 3 | Tech Lead Full-Stack Rails Engineer | plausible |
| 4 | Full-Stack Developer | plausible |
| 5 | Software Engineer, AI Coding Tasks | plausible |

**Wrong in top 5: 0/5**

#### CV 2 — Junior Python Developer
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

#### CV 3 — Marketing Manager
| Rank | Job | Rating |
|---|---|---|
| 1 | Head of Engineering | ❌ wrong — Python beginner + Git matching as real skills |
| 2 | Freelance Writer | ❌ wrong — 0 skills |
| 3 | Senior React Full-stack Developer | ❌ wrong — wrong domain |
| 4 | Inside Sales Contractor | ❌ wrong — 0 skills |
| 5 | Software Engineer, AI Coding Tasks | ❌ wrong — wrong domain |

**Wrong in top 5: 5/5**

Root causes: same as CV 2 — sparse-skill jobs inflating scores, plus beginner Python/Git matching as real technical skills.

#### CV 4 — Senior Rails Engineer
| Rank | Job | Rating |
|---|---|---|
| 1 | Head of Engineering | plausible |
| 2 | Tech Lead Full-Stack Rails Engineer | ✅ good |
| 3 | Full-Stack Developer | plausible |
| 4 | Senior React Full-stack Developer | plausible |
| 5 | Software Engineer, AI Coding Tasks | plausible |

**Wrong in top 5: 0/5**

#### Before-fix summary

| CV | Wrong/5 |
|---|---|
| CV1 Senior Python | 0/5 |
| CV2 Junior Python | 4/5 |
| CV3 Marketing | 5/5 |
| CV4 Senior Rails | 0/5 |
| **Total** | **9/20 (45%)** |

---

### Fixes applied

#### Fix 1 — Minimum skill filter (`MIN_JOB_SKILLS = 3`)

Jobs with fewer than 3 extracted skills are excluded before scoring.
Eliminates "Freelance Writer" (0 skills) and "Inside Sales Contractor" (0 skills) from all results.

#### Fix 2 — Rebalanced weights

| Component | Before | After | Reason |
|---|---|---|---|
| required_skill | 0.40 | 0.40 | Unchanged — correct |
| semantic | 0.25 | 0.15 | Was masking seniority penalty |
| seniority | 0.20 | 0.30 | Gap of 2 now costs more |
| nice_to_have | 0.10 | 0.10 | Unchanged |
| recency | 0.05 | 0.05 | Unchanged |

A junior vs senior gap of 2 now contributes `0.30 × 0.20 = 0.06` vs `0.20 × 0.20 = 0.04` before.

---

### After fixes (v2 weights: req=0.40, sem=0.15, sen=0.30)

#### CV 2 — Junior Python Developer (after)
| Rank | Job | Score | Rating |
|---|---|---|---|
| 1 | Head of Engineering | 0.400 | ❌ wrong but score is low |
| 2 | Remote Office Assistant | 0.261 | ❌ wrong |
| 3 | Freelance Copywriter | 0.253 | ❌ wrong |
| 4 | Senior React Full-stack Developer | 0.240 | plausible |
| 5 | Software Engineer, AI Coding Tasks | 0.239 | plausible |

**Wrong in top 5: 3/5** (was 4/5). Scores are visibly lower (0.24–0.40 vs 0.44–0.46 before).

#### CV 3 — Marketing Manager (after)
All 5 results remain tech jobs — unchanged at 5/5 wrong.
Root cause is data, not algorithm: no non-tech jobs in the dataset to surface instead.

#### After-fix summary

| CV | Before | After |
|---|---|---|
| CV1 Senior Python | 0/5 | 0/5 |
| CV2 Junior Python | 4/5 | 3/5 |
| CV3 Marketing | 5/5 | 5/5 |
| CV4 Senior Rails | 0/5 | 0/5 |
| **Total** | **9/20 (45%)** | **8/20 (40%)** |

---

### Remaining failures and root causes

#### 1. CV2 — Head of Engineering still ranks #1 for a junior

The job has 4 skills. The junior profile matches 2 (Python, Django) → `req=0.50`.
The seniority penalty reduces the score to 0.400 but nothing better exists in the dataset.
**Root cause: dataset.** All 11 jobs are labelled `senior`. The algorithm correctly penalises
the mismatch — scores are 0.24–0.40 vs 0.51–0.85 for a matched senior profile.

#### 2. CV3 — Marketing manager matches tech jobs

Python (beginner) and Git resolved to canonical skills and count equally against tech requirements.
The algorithm has no notion of proficiency level.
**Fix needed:** proficiency weighting — out of scope this week.

#### 3. Sparse soft-skill jobs still appear

"Remote Office Assistant" (4 soft skills) and "Freelance Copywriter" (3 soft skills) pass
`MIN_JOB_SKILLS=3`. A minimum `required_skill_score` threshold (e.g. 0.10) would remove
zero-overlap results. Not applied — would hide legitimate low-overlap results for sparse profiles.

---

### Known gaps not tested

- **Near-duplicate jobs in top 10** — only 11 jobs, no duplicates present
- **Remote filter** — no `on_site` jobs in dataset
- **Rare vs ubiquitous skill weighting** — Git matching should count less than a rare skill match

---

### Conclusion

The algorithm works correctly for well-matched profiles (0/5 wrong for CV1 and CV4).
It degrades gracefully for mismatches — scores are visibly lower, which is correct.
The remaining failures are data quality issues (no junior jobs, no proficiency levels),
not algorithm bugs. The fixes reduced wrong results from 45% → 40%.
