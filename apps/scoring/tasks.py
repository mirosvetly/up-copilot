from __future__ import annotations

from celery import shared_task

from apps.jobs.models import JobPosting

from .scorer import score_job


@shared_task
def score_pending_jobs() -> dict:
    """Score every job still in `new` under its own track's persona."""
    scored = 0
    qs = JobPosting.objects.filter(status=JobPosting.Status.NEW).select_related(
        "client", "matched_filter__track"
    )
    for job in qs:
        score_job(job)  # resolves the job's track internally
        scored += 1
    return {"scored": scored}
