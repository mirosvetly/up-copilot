from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal
from itertools import product
from urllib.parse import urlparse

import requests
from django.conf import settings

from apps.jobs.models import SavedFilter

from .base import JobProvider, RawClient, RawJob

log = logging.getLogger(__name__)

API_URL = "https://kttkatrmvlzsepgprqqd.supabase.co/functions/v1/public-jobs"
LIMIT = 20  # ponytail: modest page size to stretch the free plan's 100 results/day
TIMEOUT = 30

_UPWORK_ID = re.compile(r"~([0-9a-zA-Z]+)")


def _is_upwork(url: str) -> bool:
    # Match the host, not a substring: "notupwork.com" / "upwork.com.evil.com"
    # both contain "upwork.com" but are not Upwork.
    host = (urlparse(url or "").hostname or "").lower()
    return host == "upwork.com" or host.endswith(".upwork.com")


def _dec(v) -> Decimal | None:
    return Decimal(str(v)) if v is not None else None


class VibeworkerProvider(JobProvider):
    """Upwork jobs via Vibeworker's REST API (tryvibeworker.com/docs).

    Bearer key from Settings -> Developer (env VIBEWORKER_API_KEY). The API
    takes a single keyword/category per request, so we fan out over the
    SavedFilter lists and dedup by job id. require_verified_payment has no
    API param and is filtered here. Vibeworker's AI scores ride along in
    RawJob.raw["scores"] for later phases.

    Free-plan arithmetic: 100 results/day, charged per job RETURNED (dupes
    included, sort=newest re-bills the same page every poll). At LIMIT=20
    that is ~5 polls/day per keyword — on the free plan set the filter's
    poll_interval_min to ~300, or upgrade for unlimited.
    """

    def fetch_jobs(self, saved_filter: SavedFilter) -> list[RawJob]:
        api_key = settings.VIBEWORKER_API_KEY
        if not api_key:
            raise RuntimeError("VIBEWORKER_API_KEY is not set (tryvibeworker.com/settings)")
        seen: dict[str, RawJob] = {}
        for params in self._param_sets(saved_filter):
            try:
                rows, quota = self._get(params, api_key)
            except (requests.RequestException, RuntimeError):
                # Earlier requests in this fan-out were already charged against
                # the daily quota — partial results beat losing them all.
                log.exception("Vibeworker request failed; keeping %d jobs fetched so far", len(seen))
                break
            for row in rows:
                # Vibeworker occasionally mixes in non-Upwork postings (e.g.
                # freelancer.com) under the same upworkUrl field — this app is
                # Upwork-only (connects scoring, proposal flow), so drop them.
                if not _is_upwork(row.get("upworkUrl") or row.get("url")):
                    continue
                job = self._to_raw(row)
                if saved_filter.require_verified_payment and not job.client.verified_payment:
                    continue
                seen.setdefault(job.job_id, job)
            if quota == 0:
                log.warning("Vibeworker daily quota exhausted; stopping fan-out early")
                break
        return list(seen.values())

    def _param_sets(self, f: SavedFilter):
        base = {"sort": "newest", "limit": LIMIT}
        if f.min_budget is not None:
            base["minBudget"] = str(f.min_budget)
        for kw, cat in product(f.keywords or [None], f.categories or [None]):
            params = dict(base)
            if kw:
                params["keywords"] = kw
            if cat:
                params["category"] = cat
            yield params

    def _get(self, params: dict, api_key: str) -> tuple[list[dict], int | None]:
        resp = requests.get(
            API_URL,
            params=params,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Vibeworker API {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        quota = body.get("quotaRemaining")  # present on free accounts only
        if quota is not None:
            log.info("Vibeworker quota remaining: %s", quota)
        return body.get("data", []), quota

    def _to_raw(self, row: dict) -> RawJob:
        # Prefer the real Upwork id from the job URL so dedup keys survive a
        # later switch to the official API; fall back to Vibeworker's stable id.
        m = _UPWORK_ID.search(row.get("upworkUrl") or "")
        job_id = m.group(1) if m else row["id"]
        client = RawClient(
            # ponytail: API exposes no client id — one profile per job, keyed off it
            upwork_client_id=f"vw:{job_id}",
            verified_payment=bool(row.get("clientPaymentVerified")),
            hire_rate=row.get("clientHireRate"),
            total_spent=_dec(row.get("clientTotalSpent")),
            country=row.get("clientLocation") or "",
            avg_rating=_dec(row.get("clientRating")),
            raw={k: v for k, v in row.items() if k.startswith("client")},
        )
        # Downstream (presenters, job detail page) reads raw["url"] for the
        # "open on Upwork" link; Vibeworker names the field upworkUrl.
        row.setdefault("url", row.get("upworkUrl") or "")
        row.setdefault("source", "vibeworker")  # re-poll guard keys on raw["source"]
        posted = row.get("postedAt")
        return RawJob(
            job_id=job_id,
            title=row["title"],
            description=row.get("description") or "",
            skills=row.get("skills") or [],
            budget_type=row.get("jobType") or "",
            budget_min=_dec(row.get("budget")),
            budget_max=_dec(row.get("budgetMax")),
            currency="USD",  # the API quotes all budgets in USD
            proposals_bucket="",  # not exposed by Vibeworker
            posted_at=datetime.fromisoformat(posted) if posted else None,
            client=client,
            raw=row,
        )
