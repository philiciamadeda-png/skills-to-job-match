I'm building the matching step for my Django job-matching app: given a candidate profile extracted from a CV, return a ranked list of jobs with a score that can be explained component by component. I've already decided on a design — I want you to **critique it, not redesign it**. Tell me where my weights, penalties or filters are wrong, what edge cases will break, and what I've missed. Don't write the implementation unless I ask.

**Data I have available**

Candidate side — `CVProfile` (`apps/accounts/models.py`):
- `skills` — M2M to canonical `Skill`, resolved through the same `resolve_skill()` as jobs, so "Postgres" on a CV and "PostgreSQL" on a job are the same row
- `seniority` — one of `junior | mid | senior | principal | director | not_stated`
- `years_experience` — int or null
- `embedding` — 768-dim `nomic-embed-text` vector built from `CV | seniority | skills: ... | first 400 chars`

Job side — `Job` (`apps/intelligence/models.py`), ~1k rows from Remotive and Arbeitnow:
- skills via `JobSkill` with an `is_required` flag (LLM split required vs nice-to-have)
- `seniority` — same vocabulary as the CV
- `extracted_remote_status` — `remote | hybrid | on_site | not_stated`
- `location` → `normalised_country` (ISO alpha-2, often blank for "Remote / worldwide")
- `published_date`, `extraction_status`, `canonical` (non-null = duplicate)
- `embedding` — same model, built from `title | seniority | skills: ... | first 400 chars`, pgvector with an HNSW cosine index

**Hard filters (applied first, in the database)**

These are requirements, not preferences — a job that fails one is not a weak match, it is not a match:
1. `extraction_status = 'success'` and `embedding IS NOT NULL`
2. `canonical IS NULL` — don't show the same job twice
3. Job has at least 3 extracted skills — otherwise one generic skill gives 100% coverage
4. `remote_only` — if the candidate can only work remotely, exclude `on_site` and `hybrid`. I plan to keep `not_stated` because missing information isn't evidence of a mismatch.
5. `countries` — if the candidate can only work in certain countries, exclude jobs located elsewhere; keep jobs with no stated country

**Proposed scoring (each component 0–1, weighted sum)**

| Component | Weight | How it's computed |
|---|---|---|
| Required skill coverage | 0.40 | matched required ÷ total required (0.5 if the job lists none) |
| Semantic similarity | 0.25 | cosine similarity of the two embeddings, floored at 0 |
| Seniority fit | 0.20 | `1 − 0.4 × |gap|` on junior=1 … director=5, so gap 1 → 0.6, gap 2 → 0.2, gap ≥3 → 0. Penalises **both** directions — a graduate shown a principal role and a senior shown an internship both score low. 0.5 if either side is not stated. |
| Nice-to-have coverage | 0.10 | matched nice-to-have ÷ total nice-to-have (0 if none) |
| Recency | 0.05 | `exp(−age_days / 30)`, 0 after 180 days, 0.5 if no date |

**Explainability requirement**

Every component must stay available separately on the result — raw 0–1 score, its weighted contribution, the signed seniority gap, and the lists of matched required, missing required and matched nice-to-have skill names. A later step feeds these facts (and only these) to an LLM to write a two-sentence explanation, so the total must be fully reconstructable from the parts.

**What I want from you**

1. Are the weights in the right order and roughly the right size? Where will semantic similarity mislead me?
2. Is the linear seniority penalty right, or should over- and under-qualification be asymmetric?
3. Are the neutral defaults (0.5 for unknown seniority, no required skills, no date) sensible, or do they let bad jobs float up?
4. Are any of my hard filters really preferences, or any preferences really hard filters?
5. Should `years_experience` be used, and where?
6. What failure cases should I put in an evaluation set before I trust the ranking?
