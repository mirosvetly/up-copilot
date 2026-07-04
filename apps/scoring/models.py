from django.db import models

from apps.core.models import TimeStampedModel
from apps.jobs.models import JobPosting


class JobScore(TimeStampedModel):
    """Score + weighted reasons for a job. Phase 2a is rule-based; the LLM +
    embedding scorer will write to the same shape (score, reasoning, breakdown)."""

    job = models.OneToOneField(JobPosting, on_delete=models.CASCADE, related_name="score")
    score = models.PositiveSmallIntegerField()  # 0-100
    reasoning = models.TextField(blank=True)
    # [{"text": "...", "w": 26, "neg": false}, ...] — powers "Почему подходит".
    breakdown = models.JSONField(default=list, blank=True)
    # Vector stored inline (JSON) — Python cosine is fine at single-user scale;
    # pgvector/ANN is an optional upgrade if the job corpus ever gets large.
    embedding = models.JSONField(default=list, blank=True)
    similarity = models.FloatField(null=True, blank=True)  # profile<->job cosine
    model_name = models.CharField(max_length=40, default="rule-based-v1")

    def __str__(self):
        return f"{self.job.job_id}: {self.score}"
