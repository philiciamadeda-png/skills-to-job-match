import logging
from datetime import date

from apps.ingestion.models import RawJobPayload
from apps.intelligence.models import Company, Job, Location, Skill, SkillAlias
from apps.intelligence.utils import normalize_company, normalize_location, normalize_skill, normalize_title

logger = logging.getLogger(__name__)


def resolve_skill(raw: str) -> Skill:
    """
    Return the canonical Skill for raw_string.

    Lookup order:
      1. SkillAlias.normalised  — catches known variants ("Postgres" -> PostgreSQL)
      2. Skill.normalised_name  — direct hit on canonical key
      3. Create new Skill flagged is_auto_created=True for human review
    """
    key = normalize_skill(raw)
    if not key:
        raise ValueError(f"resolve_skill: empty string after normalisation: {raw!r}")

    # 1. alias table
    try:
        return SkillAlias.objects.select_related('skill').get(normalised=key).skill
    except SkillAlias.DoesNotExist:
        pass

    # 2. canonical key
    try:
        return Skill.objects.get(normalised_name=key)
    except Skill.DoesNotExist:
        pass

    # 3. create — flagged for review
    skill, _ = Skill.objects.get_or_create(
        normalised_name=key,
        defaults={'name': raw.strip(), 'is_auto_created': True},
    )
    return skill


# ---------------------------------------------------------------------------
# Per-source mappers — return a common dict or raise ValueError if malformed
# ---------------------------------------------------------------------------

def _map_remotive(raw: dict) -> dict:
    source_id = str(raw.get('id') or '')
    if not source_id:
        raise ValueError("missing 'id'")
    return {
        'source_id': source_id,
        'title': raw.get('title') or '',
        'company_name': raw.get('company_name') or '',
        'location_text': raw.get('candidate_required_location') or '',
        'job_type': raw.get('job_type') or '',
        'salary_text': raw.get('salary') or '',
        'url': raw.get('url') or '',
        'description': raw.get('description') or '',
        'published_date': raw.get('publication_date') or '',
    }


def _map_arbeitnow(raw: dict) -> dict:
    source_id = raw.get('slug') or ''
    if not source_id:
        raise ValueError("missing 'slug'")
    job_types = raw.get('job_types') or []
    # If remote flag is set and no location text, treat as Remote
    location_text = raw.get('location') or ''
    if raw.get('remote') and not location_text:
        location_text = 'Remote'
    return {
        'source_id': source_id,
        'title': raw.get('title') or '',
        'company_name': raw.get('company_name') or '',
        'location_text': location_text,
        'job_type': job_types[0] if job_types else '',
        'salary_text': '',
        'url': raw.get('url') or '',
        'description': raw.get('description') or '',
        'published_date': raw.get('created_at') or '',
    }


_MAPPERS = {
    'remotive': _map_remotive,
    'arbeitnow': _map_arbeitnow,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_create_company(name: str) -> Company:
    normalised = normalize_company(name) if name else ''
    company, _ = Company.objects.get_or_create(
        normalised_name=normalised or name.lower(),
        defaults={'name': name},
    )
    return company


def _get_or_create_location(location_text: str) -> Location:
    parsed = normalize_location(location_text)
    location, _ = Location.objects.get_or_create(
        normalised_country=parsed['country'] or '',
        normalised_city=parsed['city'] or '',
        defaults={
            'raw_text': parsed['raw'],
            'is_remote': parsed['is_remote'],
            'country': parsed['country'] or '',
            'city': parsed['city'] or '',
        },
    )
    return location


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Main transform service
# ---------------------------------------------------------------------------

def transform_raw_payloads(run=None, batch_size: int = 200) -> dict:
    """
    Read unprocessed RawJobPayload rows in batches, write Job/Company/Location,
    mark each payload processed. Re-runnable — uses get_or_create on Job.

    Args:
        run: optional IngestionRun instance to update counts on
        batch_size: number of payloads to process per batch

    Returns:
        dict with created, skipped, failed counts
    """
    counts = {'created': 0, 'skipped': 0, 'failed': 0}

    qs = RawJobPayload.objects.filter(processed=False).order_by('id')

    last_id = 0
    while True:
        batch = list(qs.filter(id__gt=last_id)[:batch_size])
        if not batch:
            break

        for payload in batch:
            mapper = _MAPPERS.get(payload.source)
            if mapper is None:
                logger.warning('transform: unknown source %r (payload %s)', payload.source, payload.pk)
                counts['skipped'] += 1
                continue

            try:
                mapped = mapper(payload.raw_data)
                if not mapped['title']:
                    raise ValueError("missing 'title'")

                company = _get_or_create_company(mapped['company_name'])
                location = _get_or_create_location(mapped['location_text'])

                job, created = Job.objects.get_or_create(
                    source=payload.source,
                    source_id=mapped['source_id'],
                    defaults={
                        'title': mapped['title'],
                        'normalised_title': normalize_title(mapped['title']),
                        'company': company,
                        'location': location,
                        'contract_type': mapped['job_type'],
                        'salary_text': mapped['salary_text'],
                        'external_url': mapped['url'],
                        'description': mapped['description'],
                        'published_date': _parse_date(mapped['published_date']),
                        'content_hash': payload.content_hash,
                    },
                )

                payload.processed = True
                payload.job = job
                payload.save(update_fields=['processed', 'job'])

                if created:
                    counts['created'] += 1
                else:
                    counts['skipped'] += 1

            except Exception as exc:
                logger.error('transform: failed payload %s — %s', payload.pk, exc)
                counts['failed'] += 1

        last_id = batch[-1].pk

    if run is not None:
        run.created += counts['created']
        run.skipped += counts['skipped']
        run.failed += counts['failed']
        run.save(update_fields=['created', 'skipped', 'failed'])

    return counts


def deduplicate_jobs(dry_run: bool = False) -> dict:
    """
    Simple rule: jobs with the same (normalised_title, company) are duplicates.
    The earliest-created job (lowest pk) is kept as canonical.
    All later jobs from different sources get canonical FK set.

    Args:
        dry_run: if True, count matches but make no DB changes

    Returns:
        dict with total_jobs, duplicate_groups, duplicates_marked, already_marked
    """
    from django.db.models import Count, Min

    # Find (normalised_title, company) pairs that appear on more than one source
    groups = (
        Job.objects.filter(canonical__isnull=True, company__isnull=False)
        .exclude(normalised_title='')
        .values('normalised_title', 'company')
        .annotate(count=Count('id'), min_pk=Min('id'))
        .filter(count__gt=1)
    )

    duplicate_groups = 0
    duplicates_marked = 0
    already_marked = 0

    for group in groups:
        canonical_pk = group['min_pk']
        duplicates = Job.objects.filter(
            normalised_title=group['normalised_title'],
            company=group['company'],
            canonical__isnull=True,
        ).exclude(pk=canonical_pk)

        # Only flag cross-source duplicates — same source re-posts are a different problem
        cross_source = duplicates.exclude(
            source=Job.objects.get(pk=canonical_pk).source
        )

        if not cross_source.exists():
            continue

        duplicate_groups += 1
        count = cross_source.count()

        if not dry_run:
            cross_source.update(canonical_id=canonical_pk)
            duplicates_marked += count
        else:
            duplicates_marked += count

    return {
        'total_jobs': Job.objects.count(),
        'canonical_jobs': Job.objects.filter(canonical__isnull=True).count(),
        'duplicate_groups': duplicate_groups,
        'duplicates_marked': duplicates_marked,
    }
