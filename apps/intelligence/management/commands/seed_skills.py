from django.core.management.base import BaseCommand
from apps.intelligence.fixtures.skills_seed import SKILLS
from apps.intelligence.models import Skill, SkillAlias
from apps.intelligence.utils import normalize_skill


class Command(BaseCommand):
    help = 'Seed the Skill and SkillAlias tables from fixtures/skills_seed.py'

    def handle(self, *args, **options):
        created_skills = skipped_skills = created_aliases = 0

        for canonical_name, category, aliases in SKILLS:
            key = normalize_skill(canonical_name)
            skill, created = Skill.objects.get_or_create(
                normalised_name=key,
                defaults={'name': canonical_name, 'category': category, 'is_auto_created': False},
            )
            if created:
                created_skills += 1
            else:
                skipped_skills += 1

            # Always ensure the canonical name itself is an alias
            for raw in [canonical_name] + aliases:
                norm = normalize_skill(raw)
                _, alias_created = SkillAlias.objects.get_or_create(
                    normalised=norm,
                    defaults={'skill': skill, 'alias': raw},
                )
                if alias_created:
                    created_aliases += 1

        self.stdout.write(
            f"Done — skills created: {created_skills}, skipped: {skipped_skills}, "
            f"aliases created: {created_aliases}"
        )
