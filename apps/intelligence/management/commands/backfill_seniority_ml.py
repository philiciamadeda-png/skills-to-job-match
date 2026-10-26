from django.core.management.base import BaseCommand
from apps.intelligence.models import Job
from apps.intelligence.ml_service import predict_seniority


class Command(BaseCommand):
    help = "Use the trained ML model to fill seniority on jobs labelled not_stated."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        qs = Job.objects.filter(seniority='not_stated').only('id', 'title', 'description')
        bulk, counts = [], {}

        for job in qs:
            label = predict_seniority(job.title, job.description)
            job.seniority = label
            bulk.append(job)
            counts[label] = counts.get(label, 0) + 1

        if not options['dry_run']:
            Job.objects.bulk_update(bulk, ['seniority'], batch_size=500)

        prefix = '[dry-run] ' if options['dry_run'] else ''
        self.stdout.write(f"{prefix}Processed {len(bulk)} jobs:")
        for label, n in sorted(counts.items(), key=lambda x: -x[1]):
            self.stdout.write(f"  {label}: {n}")
