from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.services import ingest_from_source
from apps.ingestion.sources.remotive import RemotiveSource
from apps.ingestion.sources.arbeitnow import ArbeitnowSource

SOURCES = {
    'remotive': RemotiveSource,
    'arbeitnow': ArbeitnowSource,
}


class Command(BaseCommand):
    help = 'Ingest job listings from a source into RawJobPayload'

    def add_arguments(self, parser):
        parser.add_argument('--source', required=True, choices=SOURCES.keys())
        parser.add_argument('--limit', type=int, default=None)
        parser.add_argument('--max-pages', type=int, default=None)

    def handle(self, *args, **options):
        source_cls = SOURCES[options['source']]
        kwargs = {}
        if options['limit'] is not None:
            kwargs['limit'] = options['limit']
        if options['max_pages'] is not None:
            kwargs['max_pages'] = options['max_pages']
        source = source_cls(**kwargs)

        try:
            jobs = source.fetch_all()
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        result = ingest_from_source(source.source_name, jobs)
        self.stdout.write(
            f"Done — total: {result['total']}, saved: {result['saved']}, skipped: {result['skipped']}"
        )
