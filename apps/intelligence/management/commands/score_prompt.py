from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.intelligence.eval.run_eval import run_eval, RESULTS_DIR
import json
from datetime import datetime, timezone


class Command(BaseCommand):
    help = "Score a prompt version against the hand-labelled eval set."

    def add_arguments(self, parser):
        parser.add_argument("--prompt-version", required=True, dest="version", help="e.g. v1, v2, v3")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        version = options["version"]
        prompt_path = Path("apps/intelligence/prompts") / f"extract_job_details_{version}.md"
        if not prompt_path.exists():
            raise CommandError(f"Prompt file not found: {prompt_path}")

        self.stdout.write(f"Scoring {prompt_path} ...")
        results = run_eval(dry_run=options["dry_run"], prompt_path=prompt_path)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = RESULTS_DIR / f"{timestamp}_extract_job_details_{version}.json"
        out_path.write_text(json.dumps(results, indent=2))

        self.stdout.write("\n=== SUMMARY ===")
        self.stdout.write(json.dumps(results["summary"], indent=2))
        self.stdout.write(f"\nResults written to {out_path}")
