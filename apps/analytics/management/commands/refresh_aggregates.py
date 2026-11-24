from django.core.management.base import BaseCommand

from apps.analytics.services import refresh_aggregates


class Command(BaseCommand):
    help = 'Rebuild the dashboard aggregation tables from the current jobs'

    def handle(self, *args, **options):
        counts = refresh_aggregates()
        self.stdout.write(', '.join(f'{k}: {v}' for k, v in counts.items()))
