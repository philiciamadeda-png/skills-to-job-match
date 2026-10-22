"""
Promote a raw skill string to an alias of an existing canonical skill,
or delete a noise skill entirely.

Usage:
    # Alias "Postgres 15" → PostgreSQL
    python manage.py add_skill_alias "Postgres 15" --canonical "PostgreSQL"

    # Delete a noise skill (e.g. "Communication")
    python manage.py add_skill_alias "Communication" --delete
"""
from django.core.management.base import BaseCommand, CommandError

from apps.intelligence.models import Skill, SkillAlias
from apps.intelligence.utils import normalize_skill


class Command(BaseCommand):
    help = 'Alias a raw skill string to a canonical skill, or delete a noise skill.'

    def add_arguments(self, parser):
        parser.add_argument('raw', help='Raw skill name to alias or delete')
        parser.add_argument('--canonical', help='Canonical skill name to map to')
        parser.add_argument('--delete', action='store_true', help='Delete the auto-created skill instead')

    def handle(self, *args, **options):
        raw = options['raw'].strip()
        norm = normalize_skill(raw)

        if options['delete']:
            deleted, _ = Skill.objects.filter(normalised_name=norm, is_auto_created=True).delete()
            if deleted:
                self.stdout.write(f"Deleted skill: {raw!r}")
            else:
                self.stdout.write(f"No auto-created skill found for {raw!r}")
            return

        if not options['canonical']:
            raise CommandError('Provide --canonical <name> or --delete')

        canonical_norm = normalize_skill(options['canonical'])
        try:
            canonical_skill = Skill.objects.get(normalised_name=canonical_norm)
        except Skill.DoesNotExist:
            raise CommandError(f"Canonical skill not found: {options['canonical']!r}")

        # Create the alias
        _, created = SkillAlias.objects.get_or_create(
            normalised=norm,
            defaults={'skill': canonical_skill, 'alias': raw},
        )

        # Re-point any JobSkill rows that landed on the auto-created skill
        auto_skill = Skill.objects.filter(normalised_name=norm, is_auto_created=True).first()
        repointed = 0
        if auto_skill and auto_skill.pk != canonical_skill.pk:
            from apps.intelligence.models import JobSkill
            for js in JobSkill.objects.filter(skill=auto_skill):
                JobSkill.objects.get_or_create(
                    job=js.job, skill=canonical_skill,
                    defaults={'extraction_method': js.extraction_method, 'extracted_at': js.extracted_at},
                )
                js.delete()
                repointed += 1
            auto_skill.delete()

        status = 'created' if created else 'already existed'
        self.stdout.write(
            f"Alias {status}: {raw!r} → {canonical_skill.name!r} "
            f"(repointed {repointed} JobSkill rows)"
        )
