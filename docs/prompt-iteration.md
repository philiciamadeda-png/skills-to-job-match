# Prompt Iteration Log — LLM Skill Extraction

## Setup

**Eval set:** 20 hand-labelled job descriptions from two sources (Remotive, Arbeitnow). Jobs span English, German, and French. Mix of technical roles (Python/Django, .NET, SAP), non-technical roles (marketing, retail, reception), and edge cases (image-only descriptions, double-HTML-encoded text, Werkstudent roles).

**Model:** llama3.2 via local Ollama (OpenAI-compatible endpoint). Zero cost per run.

**Metrics collected per run:**
- `skill_recall_mean` — fraction of labelled skills the model found, averaged across jobs that have expected skills. **Headline metric** — missing a required skill excludes a candidate wrongly.
- `total_false_positives` — skill strings returned that were not in the label. Lower is better but secondary to recall.
- `seniority_accuracy`, `contract_type_accuracy`, `remote_status_accuracy` — exact match rate on scalar fields.
- `schema_failure_rate` — fraction of jobs where the model returned output that failed Pydantic validation entirely.

**Why recall is the headline metric:** for job matching, a false negative (missing a required skill) wrongly excludes a candidate. A false positive (extra skill) is less damaging — it may cause a weak match but not a missed one. Sort prompt versions by recall; use false positives as a tiebreaker.

---

## Scorecard

| Version | skill_recall | false_positives | seniority_acc | contract_acc | remote_acc | schema_failures |
|---------|-------------|-----------------|---------------|--------------|------------|-----------------|
| v1      | 0.200       | 40              | 0.526         | 0.474        | 0.579      | 1/20            |
| v2      | **0.400**   | 60              | 0.421         | 0.316        | 0.368      | 1/20            |
| v3      | 0.178       | **17**          | **0.526**     | **0.579**    | 0.474      | 1/20            |

No single version dominates. v2 has the best recall; v3 has the best false-positive count and scalar accuracy. The schema failure (job 726) is persistent across all versions — the model returns `"home office"` or empty strings for `remote_status`, which are not valid enum values.

---

## v1 — Baseline

**File:** `apps/intelligence/prompts/extract_job_details_v1.md`

**What it contains:**
- Schema definition with all six fields
- Rules section covering skills, seniority, years, remote status, contract type, and language handling
- Two few-shot examples: a clear technical role and a vague soft-skills role

**Scores:** recall 0.200, FP 40, schema failures 1

**Failure analysis after reading per-job output:**

The dominant failure was the model returning **phrases and sentences as skill entries** rather than technology names:

- Job 638 (German electrical role): predicted `["Abgeschlossene Ausbildung im elektrotechnischen Bereich", "Mehrjährige Berufserfahrung in ähnlicher Position", "gute elektrische Kenntnisse"]` — these are full German sentences, not skills
- Job 601 (French electrical engineer): predicted `["Modélisation BIM - REVIT", "Réalisation de schémas de principe"]` instead of `["BIM", "Revit"]`
- Job 811 (French cybersecurity): predicted `["Administration Windows", "Expertise antivirus/EDR"]` instead of `["Windows"]`
- Job 1 (AI Code Trainer): predicted `["Software Engineering", "Debugging & Code Review", "Algorithms"]` — abstract competencies, not skills

This caused both the high false-positive count (40) and the low recall (0.200): the model extracted the right concepts but wrapped them in phrases that didn't match the expected short names after normalisation.

**Hypothesis:** adding an explicit constraint that skill entries must be short names (1–3 words) will force the model to extract `"BIM"` and `"Revit"` instead of `"Modélisation BIM - REVIT"`, recovering those recall misses while also reducing false positives.

---

## v2 — Short-name constraint

**File:** `apps/intelligence/prompts/extract_job_details_v2.md`

**One change from v1:** added one sentence to the Skills rule:

> A skill entry must be a short technology or tool name — 1 to 3 words maximum (e.g. "Python", "React", "PostgreSQL", "SAP BTP", "Cortex XDR"). Never write a phrase, sentence, or soft skill (e.g. do NOT write "Debugging & Code Review", "Administration Windows", "Modélisation BIM - REVIT" — write "Windows", "BIM", "Revit" instead).

**Scores:** recall 0.400 (+0.200), FP 60 (+20), seniority 0.421 (-0.105), contract 0.316 (-0.158), remote 0.368 (-0.211)

**What happened:**

Recall doubled — the constraint worked for technical jobs. The model now correctly extracts `"BIM"`, `"Revit"`, `"Windows"` as short names, recovering the recall misses from v1.

But false positives increased and scalar accuracy collapsed. Two new failure patterns appeared:

1. **Non-technical jobs became noisier.** Job 283 (Performance Marketing) went from 0 FP to 18 FP — the model now lists `["Meta", "Google", "Search", "Facebook", "Instagram", "TikTok", "Content Calendar", "SEO Tools", "A/B Testing"]`. The short-name rule made it more extractive across the board, not just for technical skills.

