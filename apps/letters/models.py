from django.db import models

from apps.core.models import TimeStampedModel
from apps.jobs.models import JobPosting


class CoverLetterDraft(TimeStampedModel):
    """A versioned cover-letter draft. Regenerating adds a version and flips
    is_active; the human edits `body` before sending manually."""

    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name="cover_drafts")
    version = models.PositiveSmallIntegerField(default=0)
    body = models.TextField(blank=True)
    # [{"t": "...", "src": "repo-name"|null}] — src marks GitHub-sourced spans.
    segments = models.JSONField(default=list, blank=True)
    sources = models.JSONField(default=list, blank=True)  # repo names used
    is_active = models.BooleanField(default=True)
    model_name = models.CharField(max_length=40, default="mock-template-v1")

    class Meta:
        ordering = ("-version",)
        constraints = [
            models.UniqueConstraint(fields=("job", "version"), name="uniq_job_version"),
        ]

    def __str__(self):
        return f"{self.job.job_id} cover v{self.version}"
