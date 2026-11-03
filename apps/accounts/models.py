from django.contrib.auth import get_user_model
from django.db import models

from apps.core.models import TimestampedModel

User = get_user_model()


def _cv_upload_path(instance, filename):
    # Store under user pk — never expose original filename in the path
    ext = filename.rsplit('.', 1)[-1].lower()
    return f'cvs/{instance.owner_id}/{instance.pk}.{ext}'


class CV(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'       # file uploaded, text not yet extracted
        READY = 'ready', 'Ready'             # text extracted successfully
        FAILED = 'failed', 'Failed'          # extraction failed (scanned PDF, corrupt file, …)

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cvs')
    file = models.FileField(upload_to=_cv_upload_path, null=True, blank=True)
    original_filename = models.CharField(max_length=255)   # for display only — never logged
    extracted_text = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    failure_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']

    def delete_file(self):
        """Delete the stored file once text has been processed."""
        if self.file:
            self.file.delete(save=False)
            self.file = None
            self.save(update_fields=['file'])

    def __str__(self):
        # Never include extracted_text or original_filename in __str__ — it ends up in logs
        return f"CV(pk={self.pk}, owner={self.owner_id}, status={self.status})"
