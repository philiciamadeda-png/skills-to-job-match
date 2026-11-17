I need to decide what text represents a job when I embed it for CV-to-job matching in my Django app. I want a **comparison harness** so I can see the difference between three strategies myself. **Do not pick a winner for me and do not rank the strategies** — build a tool that puts the results side by side, and I'll inspect them and decide.

**What I have**

`Job` (`apps/intelligence/models.py`): `title`, `description` (raw text, may contain HTML), `seniority`, `extraction_status`, and skills via `JobSkill` → canonical `Skill.name` (resolved through `resolve_skill()`, so "Postgres" is stored as "PostgreSQL").

Embeddings come from `nomic-embed-text` on local Ollama (`POST http://localhost:11434/api/embed`, `{"model": ..., "input": ...}`), 768 dimensions. No paid API.

**The three strategies to compare**

| Name | Text fed to the embedder |
|---|---|
| `full_description` | the whole description, HTML stripped — benefits, boilerplate, EEO statements and all |
| `skills_only` | comma-joined canonical skill names |
| `title_skills` | `{title} \| {seniority} \| skills: {skills} \| {first 400 chars of description}` |

**What the harness should do**

1. Take the same N jobs (default 10) for all three strategies — jobs with `extraction_status='success'` and at least one skill, chosen deterministically so reruns use the same jobs.
2. Embed each job under each strategy, and embed a free-text query I pass in.
3. Rank the jobs by cosine similarity to the query, separately per strategy.
4. Print the three rankings side by side: rank, score, job id and title, so I can see where the same job lands under each strategy.
5. Print the **exact text** that was embedded for each job under each strategy (truncated is fine), so I can see *why* a job scored the way it did — for example a job ranking high on culture or benefits text rather than on the work.
6. Run as a standalone script (`apps/intelligence/eval/compare_embedding_strategies.py`) with `--query`, `--n` and `--top` flags. No writes to the database — this is read-only exploration, not the production embedding step.

**What I'm going to look for**, so the output should make these easy to spot:
- two unrelated jobs scoring close together under `full_description` because their descriptions share company boilerplate
- `skills_only` collapsing different roles that share a common skill (e.g. "Python" for data engineering vs web backend)
- whether `title_skills` keeps the right jobs near the top when the extraction is good, and what happens when it isn't

Show me the script and how to run it. Don't include a recommendation in the output or in your answer.
