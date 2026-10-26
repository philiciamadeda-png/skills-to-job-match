import re
from django.core.management.base import BaseCommand
from apps.intelligence.models import Job

# Order matters — more specific patterns first
RULES = [
    ("intern",    re.compile(r"\b(intern|internship|werkstudent|studentische|ausbildung|trainee)\b", re.I)),
    ("junior",    re.compile(r"\b(junior|jr\.?|entry.?level|associate)\b", re.I)),
    ("principal", re.compile(r"\b(principal|staff|distinguished|fellow)\b", re.I)),
    ("lead",      re.compile(r"\b(lead|tech lead|team lead|teamlei[dt])\b", re.I)),
    ("manager",   re.compile(r"\b(manager|head of|director|vp |vice president)\b", re.I)),
    ("senior",    re.compile(r"\b(senior|sr\.?)\b", re.I)),
    ("mid",       re.compile(r"\b(mid.?level|medior|confirmed)\b", re.I)),
]


def infer_seniority(title: str) -> str:
    for label, pattern in RULES:
        if pattern.search(title):
            return label
    return "not_stated"


class Command(BaseCommand):
    help = "Backfill seniority on jobs where it is blank, using title regex rules."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        qs = Job.objects.filter(seniority="")
        updated = 0
        bulk = []
        for job in qs.only("id", "title", "seniority"):
            label = infer_seniority(job.title)
            job.seniority = label
            bulk.append(job)

        if not options["dry_run"]:
            Job.objects.bulk_update(bulk, ["seniority"], batch_size=500)
            updated = len(bulk)

        self.stdout.write(f"{'[dry-run] would update' if options['dry_run'] else 'Updated'} {len(bulk)} jobs.")
        if options["dry_run"]:
            from collections import Counter
            counts = Counter(infer_seniority(j.title) for j in qs.only("title"))
            for label, n in counts.most_common():
                self.stdout.write(f"  {label}: {n}")
