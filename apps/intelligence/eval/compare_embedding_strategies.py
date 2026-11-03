"""
Embedding strategy comparison harness.

Embeds up to N jobs under three strategies and runs a free-text query against
each, printing ranked results side-by-side so you can judge which strategy
surfaces the most relevant jobs.

Strategies
----------
A  full_description   Raw job description (everything — boilerplate included)
B  skills_only        Comma-joined canonical skill names from JobSkill
C  title_skills       "{title} | {seniority} | skills: {skills} | {first 400 chars of description}"

Usage
-----
DJANGO_SETTINGS_MODULE=config.settings.local PYTHONPATH=. \
  python apps/intelligence/eval/compare_embedding_strategies.py \
  --query "Python data engineer with Spark and AWS" \
  --n 10 --top 5
"""
from __future__ import annotations

import argparse
import os
import sys
import textwrap

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
django.setup()

import requests  # noqa: E402  (after django.setup)
from apps.intelligence.models import Job  # noqa: E402

OLLAMA_EMBED_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"
STRATEGIES = ("full_description", "skills_only", "title_skills")


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed(text: str) -> list[float]:
    resp = requests.post(OLLAMA_EMBED_URL, json={"model": EMBED_MODEL, "input": text}, timeout=30)
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------
# Text builders — one per strategy
# ---------------------------------------------------------------------------

def text_full_description(job: Job) -> str:
    return job.description


def text_skills_only(job: Job) -> str:
    skills = list(job.skills.values_list("name", flat=True))
    return ", ".join(skills) if skills else job.title


def text_title_skills(job: Job) -> str:
    skills = list(job.skills.values_list("name", flat=True))
    parts = [job.title]
    if job.seniority:
        parts.append(job.seniority)
    if skills:
        parts.append("skills: " + ", ".join(skills))
    # short requirements snippet — first 400 chars of description
    snippet = job.description[:400].replace("\n", " ").strip()
    if snippet:
        parts.append(snippet)
    return " | ".join(parts)


TEXT_BUILDERS = {
    "full_description": text_full_description,
    "skills_only": text_skills_only,
    "title_skills": text_title_skills,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(query: str, n: int, top: int) -> None:
    jobs = list(
        Job.objects.filter(skills__isnull=False)
        .distinct()
        .prefetch_related("skills")
        .select_related("company")[:n]
    )
    if not jobs:
        print("No jobs with skills found. Run extraction first.")
        return

    print(f"\nEmbedding {len(jobs)} jobs under 3 strategies using {EMBED_MODEL}...")

    # Build corpus embeddings per strategy
    corpus: dict[str, list[tuple[Job, list[float], str]]] = {}
    for strategy in STRATEGIES:
        builder = TEXT_BUILDERS[strategy]
        rows = []
        for job in jobs:
            text = builder(job)
            vec = embed(text)
            rows.append((job, vec, text))
        corpus[strategy] = rows
        print(f"  {strategy}: done")

    # Embed the query once (same model, same space)
    query_vec = embed(query)
    print(f"\nQuery: \"{query}\"\n")
    print("=" * 80)

    for strategy in STRATEGIES:
        rows = corpus[strategy]
        scored = sorted(rows, key=lambda r: cosine(query_vec, r[1]), reverse=True)[:top]

        print(f"\nStrategy: {strategy.upper()}")
        print("-" * 60)
        for rank, (job, _, text) in enumerate(scored, 1):
            score = cosine(query_vec, embed(text))  # reuse already-computed vec
            company = job.company.name if job.company else "?"
            skills = ", ".join(job.skills.values_list("name", flat=True))
            print(f"  {rank}. [{score:.3f}] {job.title} @ {company}")
            print(f"       skills: {skills or '—'}")
            # show what the strategy actually fed to the embedder
            preview = text[:120].replace("\n", " ")
            print(f"       text fed: {textwrap.shorten(preview, 110)}")

    print("\n" + "=" * 80)
    print("\nWhat to look for:")
    print("  full_description — watch for unrelated jobs scoring high due to shared boilerplate")
    print("  skills_only      — relevant jobs may rank low if skills are sparse or generic")
    print("  title_skills     — should give the best signal-to-noise for job matching")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare embedding strategies for job matching")
    parser.add_argument("--query", required=True, help="Free-text query representing a CV or skill set")
    parser.add_argument("--n", type=int, default=10, help="Number of jobs to embed (default 10)")
    parser.add_argument("--top", type=int, default=5, help="Top N results to show per strategy (default 5)")
    args = parser.parse_args()
    run(args.query, args.n, args.top)
