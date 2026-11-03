import hashlib

from django.contrib.auth import get_user_model
from django.db import models

from apps.core.models import TimestampedModel
from apps.intelligence.models import Skill

User = get_user_model()


def _cv_upload_path(instance, filename):
    ext = filename.rsplit('.', 1)[-1].lower()
    return f'cvs/{instance.owner_id}/{instance.pk}.{ext}'


class CV(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        READY = 'ready', 'Ready'
        FAILED = 'failed', 'Failed'

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cvs')
    file = models.FileField(upload_to=_cv_upload_path, null=True, blank=True)
    original_filename = models.CharField(max_length=255)   # for display only — never logged
    extracted_text = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    failure_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']

    def delete_file(self):
        if self.file:
            self.file.delete(save=False)
            self.file = None
            self.save(update_fields=['file'])

    def __str__(self):
        return f"CV(pk={self.pk}, owner={self.owner_id}, status={self.status})"


class CVProfile(TimestampedModel):
    """
    Structured profile extracted from a CV.
    Skills are resolved through resolve_skill() — same canonical records as jobs.
    Embedding is built with the same title_skills strategy as Job.embed_text().
    """
    cv = models.OneToOneField(CV, on_delete=models.CASCADE, related_name='profile')
    skills = models.ManyToManyField(Skill, blank=True)
    seniority = models.CharField(max_length=20, blank=True)
    years_experience = models.PositiveSmallIntegerField(null=True, blank=True)
    embedding = models.JSONField(null=True, blank=True)   # set after pgvector migration on accounts
    embedding_model = models.CharField(max_length=100, blank=True)

    def embed_text(self) -> str:
        """
        Mirror of Job.embed_text() — same title_skills strategy so both sides
        live in the same embedding space.
        """
        skill_names = list(self.skills.values_list('name', flat=True))
        parts = ['CV']
        if self.seniority:
            parts.append(self.seniority)
        if skill_names:
            parts.append('skills: ' + ', '.join(skill_names))
        snippet = self.cv.extracted_text[:400].replace('\n', ' ').strip()
        if snippet:
            parts.append(snippet)
        return ' | '.join(parts)

    def embed_text_hash(self) -> str:
        return hashlib.sha256(self.embed_text().encode()).hexdigest()

    def __str__(self):
        return f"CVProfile(cv={self.cv_id}, seniority={self.seniority})"
