# Design Note — CV-to-Job Matching

How a CV becomes a ranked list of jobs, and why it's built this way. Code: `apps/intelligence/matching.py`, `apps/accounts/cv_extraction.py`, `apps/intelligence/explain.py`.

---

## 1. What gets embedded, and why

Both sides are embedded from the same four-part text, with `nomic-embed-text` (768 dimensions, local Ollama):

```
Job:  {title} | {seniority} | skills: {canonical skills} | {first 400 chars of description}
CV:   CV      | {seniority} | skills: {canonical skills} | {first 400 chars of CV text}
```

The skills are the canonical names after `resolve_skill()`, so "Postgres" on a CV and "PostgreSQL" on a job produce the same tokens.

| Option | Why not |
|---|---|
| Full job description | Boilerplate dominates. In the comparison harness a generic agency listing (Lemon.io) scored 0.529 against "Python data engineer with Spark and AWS" on remote-work culture text, not requirements. |
| Skills only | No context. "Python" matches everything, and jobs with sparse skills have almost nothing to embed. |
| **Title + seniority + skills + short snippet** | Chosen. The requirements carry the signal; the title and 400-character snippet add enough context to tell a data engineer from a backend developer. |
| Raw CV text against structured job text | Rejected outright — the two sides would sit in different regions of the vector space and the similarity would be meaningless. Both sides must be built the same way. |

The CV and job sides share one embedding helper (`_embed_batch`, `EMBED_MODEL`), so changing the model changes both. Jobs are re-embedded only when the SHA-256 of their text or the model name changes.

Known cost of this choice: the first 400 characters of a CV are usually the name and contact details. They add noise to the vector and put personal data into it (see section 5).

## 2. Scoring

Vector similarity alone was not used — nearest-neighbour search has no notion of a missing required skill or a wrong level. Each job that passes the hard filters gets five 0–1 scores combined with fixed weights:

| Component | Weight | How it's computed |
|---|---|---|
| Required skill coverage | **0.40** | matched required ÷ job's required skills (0.5 if the job lists none) |
| Seniority fit | **0.30** | `1 − 0.4 × |gap|` on junior=1 … director=5: gap 1 → 0.6, 2 → 0.2, ≥ 3 → 0. Same penalty in both directions. 0.5 if either side is not stated. |
| Semantic similarity | **0.15** | cosine similarity of the two embeddings, floored at 0 |
| Nice-to-have coverage | **0.10** | matched nice-to-have ÷ job's nice-to-have skills (0 if none) |
| Recency | **0.05** | `exp(−age_days / 30)`, 0 after 180 days, 0.5 if no date |

The proposal (`task6_prompt.md`) had semantic at 0.25 and seniority at 0.20. Evaluation showed similarity masking a two-level seniority gap, so they were swapped toward seniority.

Every result keeps each raw score, its weighted contribution (these sum to the total), the signed seniority gap, and the matched / missing / nice-to-have skill names. That is all the explanation step is allowed to see. Weights can be overridden per run (`--weight seniority=0.5`) and are rescaled to sum to 1. Ties break on job id, so ranking is deterministic.

## 3. Hard filters vs scored

A hard filter is a requirement: a job that fails it is not a weak match, it is not a match. Filters run in the database before scoring.

| Hard filter | Rule |
|---|---|
| Processed | `extraction_status = success` and an embedding exists |
| Not a duplicate | `canonical IS NULL` |
| Enough skills | at least 3 extracted skills — otherwise one generic match gives 100% coverage |
| Remote only (candidate choice) | excludes `on_site` and `hybrid`; keeps `remote` and unstated |
| Countries (candidate choice) | job country must be in the list; jobs with no stated country are kept |
| Candidate has skills | a profile with no recognised skills gets no matches at all, rather than a list ranked on similarity |

Scored, not filtered: **seniority** (a one-level stretch is a reasonable application, so it's a penalty that reaches 0 at three levels), **missing skills** (few candidates meet every requirement), and **recency**. Unstated remote status and location are kept, because missing information isn't evidence of a mismatch.

## 4. Evaluation without ground truth

There is no labelled "right answer" for a CV, so the evaluation combines three things that don't need one.

1. **Invariants as tests.** Properties that must hold whatever the right ranking is: a skill written differently on each side resolves to the same record and counts as matched; the same inputs give the same scores and order; a perfect-scoring onsite job never reaches a remote-only candidate; seniority gaps are penalised in both directions; empty or unreadable CVs give a message and no matches; an explanation receives exactly the facts of its match and nothing else. 110 tests, all passing.
2. **Hand judgement of the top results.** Four contrasting CVs (senior Python, junior Python, marketing manager, senior Rails) × top 5 = 20 results, each rated good / plausible / wrong (`docs/matching-evaluation.md`). Wrong results fell from 9/20 (45%) to 8/20 (40%) after the minimum-skills filter and the weight change. Well-matched profiles had 0/5 wrong; the failures concentrate on profiles the dataset can't serve (no junior or non-tech jobs among the 11 evaluated).
3. **Side-by-side comparisons for each design choice.** The embedding harness ranks the same jobs under all three strategies; `--weight` runs the same CV before and after a weight change, where component scores must stay identical and only totals and order move; the explanation checks were run against the live model (11 of 15 accepted, all 4 rejections correct).

Limits: one rater (the author), 20 judgements, 11 jobs all labelled senior, and no on-site jobs in the judged set, so the remote filter is covered by tests rather than by judgement.

## 5. Personal data

| Data | Where | Kept for |
|---|---|---|
| Username, email, password hash | `auth_user` | Until the account is deleted |
| Full extracted CV text, original filename | `CV.extracted_text`, `CV.original_filename` | Until the CV or account is deleted |
| The uploaded file | **Not stored** by the upload page — only the text. (`CV.file` exists, and `delete_file()` removes a stored file.) | — |
| Extracted profile: skills, seniority, years of experience | `CVProfile` | Until the CV is deleted (cascade) |
| Profile embedding — includes the first 400 characters of the CV, usually name and contact details | `CVProfile.embedding` | Until the CV is deleted (cascade) |
| Skill strings from a CV that aren't in the vocabulary | New `Skill` rows (`is_auto_created=True`), shared and visible to admins | **Not deleted with the CV** |

Processing: the CV text (first 4,000 characters) goes to the LLM and the profile text to the embedder. Both default to local Ollama, so nothing leaves the machine; pointing `LLM_BASE_URL` at a hosted API would send CV text to that provider. Explanations receive only computed facts, never CV text. Logs never contain CV text or filenames; on an LLM parse failure up to 200 characters of the model's output are logged, which for a CV can include extracted skill names.

**There is no retention limit yet.** CVs and profiles are kept until deleted, and there's no user-facing delete. Before real users: add a "delete my CV" action, an automatic expiry (for example 90 days after last use), and drop the CV snippet from `CVProfile.embed_text()` so the vector carries no contact details.
