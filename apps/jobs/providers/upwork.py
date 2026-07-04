from __future__ import annotations

from apps.jobs.models import SavedFilter

from .base import JobProvider, RawJob


class UpworkProvider(JobProvider):
    """Real client over Upwork's GraphQL API (api.upwork.com/graphql, OAuth2).

    Stubbed until the OAuth app is approved. When the key lands, implement
    fetch_jobs: run the marketplaceJobPostingsSearch query built from the
    SavedFilter and map results into RawJob/RawClient.
    """

    def fetch_jobs(self, saved_filter: SavedFilter) -> list[RawJob]:
        raise NotImplementedError(
            "UpworkProvider is not implemented yet — waiting on OAuth approval. "
            "Set JOB_PROVIDER=mock for now."
        )
