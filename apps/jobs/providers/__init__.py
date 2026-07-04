from django.conf import settings

from .base import JobProvider, RawClient, RawJob
from .mock import MockProvider
from .upwork import UpworkProvider

_PROVIDERS = {"mock": MockProvider, "upwork": UpworkProvider}


def get_provider(name: str | None = None) -> JobProvider:
    name = name or settings.JOB_PROVIDER
    try:
        return _PROVIDERS[name]()
    except KeyError:
        raise ValueError(f"Unknown JOB_PROVIDER {name!r}; choose from {list(_PROVIDERS)}")


__all__ = ["JobProvider", "RawJob", "RawClient", "get_provider"]
