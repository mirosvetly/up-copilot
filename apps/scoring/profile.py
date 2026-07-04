from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from django.conf import settings

PROFILE_PATH = Path(settings.BASE_DIR) / "stack_profile.yaml"


@lru_cache(maxsize=1)
def load_profile(path: str | None = None) -> dict:
    """Load the hand-edited stack profile. Cached; call load_profile.cache_clear() after edits."""
    return yaml.safe_load(Path(path or PROFILE_PATH).read_text())
