from django.db import models
from django.utils import timezone

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
    breakdown_ru = models.JSONField(default=list, blank=True)  # cached RU translation of reasons
    # Vector stored inline (JSON) — Python cosine is fine at single-user scale;
    # pgvector/ANN is an optional upgrade if the job corpus ever gets large.
    embedding = models.JSONField(default=list, blank=True)
    similarity = models.FloatField(null=True, blank=True)  # profile<->job cosine
    model_name = models.CharField(max_length=40, default="rule-based-v1")

    def __str__(self):
        return f"{self.job.job_id}: {self.score}"

    def ensure_ru(self):
        """Translate the reason texts to RU once and cache (reasons come from
        the LLM in English). No-op if done or translation is off/unavailable."""
        if self.breakdown_ru or not self.breakdown:
            return
        from apps.core.translate import translate_ru_batch

        ru = translate_ru_batch([b.get("text", "") for b in self.breakdown])  # one call
        if any(ru):
            self.breakdown_ru = [
                {**b, "text": r or b.get("text", "")} for b, r in zip(self.breakdown, ru)
            ]
            # update(), not save(): the job (and this score) may be deleted mid-translation.
            type(self).objects.filter(pk=self.pk).update(
                breakdown_ru=self.breakdown_ru, updated_at=timezone.now()
            )
