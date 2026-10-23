"""
Report auto-created Skill rows ordered by job frequency.

These are skills the LLM returned that had no match in the canonical
vocabulary or alias table. Read the top results and decide for each:

  - Alias of an existing skill  → python manage.py add_skill_alias
  - Genuinely new skill         → add to fixtures/skills_seed.py and re-run seed_skills
  - Noise / not a real skill    → python manage.py add_skill_alias --delete

Usage:
    python manage.py report_new_skills
    python manage.py report_new_skills --limit 100
    python manage.py report_new_skills --min-jobs 2
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.intelligence.models import Skill


class Command(BaseCommand):
    help = 'Report auto-created skills ordered by job frequency.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50)
        parser.add_argument('--min-jobs', type=int, default=1,
                            help='Only show skills linked to at least this many jobs')

    def handle(self, *args, **options):
        qs = (
            Skill.objects.filter(is_auto_created=True)
            .annotate(job_count=Count('jobskill'))
            .filter(job_count__gte=options['min_jobs'])
            .order_by('-job_count', 'name')
            [:options['limit']]
        )

        if not qs:
            self.stdout.write('No auto-created skills found.')
            return

        self.stdout.write(f"\n{'jobs':>5}  {'normalised_name':<30}  raw name")
        self.stdout.write('-' * 70)
        for skill in qs:
            self.stdout.write(f"{skill.job_count:>5}  {skill.normalised_name:<30}  {skill.name}")

        self.stdout.write(f"\nTotal shown: {len(qs)}")
        self.stdout.write(
            "\nNext steps:\n"
            "  Alias an existing skill : python manage.py add_skill_alias \"<raw>\" --canonical \"<canonical>\"\n"
            "  Delete noise            : python manage.py add_skill_alias \"<raw>\" --delete\n"
            "  New canonical skill     : add to fixtures/skills_seed.py, then python manage.py seed_skills\n"
        )
