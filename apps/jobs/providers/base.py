from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from apps.jobs.models import SavedFilter


@dataclass
class RawClient:
    upwork_client_id: str
    verified_payment: bool = False
    hire_rate: int | None = None
    total_spent: Decimal | None = None
    country: str = ""
    avg_rating: Decimal | None = None
    total_jobs: int | None = None
    total_hires: int | None = None
    member_since: date | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class RawJob:
    job_id: str
    title: str
    description: str
    skills: list[str]
    budget_type: str  # "hourly" | "fixed"
    budget_min: Decimal | None
    budget_max: Decimal | None
    currency: str
    proposals_bucket: str
    posted_at: datetime
    client: RawClient
    raw: dict = field(default_factory=dict)


class JobProvider(ABC):
    """Swap point between the fixture MockProvider and the real Upwork client."""

    @abstractmethod
    def fetch_jobs(self, saved_filter: SavedFilter) -> list[RawJob]:
        """Return raw jobs matching a saved filter. No persistence here."""
        raise NotImplementedError


def matches_filter(job: RawJob, f: SavedFilter) -> bool:
    """Loose client-side SavedFilter check for providers that can't filter server-side."""
    if f.require_verified_payment and not job.client.verified_payment:
        return False
    if f.min_budget is not None and (job.budget_min or Decimal(0)) < f.min_budget:
        return False
    if f.keywords:
        haystack = (job.title + " " + " ".join(job.skills)).lower()
        if not any(k.lower() in haystack for k in f.keywords):
            return False
    return True
