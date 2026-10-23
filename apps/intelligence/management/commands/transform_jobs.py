from django.core.management.base import BaseCommand
from apps.intelligence.services import transform_raw_payloads


class Command(BaseCommand):
    help = 'Transform unprocessed RawJobPayload rows into Job/Company/Location records'

    def add_arguments(self, parser):
        parser.add_argument('--batch-size', type=int, default=200)

    def handle(self, *args, **options):
        counts = transform_raw_payloads(batch_size=options['batch_size'])
        self.stdout.write(
            f"Done — created: {counts['created']}, skipped: {counts['skipped']}, failed: {counts['failed']}"
        )
