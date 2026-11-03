from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import CV
from apps.intelligence.matching import match_profile


class Command(BaseCommand):
    help = 'Match a CV profile against all jobs and print ranked results.'

    def add_arguments(self, parser):
        parser.add_argument('--cv', type=int, required=True, help='CV pk')
        parser.add_argument('--top', type=int, default=10)
        parser.add_argument('--explain', action='store_true', help='Show per-component scores and skill breakdown')
        parser.add_argument('--remote-only', action='store_true')

    def handle(self, *args, **options):
        try:
            cv = CV.objects.select_related('profile').get(pk=options['cv'])
        except CV.DoesNotExist:
            raise CommandError(f"CV {options['cv']} not found.")

        if not hasattr(cv, 'profile'):
            raise CommandError(f"CV {options['cv']} has no profile. Run extract_cv_profile() first.")

        profile = cv.profile
        self.stdout.write(f"\nProfile  seniority={profile.seniority}  years={profile.years_experience}")
        self.stdout.write(f"Skills   {', '.join(profile.skills.values_list('name', flat=True))}\n")

        results = match_profile(profile, remote_only=options['remote_only'], limit=options['top'])

        if not results:
            self.stdout.write('No matching jobs found.')
            return

        self.stdout.write(f"{'Rank':<5} {'Score':<7} {'Title':<45} {'Company':<25} {'Seniority'}")
        self.stdout.write('-' * 110)

        for i, r in enumerate(results, 1):
            company = r.job.company.name if r.job.company else '—'
            self.stdout.write(
                f"{i:<5} {r.total_score:<7.3f} {r.job.title[:44]:<45} {company[:24]:<25} {r.job.seniority or '—'}"
            )
            if options['explain']:
                self.stdout.write(
                    f"      req={r.required_skill_score:.2f}  "
                    f"sem={r.semantic_score:.2f}  "
                    f"sen={r.seniority_score:.2f} (gap={r.seniority_gap:+d})  "
                    f"recency={r.recency_score:.2f}"
                )
                if r.matched_required:
                    self.stdout.write(f"      matched : {', '.join(r.matched_required)}")
                if r.missing_required:
                    self.stdout.write(f"      missing : {', '.join(r.missing_required)}")
                self.stdout.write('')
