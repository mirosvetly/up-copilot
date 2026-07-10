from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from django.conf import settings

PROFILE_PATH = Path(settings.BASE_DIR) / "stack_profile.yaml"


def load_profile(path: str | None = None) -> dict:
    """Load the hand-edited stack profile — the sidebar identity + migration seed."""
    return yaml.safe_load(Path(path or PROFILE_PATH).read_text())


def freelancer_config(profile: dict[str, Any] | None = None) -> dict[str, str]:
    """Personal identity for the sidebar. Global, not per-track."""
    profile = profile or load_profile()
    person = profile.get("freelancer") or {}
    name = str(person.get("name") or "Freelancer")
    first_name = name.split()[0] if name.strip() else "Freelancer"
    skills = profile.get("skills") or []
    headline = str(person.get("headline") or " · ".join(skills[:3]) or "Freelancer")
    return {
        "name": name,
        "display_name": str(person.get("display_name") or name),
        "initials": str(person.get("initials") or first_name[:2].upper()),
        "headline": headline,
    }


def track_config(track) -> dict[str, Any]:
    """A Track -> the profile dict the scorer / letters / screening consume.

    Same shape the old global load_profile() returned, so downstream code is
    unchanged. `track` may be None (fresh DB with no tracks) — safe defaults.
    """
    # Geo/language identity is global (single user), same for every track.
    geo = {
        "freelancer_location": settings.FREELANCER_LOCATION,
        "freelancer_languages": settings.FREELANCER_LANGUAGES,
    }
    if track is None:
        return {
            "skills": [], "min_hourly_rate": 0, "red_flag_phrases": [], "projects": [],
            "job_analysis_prompt": "Score fit 0-100 and justify it.",
            "scorer_role": "freelancer",
            "cover_letter_instructions": "Write a concise, specific Upwork cover letter.",
            "screening_instructions": "Answer Upwork screening questions honestly, first person.",
            "signoff": "Best,\nFreelancer",
            **geo,
        }
    return {
        **geo,
        "skills": track.skills or [],
        "min_hourly_rate": track.min_hourly_rate,
        "red_flag_phrases": track.red_flag_phrases or [],
        "projects": track.projects or [],
        "job_analysis_prompt": track.job_analysis_prompt or "Score fit 0-100 and justify it.",
        "scorer_role": track.scorer_role or "freelancer",
        "cover_letter_instructions": (
            track.cover_letter_instructions or "Write a concise, specific Upwork cover letter."
        ),
        "screening_instructions": (
            track.screening_instructions
            or "Answer Upwork screening questions honestly, first person."
        ),
        "signoff": track.signoff or "Best,\nFreelancer",
        "track_id": track.id,
    }


def resolve_track(job):
    """The Track a job is scored/drafted under: its search's track, else default."""
    from apps.tracks.models import Track

    f = getattr(job, "matched_filter", None)
    return (f.track if f else None) or Track.get_default()
