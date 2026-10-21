import html
import json
import re

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.models import RawJobPayload
from apps.intelligence.prompts import render_extraction_prompt


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", html.unescape(text)).strip()


class Command(BaseCommand):
    help = "Extract job details via LLM. Use --dry-run to print prompt and response without saving."

    def add_arguments(self, parser):
        parser.add_argument("--job-id", required=True, type=int)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        job_id = options["job_id"]

        try:
            payload = RawJobPayload.objects.get(id=job_id)
        except RawJobPayload.DoesNotExist:
            raise CommandError(f"No RawJobPayload with id={job_id}")

        desc = strip_html(payload.raw_data.get("description", ""))[:2000]
        prompt = render_extraction_prompt(desc)

        self.stdout.write("\n=== RENDERED PROMPT ===\n")
        self.stdout.write(prompt)

        if options["dry_run"]:
            self.stdout.write("\n=== DRY RUN — no model call made ===\n")
            return

        from apps.intelligence.llm.client import LLMClient, LLMMessage

        client = LLMClient()
        resp = client.chat([
            LLMMessage(role="system", content="You are a job data extractor."),
            LLMMessage(role="user", content=prompt),
        ])

        self.stdout.write("\n=== RAW MODEL RESPONSE ===\n")
        self.stdout.write(resp.content)
        self.stdout.write(f"\n\ntokens_in={resp.tokens_in} tokens_out={resp.tokens_out} cost_usd={resp.cost_usd}\n")
