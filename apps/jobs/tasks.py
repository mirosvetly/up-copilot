from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import ClientProfile, JobPosting, SavedFilter, SeenJob
from .providers import RawClient, get_provider

SEEN_TTL_DAYS = 21  # API window is ~7 days; keep the ledger a few multiples of that

log = logging.getLogger(__name__)


def _upsert_client(rc: RawClient) -> ClientProfile:
    obj, _ = ClientProfile.objects.update_or_create(
        upwork_client_id=rc.upwork_client_id,
        defaults={
            "verified_payment": rc.verified_payment,
            "hire_rate": rc.hire_rate,
            "total_spent": rc.total_spent,
            "country": rc.country,
            "avg_rating": rc.avg_rating,
            "total_jobs": rc.total_jobs,
            "total_hires": rc.total_hires,
            "member_since": rc.member_since,
            "raw": rc.raw,
        },
    )
    return obj


def _persist_job(rj, *, matched_filter: SavedFilter | None) -> bool:
    """Create a JobPosting (+ upsert its client) from one RawJob. Returns True if
    a new JobPosting row was created. Shared by both ingestion paths — polling
    (collect_for_filter, many jobs/call) and the push webhook (one job/call) —
    so a job looks identical in the DB no matter which path delivered it."""
    client = _upsert_client(rj.client)
    _, is_new = JobPosting.objects.get_or_create(
        job_id=rj.job_id,
        defaults={
            "title": rj.title,
            "description": rj.description,
            "skills": rj.skills,
            "budget_type": rj.budget_type,
            "budget_min": rj.budget_min,
            "budget_max": rj.budget_max,
            "currency": rj.currency,
            "proposals_bucket": rj.proposals_bucket,
            "client": client,
            "matched_filter": matched_filter,
            "posted_at": rj.posted_at,
            "raw": rj.raw,
        },
    )
    return is_new


def _is_stale(rj) -> bool:
    cutoff = timezone.now() - timedelta(hours=settings.MAX_JOB_AGE_HOURS)
    return bool(rj.posted_at and rj.posted_at < cutoff)


def collect_for_filter(saved_filter: SavedFilter, *, provider=None) -> dict:
    """Fetch + dedup-persist jobs for one filter. Returns {created, seen}.

    Dedup is against the SeenJob ledger, not the live JobPosting table, so a job
    imported once is never re-imported (hence never re-scored) even after it's
    deleted — the API keeps returning the same recent jobs on every poll."""
    provider = provider or get_provider()
    raw_jobs = provider.fetch_jobs(saved_filter)
    # Only keep fresh jobs: the API returns a ~7-day window, but week-old postings
    # already have a crowd of applicants — not worth importing or scoring.
    raw_jobs = [rj for rj in raw_jobs if not _is_stale(rj)]
    ids = [rj.job_id for rj in raw_jobs]
    already = set(SeenJob.objects.filter(job_id__in=ids).values_list("job_id", flat=True))
    created = 0
    for rj in raw_jobs:
        if rj.job_id in already:
            continue  # seen before (maybe since deleted) — don't re-import or re-score
        created += int(_persist_job(rj, matched_filter=saved_filter))
    # Remember every id we just saw so the next poll skips them; prune the tail.
    SeenJob.objects.bulk_create(
        [SeenJob(job_id=i) for i in ids if i not in already], ignore_conflicts=True
    )
    SeenJob.objects.filter(
        created_at__lt=timezone.now() - timedelta(days=SEEN_TTL_DAYS)
    ).delete()
    saved_filter.last_polled_at = timezone.now()
    saved_filter.save(update_fields=["last_polled_at", "updated_at"])
    return {"created": created, "seen": len(raw_jobs)}


def ingest_pushed_job(rj, *, matched_filter: SavedFilter | None) -> str:
    """Single-job ingest for the Vibeworker push webhook. Returns "created",
    "duplicate", or "stale". Dedup rides the same SeenJob ledger as polling, so
    a job delivered via both the webhook and a still-running poll of the same
    filter is only ever imported once, in whichever order they arrive."""
    if _is_stale(rj):
        return "stale"
    if SeenJob.objects.filter(job_id=rj.job_id).exists():
        return "duplicate"
    is_new = _persist_job(rj, matched_filter=matched_filter)
    SeenJob.objects.get_or_create(job_id=rj.job_id)
    return "created" if is_new else "duplicate"


def _is_due(f: SavedFilter, now) -> bool:
    return f.last_polled_at is None or now - f.last_polled_at >= timedelta(minutes=f.poll_interval_min)


@shared_task
def collect_jobs() -> dict:
    """Beat heartbeat: poll every active filter whose interval has elapsed."""
    now = timezone.now()
    totals = {"filters": 0, "created": 0, "seen": 0}
    for f in SavedFilter.objects.filter(is_active=True):
        if not _is_due(f, now):
            continue
        try:
            r = collect_for_filter(f)
        except NotImplementedError as exc:
            log.warning("Provider not ready for filter %s: %s", f.name, exc)
            continue
        except Exception:
            # One broken filter (API down, quota hit) must not kill the loop —
            # and must retry on its own cadence, not on every 60s beat tick,
            # so mark it polled even though the attempt failed.
            log.exception("Collect failed for filter %s", f.name)
            f.last_polled_at = now
            f.save(update_fields=["last_polled_at", "updated_at"])
            continue
        totals["filters"] += 1
        totals["created"] += r["created"]
        totals["seen"] += r["seen"]
    return totals
