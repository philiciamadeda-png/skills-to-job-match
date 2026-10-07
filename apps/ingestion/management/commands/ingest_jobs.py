from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.services import ingest_from_source
from apps.ingestion.sources.remotive import RemotiveSource

SOURCES = {
    'remotive': RemotiveSource,
}


class Command(BaseCommand):
    help = 'Ingest job listings from a source into RawJobPayload'

    def add_arguments(self, parser):
        parser.add_argument('--source', required=True, choices=SOURCES.keys())
        parser.add_argument('--limit', type=int, default=None)

    def handle(self, *args, **options):
        source_cls = SOURCES[options['source']]
        source = source_cls(limit=options['limit'])

        try:
            jobs = source.fetch_all()
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        result = ingest_from_source(source.source_name, jobs)
        self.stdout.write(
            f"Done — total: {result['total']}, saved: {result['saved']}, skipped: {result['skipped']}"
        )
