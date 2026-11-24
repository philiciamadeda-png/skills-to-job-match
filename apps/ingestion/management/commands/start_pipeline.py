from celery import chain
from django.core.management.base import BaseCommand

from apps.ingestion.tasks import task_ingest_jobs, task_transform_jobs
from apps.intelligence.tasks import task_embed_jobs, task_extract_jobs


def pipeline():
    """Every stage once, in order: ingest both sources, transform, extract, embed.
    Transform and extraction queue the dashboard refresh themselves."""
    return chain(
        task_ingest_jobs.si('remotive'),
        task_ingest_jobs.si('arbeitnow', max_pages=3),
        task_transform_jobs.si(),
        task_extract_jobs.si(),
        task_embed_jobs.si(),
    )


class Command(BaseCommand):
    help = ("Queue the whole job pipeline once, without waiting for Beat. "
            "Runs automatically after the first deploy (render.yaml initialDeployHook).")

    def handle(self, *args, **options):
        result = pipeline().apply_async()
        self.stdout.write(f'Queued ingest → transform → extract → embed ({result.id}). '
                          'A running worker picks it up; watch its log.')
