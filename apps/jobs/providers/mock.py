from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.utils import timezone

from apps.jobs.models import SavedFilter

from .base import JobProvider, RawClient, RawJob, matches_filter

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "mock_jobs.json"


def _dec(v):
    return Decimal(v) if v is not None else None


class MockProvider(JobProvider):
    """Serves jobs from a fixture file, dated relative to now so freshness works.

    Filtering is deliberately loose — enough to prove SavedFilter plumbing,
    not to mimic Upwork's ranking. The real provider will delegate that to the API.
    """

    def __init__(self, fixture: Path = FIXTURE):
        self._fixture = fixture

    def fetch_jobs(self, saved_filter: SavedFilter) -> list[RawJob]:
        rows = json.loads(self._fixture.read_text())
        now = timezone.now()
        jobs = [self._to_raw(r, now) for r in rows]
        return [j for j in jobs if matches_filter(j, saved_filter)]

    def _to_raw(self, r: dict, now) -> RawJob:
        c = r["client"]
        client = RawClient(
            upwork_client_id=c["upwork_client_id"],
            verified_payment=c.get("verified_payment", False),
            hire_rate=c.get("hire_rate"),
            total_spent=_dec(c.get("total_spent")),
            country=c.get("country", ""),
            avg_rating=_dec(c.get("avg_rating")),
            total_jobs=c.get("total_jobs"),
            total_hires=c.get("total_hires"),
            member_since=date.fromisoformat(c["member_since"]) if c.get("member_since") else None,
        )
        return RawJob(
            job_id=r["job_id"],
            title=r["title"],
            description=r.get("description", ""),
            skills=r.get("skills", []),
            budget_type=r["budget_type"],
            budget_min=_dec(r.get("budget_min")),
            budget_max=_dec(r.get("budget_max")),
            currency=r.get("currency", "USD"),
            proposals_bucket=r.get("proposals_bucket", ""),
            posted_at=now - timedelta(minutes=r.get("age_min", 0)),
            client=client,
            raw=r,
        )