2. **Scalar fields regressed.** The schema failure for job 726 now returns empty strings `""` for all enum fields instead of `"not_stated"`. Several jobs that previously returned correct scalar values now return `not_stated` more aggressively. The additional instruction text may have shifted the model's attention away from scalar fields.

**Hypothesis:** the false-positive explosion on non-technical jobs needs a negative example — showing the model a marketing role where the correct output has empty skill lists, explicitly noting that advertising platforms and channels are not skills.

---

## v3 — Negative example for non-technical roles

**File:** `apps/intelligence/prompts/extract_job_details_v3.md`

**One change from v2:** added a third few-shot example — a Senior Performance Marketing Manager role — with empty skill lists and an explicit note:

> Note: Meta, Google, Instagram, TikTok, Facebook Ads, Google Ads are advertising platforms and channels, not software engineering skills. They do not belong in the skill lists.

**Scores:** recall 0.178 (-0.222 vs v2), FP 17 (-43 vs v2), seniority 0.526, contract 0.579, remote 0.474

**What happened:**

False positives dropped sharply (60 → 17) — the negative example worked. The model now correctly returns empty skill lists for marketing, retail, and management roles.

Scalar accuracy recovered to v1 levels or better (contract_type 0.579 is the best across all versions).

But recall dropped back below v1. The model over-applied the negative example's lesson: it became more conservative on technical jobs too, returning empty skill lists for jobs that do have real skills. Job 742 (Finance Manager, expected `["Excel", "DATEV"]`) still returns empty — the model treats domain tools as non-skills.

**The tension:** v2 and v3 are trading recall against precision. The short-name rule (v2) makes the model more extractive; the negative example (v3) makes it more conservative. They partially cancel each other out.

---

## What I would try next with more time

**v4 hypothesis — domain tool positive example:**

The core unresolved problem is that the model doesn't know where to draw the line between "advertising platform" (not a skill) and "domain tool" (is a skill). The negative example in v3 shows advertising platforms. What's missing is a positive example showing domain tools — Excel, DATEV, BIM, Revit — that are not software engineering skills but are still extractable.

Proposed addition: a fourth example — a Finance Manager role — with `["Excel", "DATEV"]` as required skills and an explicit note:

> Note: Excel and DATEV are domain-specific tools that belong in the skill list even though they are not software engineering skills. The distinction is: tools a candidate must know how to operate (Excel, DATEV, BIM, Revit, SAP) belong in skills; channels and platforms they manage (Meta, Google Ads, TikTok) do not.

This directly addresses the recall miss on job 742 and the false-positive pattern on job 283 simultaneously, without adding a new rule that might have unintended side effects.

**v5 hypothesis — fix the persistent schema failure:**

Job 726 fails schema validation on every version because the model returns `"home office"` or `""` for `remote_status`. The prompt already says `"home office"` maps to `remote`, but the model ignores it. A targeted fix: add `"home office"` explicitly to the remote_status rule as a mapped value, and add a note that empty strings are never valid — use `"not_stated"` instead.

**Longer-term — separate prompts by job category:**

The eval set contains technical jobs, non-technical jobs, and edge cases (image-only, double-encoded HTML, non-English). A single prompt trying to handle all three is fighting itself. With more time: classify the job first (technical / non-technical / unreadable), then route to a specialised prompt. The unreadable category (jobs 437, 794) should short-circuit to `not_stated` on all fields without an LLM call.

---

## Known failure modes — where the model is confidently wrong

These pass schema validation and are still wrong. No prompt change will catch them:

1. **Seniority inferred from context, not stated.** Job 811 (French cybersecurity): expected `mid`, got `senior`. The description mentions "expertise" and "complex environments" — the model infers senior from tone. The label says mid because no seniority label appears in the text.

2. **`not_stated` used as a cop-out on clearly stated fields.** Jobs 164, 283, 487 all have obvious contract and remote signals (`"100% remote"` in the title, `"full-time permanent"` in the body) that the model returns as `not_stated`. This is the most damaging failure for matching — a remote job marked `not_stated` won't surface in a remote-only search.

3. **Skills placed in the wrong list.** The model sometimes puts required skills in `nice_to_have_skills` and vice versa. Schema validation cannot catch this — both are lists of strings.

4. **Non-English jobs.** German and French jobs have consistently lower scalar accuracy across all versions. The model reads them correctly (it understands the languages) but maps German/French contract and seniority signals to the wrong enum values. "Festanstellung" (permanent employment) should be `full_time`; the model often returns `not_stated`.

---

## Eval infrastructure

- **Eval set:** `apps/intelligence/fixtures/eval_set.json` — 20 hand-labelled jobs
- **Run script:** `apps/intelligence/eval/run_eval.py --prompt=<path>`
- **Management command:** `python manage.py score_prompt --prompt-version v1`
- **Results:** `apps/intelligence/eval/results/<timestamp>_<prompt_version>.json`
- **Skill normalisation in eval:** both expected and predicted skills are run through `resolve_skill()` before comparison, so "React.js" and "React" match correctly
