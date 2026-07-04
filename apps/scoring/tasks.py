from __future__ import annotations

from celery import shared_task

from apps.jobs.models import JobPosting

from .profile import load_profile
from .scorer import score_job


@shared_task
def score_pending_jobs() -> dict:
    """Score every job still in `new`. Runs after collection."""
    profile = load_profile()
    scored = 0
    for job in JobPosting.objects.filter(status=JobPosting.Status.NEW).select_related("client"):
        score_job(job, profile=profile)
        scored += 1
    return {"scored": scored}
