from django.db import models

from apps.core.models import TimeStampedModel
from apps.jobs.models import JobPosting


class KnowledgeBase(TimeStampedModel):
    """Hand-maintained facts (rates, availability, timezone, cases, FAQ) that
    RAG pulls from to answer client screening questions."""

    category = models.CharField(max_length=40, blank=True)
    keywords = models.JSONField(default=list, blank=True)  # match hints
    content = models.TextField()

    def __str__(self):
        return f"[{self.category}] {self.content[:50]}"


class ScreeningQuestion(TimeStampedModel):
    """A question attached to a job posting (comes from Upwork / job.raw)."""

    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name="screening_questions")
    order = models.PositiveSmallIntegerField(default=0)
    text = models.TextField()

    class Meta:
        ordering = ("order",)
        constraints = [
            models.UniqueConstraint(fields=("job", "order"), name="uniq_job_question_order"),
        ]

    def __str__(self):
        return self.text[:60]


class ScreeningAnswer(TimeStampedModel):
    question = models.OneToOneField(ScreeningQuestion, on_delete=models.CASCADE, related_name="answer")
    body = models.TextField(blank=True)
    model_name = models.CharField(max_length=40, default="mock-rag-v1")

    def __str__(self):
        return self.body[:60]
