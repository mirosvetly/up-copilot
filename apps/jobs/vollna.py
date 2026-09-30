"""Vollna webhook: your Upwork proposals (sent, viewed, interviewed, hired) flow in
without tapping "Отправил". Keys are looked up anywhere in the payload because
Vollna documents the envelope but not every field of the proposal object."""
from __future__ import annotations

import hmac
import json
import logging
import re

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import JobPosting, VollnaEvent

log = logging.getLogger(__name__)
_UPWORK_ID = re.compile(r"~([0-9a-zA-Z]{8,})")


def _find(obj, *keys):
    """First value under any of `keys`, searched depth-first through dicts and lists."""
    if isinstance(obj, dict):
        for k in keys:
            if obj.get(k) not in (None, ""):
                return obj[k]
        for v in obj.values():
            hit = _find(v, *keys)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find(v, *keys)
            if hit is not None:
                return hit
    return None


def authorized(header: str) -> bool:
    token = settings.VOLLNA_WEBHOOK_TOKEN
    return bool(token) and hmac.compare_digest(header or "", f"Bearer {token}")


def handle(body: bytes) -> tuple[int, str]:
    try:
        env = json.loads(body)
        event_id, event, data = env["id"], env["event"], env.get("data") or {}
    except (ValueError, KeyError, TypeError):
        return 400, "bad payload"
    ev, created = VollnaEvent.objects.get_or_create(event_id=event_id, defaults={"event": event, "payload": env})
    if not created:
        return 200, "duplicate"
    if event.startswith("upwork_proposal."):
        ev.job = _apply_proposal(data)
        ev.save(update_fields=["job"])
    return 200, "ok"


def _apply_proposal(data: dict) -> JobPosting | None:
    url = _find(data, "url", "jobUrl", "upworkUrl", "link") or ""
    m = _UPWORK_ID.search(str(url))
    if not m:
        log.warning("Vollna proposal without an Upwork job url: %s", str(data)[:300])
        return None
    now = timezone.now()
    sent_at = parse_datetime(str(_find(data, "createdAt", "submittedAt", "created_at") or "")) or now
    job, _ = JobPosting.objects.get_or_create(
        job_id=m.group(1),
        defaults={"title": str(_find(data, "title") or "Upwork job")[:500], "budget_type": "fixed",
                  "status": JobPosting.Status.APPLIED, "applied_at": sent_at, "raw": {"url": str(url)}},
    )
    fields = []
    if job.status != JobPosting.Status.APPLIED:  # sent on Upwork, not marked here yet
        job.status, job.applied_at = JobPosting.Status.APPLIED, job.applied_at or sent_at
        fields += ["status", "applied_at"]
    connects = _find(data, "connects", "connectsSpent")
    if isinstance(connects, (int, float)) and connects > 0 and job.connects_spent != int(connects):
        job.connects_spent = int(connects); fields.append("connects_spent")
    for flag, attr in (("isViewed", "viewed_at"), ("isInterviewed", "interviewed_at"), ("isHired", "hired_at")):
        if _find(data, flag) is True and getattr(job, attr) is None:
            setattr(job, attr, now); fields.append(attr)
    if fields:
        job.save(update_fields=fields + ["updated_at"])
    return job
