from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import ClientProfile, JobPosting, SavedFilter
from .providers import RawClient, get_provider

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


def collect_for_filter(saved_filter: SavedFilter, *, provider=None) -> dict:
    """Fetch + dedup-persist jobs for one filter. Returns {created, seen}."""
    provider = provider or get_provider()
    raw_jobs = provider.fetch_jobs(saved_filter)
    created = 0
    for rj in raw_jobs:
        client = _upsert_client(rj.client)
        # Dedup on job_id. Existing rows keep their status and posted_at (don't
        # reset a job's position in the machine just because we saw it again);
        # only refresh volatile fields.
        obj, is_new = JobPosting.objects.get_or_create(
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
                "matched_filter": saved_filter,
                "posted_at": rj.posted_at,
                "raw": rj.raw,
            },
        )
        if not is_new:
            updates = {"proposals_bucket": rj.proposals_bucket}
            # Refresh raw/client only from the same source: a sparse gmail
            # alert must not clobber the richer row vibeworker collected.
            if (obj.raw or {}).get("source") == rj.raw.get("source"):
                updates.update(raw=rj.raw, client=client)
            JobPosting.objects.filter(job_id=rj.job_id).update(**updates)
        created += int(is_new)
    saved_filter.last_polled_at = timezone.now()
    saved_filter.save(update_fields=["last_polled_at", "updated_at"])
    return {"created": created, "seen": len(raw_jobs)}


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
