from django.db import models
from apps.core.models import TimestampedModel


class Company(TimestampedModel):
    name = models.CharField(max_length=255)
    normalised_name = models.CharField(max_length=255, unique=True, db_index=True)
    website = models.URLField(blank=True)
    logo_url = models.URLField(blank=True)


class Location(TimestampedModel):
    raw_text = models.CharField(max_length=255)
    country = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    normalised_country = models.CharField(max_length=100, blank=True)
    normalised_city = models.CharField(max_length=100, blank=True)
    is_remote = models.BooleanField(default=False)

    class Meta:
        unique_together = [('normalised_country', 'normalised_city')]
        indexes = [
            models.Index(fields=['country', 'city']),
        ]


class Skill(TimestampedModel):
    name = models.CharField(max_length=100)
    normalised_name = models.CharField(max_length=100, unique=True, db_index=True)
    category = models.CharField(max_length=100, blank=True)
    is_auto_created = models.BooleanField(default=False, db_index=True)


class SkillAlias(TimestampedModel):
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name='aliases')
    alias = models.CharField(max_length=100)          # raw form, e.g. "Postgres"
    normalised = models.CharField(max_length=100, unique=True, db_index=True)  # lookup key

    class Meta:
        verbose_name_plural = 'skill aliases'


class JobSkill(TimestampedModel):
    job = models.ForeignKey('Job', on_delete=models.CASCADE)
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE)
    confidence_score = models.FloatField(null=True, blank=True)
    extraction_method = models.CharField(max_length=50, blank=True)
    extracted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('job', 'skill')]


class Job(TimestampedModel):
    title = models.CharField(max_length=255)
    normalised_title = models.CharField(max_length=255, blank=True, db_index=True)
    description = models.TextField(blank=True)
    company = models.ForeignKey(Company, on_delete=models.SET_NULL, null=True, db_index=True)
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, db_index=True)
    skills = models.ManyToManyField(Skill, through=JobSkill, blank=True)
    source = models.CharField(max_length=100)
    source_id = models.CharField(max_length=255)
    external_url = models.URLField(max_length=500, blank=True)
    published_date = models.DateField(null=True, blank=True, db_index=True)
    salary_text = models.CharField(max_length=255, blank=True)
    salary_min = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    salary_max = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    salary_currency = models.CharField(max_length=10, blank=True)
    contract_type = models.CharField(max_length=100, blank=True)
    content_hash = models.CharField(max_length=64, db_index=True)
    embedding = models.JSONField(null=True, blank=True)  # placeholder for pgvector
    canonical = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='duplicates',
        help_text='Non-null means this job is a duplicate of the referenced job',
    )

    class Meta:
        unique_together = [('source', 'source_id')]
        indexes = [
            models.Index(fields=['source', 'source_id']),
            models.Index(fields=['normalised_title', 'company']),
        ]
