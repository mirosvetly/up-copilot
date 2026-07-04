from __future__ import annotations

from celery import shared_task

from apps.jobs.models import JobPosting

from .generator import ensure_screening


@shared_task
def answer_drafted_jobs() -> dict:
    """Draft screening answers for drafted jobs that have client questions."""
    answered = 0
    for job in JobPosting.objects.filter(status=JobPosting.Status.DRAFTED):
        answered += ensure_screening(job)
    return {"answered": answered}
