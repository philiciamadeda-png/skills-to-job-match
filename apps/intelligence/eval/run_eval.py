"""
Evaluation script: measures extraction prompt quality against the hand-labelled
eval set at apps/intelligence/fixtures/eval_set.json.

Usage:
    python manage.py shell < apps/intelligence/eval/run_eval.py
    # or
    python apps/intelligence/eval/run_eval.py  (with DJANGO_SETTINGS_MODULE set)

Results are written to apps/intelligence/eval/results/<timestamp>.json
so prompt versions can be compared over time.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Django setup (allows running as a plain script)
# ---------------------------------------------------------------------------
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django  # noqa: E402
django.setup()

from apps.intelligence.prompts import render_extraction_prompt  # noqa: E402
from apps.intelligence.llm.client import LLMClient, LLMMessage, LLMResponse  # noqa: E402
from apps.intelligence.schemas import JobExtractionResult  # noqa: E402
from apps.intelligence.utils import normalize_skill  # noqa: E402
from apps.intelligence.services import resolve_skill  # noqa: E402
from apps.ingestion.models import RawJobPayload  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FIXTURE_PATH = Path(__file__).parents[3] / "apps" / "intelligence" / "fixtures" / "eval_set.json"
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", html.unescape(text)).strip()


def _resolve_to_canonical(skill: str) -> str:
    """
    Resolve a raw skill string to its canonical name via the DB alias table.
    Falls back to character-level normalisation if Django ORM is unavailable
    (e.g. dry-run without DB).
    """
    try:
        return resolve_skill(skill).normalised_name
    except Exception:
        return normalize_skill(skill)


def compare_skills(expected: list[str], predicted: list[str]) -> dict:
    exp_norm = {_resolve_to_canonical(s) for s in expected}
    pred_norm = {_resolve_to_canonical(s) for s in predicted}

    if not exp_norm:
        # Non-technical job — any prediction is a false positive
        return {
            "recall": None,  # undefined when there are no expected skills
            "false_positives": len(pred_norm),
        }

    hits = exp_norm & pred_norm
    return {
        "recall": round(len(hits) / len(exp_norm), 3),
        "false_positives": len(pred_norm - exp_norm),
    }


_CONTRACT_NORMALISE = {
    "werkstudent": "part_time",
    "part-time": "part_time",
    "full-time": "full_time",
    "permanent": "full_time",
    "freelancer": "freelance",
}


def _repair_contract_type(raw_json: str) -> str:
    """Replace known invalid contract_type values before Pydantic validation."""
    def replacer(m):
        val = m.group(1).lower()
        mapped = _CONTRACT_NORMALISE.get(val)
        return f'"contract_type": "{mapped}"' if mapped else m.group(0)
    return re.sub(r'"contract_type":\s*"([^"]+)"', replacer, raw_json)


def call_llm(description: str, client: LLMClient, prompt_path: Path | None = None) -> tuple[JobExtractionResult | None, str, dict]:
    """Returns (parsed_result, raw_content, usage_dict). parsed_result is None on schema failure."""
    if prompt_path:
        template = prompt_path.read_text()
        prompt = template.replace("{job_description}", description[:2000])
    else:
        prompt = render_extraction_prompt(description[:2000])
    resp: LLMResponse = client.chat([
        LLMMessage(role="system", content="You are a job data extractor."),
        LLMMessage(role="user", content=prompt),
    ])
    raw = resp.content
    usage = {"tokens_in": resp.tokens_in, "tokens_out": resp.tokens_out, "cost_usd": resp.cost_usd}

    # Strip markdown fences if present
    raw_stripped = re.sub(r"```(?:json)?", "", raw).strip()
    # Extract JSON even if the model wraps it in prose or markdown fences
    match = re.search(r"\{.*\}", raw_stripped, re.DOTALL)
    if not match:
        # Try to repair truncated JSON by closing open braces
        open_count = raw_stripped.count("{") - raw_stripped.count("}")
        candidate = raw_stripped[raw_stripped.find("{"):] + "}" * open_count if "{" in raw_stripped and open_count > 0 else None
        if not candidate:
            return None, raw, usage
        raw_json = candidate
    else:
        raw_json = match.group()

    try:
        parsed = JobExtractionResult.model_validate_json(_repair_contract_type(raw_json))
        return parsed, raw, usage
    except Exception:
        return None, raw, usage


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

def run_eval(dry_run: bool = False, prompt_path: Path | None = None) -> dict:
    labels = json.loads(FIXTURE_PATH.read_text())
    label_map = {str(item["id"]): item for item in labels}

    # Load raw descriptions
    ids = [int(k) for k in label_map]
    payloads = {str(p.id): p for p in RawJobPayload.objects.filter(id__in=ids)}

    client = LLMClient()

    scalar_fields = ["seniority", "contract_type", "remote_status"]
    scalar_correct: dict[str, int] = {f: 0 for f in scalar_fields}
    scalar_total: dict[str, int] = {f: 0 for f in scalar_fields}

    skill_recalls: list[float] = []
    total_false_positives = 0
    schema_failures = 0
    total_cost = 0.0
    per_job = []

    for label in labels:
        job_id = str(label["id"])
        payload = payloads.get(job_id)
        if not payload:
            print(f"  SKIP {job_id} — not in DB")
            continue

        desc = strip_html(payload.raw_data.get("description", ""))
        print(f"  Running {job_id}: {label['title'][:60]}")

        if dry_run:
            # Map fixture values to schema enum values
            _CONTRACT_MAP = {
                "part-time student": "part_time",
                "full-time": "full_time",
                "part-time": "part_time",
            }

            def _ns(v):
                if v in (None, "not stated", "not_stated"):
                    return "not_stated"
                if isinstance(v, str) and v.endswith("+"):
                    return int(v[:-1])
                return _CONTRACT_MAP.get(v, v)

            remote_raw = label.get("remote")
            if remote_raw is True:
                remote_val = "remote"
            elif remote_raw is False:
                remote_val = "on_site"
            else:
                remote_val = "not_stated"

            result = JobExtractionResult(
                required_skills=label.get("skills", []),
                seniority=_ns(label.get("seniority")),
                years_required=_ns(label.get("years_required")),
                remote_status=remote_val,
                contract_type=_ns(label.get("contract_type")),
            )
            raw, usage = "DRY RUN", {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
        else:
            result, raw, usage = call_llm(desc, client, prompt_path=prompt_path)
            total_cost += usage["cost_usd"]

        if result is None:
            schema_failures += 1
            per_job.append({"id": job_id, "title": label["title"], "schema_failure": True, "raw": raw[:300]})
            continue

        def _norm_remote(v):
            if v is True:
                return "remote"
            if v is False:
                return "on_site"
            if v in (None, "not stated", "not_stated"):
                return "not_stated"
            return v

        def _norm_label(field, v):
            if field == "remote_status":
                return _norm_remote(v)
            if field == "contract_type":
                return {"full-time": "full_time", "part-time": "part_time",
                        "part-time student": "part_time"}.get(str(v), str(v))
            if field == "seniority":
                return {"not stated": "not_stated"}.get(str(v), str(v))
            return str(v)

        # Scalar fields
        field_map = {
            "seniority": ("seniority", result.seniority.value if result.seniority else None),
            "contract_type": ("contract_type", result.contract_type.value if result.contract_type else None),
            "remote_status": ("remote", result.remote_status.value if result.remote_status else None),
        }
        scalar_results = {}
        for field, (label_key, pred_val) in field_map.items():
            expected = label.get(label_key)
            if expected is not None:
                expected = _norm_label(field, expected)
                scalar_total[field] += 1
                match = str(expected) == str(pred_val)
                if match:
                    scalar_correct[field] += 1
                scalar_results[field] = {"expected": expected, "predicted": pred_val, "match": match}

        # Skills
        expected_skills = label.get("skills", [])
        predicted_skills = list(result.required_skills) + list(result.nice_to_have_skills)
        skill_result = compare_skills(expected_skills, predicted_skills)
        if skill_result["recall"] is not None:
            skill_recalls.append(skill_result["recall"])
        total_false_positives += skill_result["false_positives"]

        per_job.append({
            "id": job_id,
            "title": label["title"],
            "schema_failure": False,
            "scalars": scalar_results,
            "skills": skill_result,
            "predicted_skills": predicted_skills,
            "expected_skills": expected_skills,
        })

    n = len(labels)
    summary = {
        "total": n,
        "prompt": str(prompt_path) if prompt_path else "default",
        "schema_failure_rate": round(schema_failures / n, 3) if n else 0,
        "scalar_accuracy": {
            f: round(scalar_correct[f] / scalar_total[f], 3) if scalar_total[f] else None
            for f in scalar_fields
        },
        "skill_recall_mean": round(sum(skill_recalls) / len(skill_recalls), 3) if skill_recalls else None,
        "total_false_positives": total_false_positives,
        "total_cost_usd": round(total_cost, 6),
    }

    return {"summary": summary, "per_job": per_job}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv

    prompt_path = None
    for arg in sys.argv[1:]:
        if arg.startswith("--prompt="):
            prompt_path = Path(arg.split("=", 1)[1])
            if not prompt_path.exists():
                print(f"ERROR: prompt file not found: {prompt_path}")
                sys.exit(1)

    print(f"Running eval (dry_run={dry_run}, prompt={prompt_path or 'default'})...")
    results = run_eval(dry_run=dry_run, prompt_path=prompt_path)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prompt_tag = prompt_path.stem if prompt_path else "default"
    out_path = RESULTS_DIR / f"{timestamp}_{prompt_tag}.json"
    out_path.write_text(json.dumps(results, indent=2))

    print("\n=== SUMMARY ===")
    print(json.dumps(results["summary"], indent=2))
    print(f"\nFull results written to {out_path}")
