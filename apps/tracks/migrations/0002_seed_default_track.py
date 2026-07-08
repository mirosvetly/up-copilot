"""Seed the default 'Разработка' track from the hand-edited stack_profile.yaml,
so existing installs keep their persona with no manual step."""
from pathlib import Path

import yaml
from django.conf import settings
from django.db import migrations


def seed(apps, schema_editor):
    Track = apps.get_model("tracks", "Track")
    if Track.objects.exists():
        return
    path = Path(settings.BASE_DIR) / "stack_profile.yaml"
    profile = yaml.safe_load(path.read_text()) if path.exists() else {}
    person = profile.get("freelancer") or {}
    Track.objects.create(
        name="Разработка",
        is_default=True,
        scorer_role=person.get("scorer_role") or "freelance developer",
        job_analysis_prompt=profile.get("job_analysis_prompt") or "",
        cover_letter_instructions=person.get("cover_letter_instructions") or "",
        screening_instructions=person.get("screening_instructions") or "",
        signoff=person.get("signoff") or "Best,\nFreelancer",
        skills=profile.get("skills") or [],
        min_hourly_rate=int(profile.get("min_hourly_rate") or 0),
        projects=profile.get("projects") or [],
        red_flag_phrases=profile.get("red_flag_phrases") or [],
    )


def unseed(apps, schema_editor):
    Track = apps.get_model("tracks", "Track")
    Track.objects.filter(name="Разработка", is_default=True).delete()


class Migration(migrations.Migration):
    dependencies = [("tracks", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
