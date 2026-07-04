from __future__ import annotations

from celery import shared_task
from django.conf import settings

from apps.jobs.models import JobPosting

from .generator import generate_cover


@shared_task
def draft_scored_jobs() -> dict:
    """Draft a cover letter for each promising scored job (score >= threshold)."""
    drafted = 0
    qs = JobPosting.objects.filter(
        status=JobPosting.Status.SCORED, score__score__gte=settings.DRAFT_MIN_SCORE
    ).select_related("score")
    for job in qs:
        generate_cover(job)  # transitions scored -> drafted
        drafted += 1
    return {"drafted": drafted}
