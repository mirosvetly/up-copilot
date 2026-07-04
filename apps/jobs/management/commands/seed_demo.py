from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.jobs.models import SavedFilter
from apps.jobs.tasks import collect_for_filter
from apps.letters.tasks import draft_scored_jobs
from apps.scoring.tasks import score_pending_jobs
from apps.screening.tasks import answer_drafted_jobs


class Command(BaseCommand):
    help = "Create a default SavedFilter and run the collector once (mock provider)."

    def handle(self, *args, **options):
        call_command("seed_kb")  # KB facts for screening answers
        # Broad filter (no keyword gate) so scoring — not collection — ranks jobs.
        # Keyword filters still work; this demo just shows the full score spread.
        f, created = SavedFilter.objects.get_or_create(
            name="Все вакансии (демо)",
            defaults={
                "keywords": [],
                "min_budget": None,
                "require_verified_payment": False,
                "poll_interval_min": 15,
            },
        )
        self.stdout.write(f"Filter {'created' if created else 'exists'}: {f.name}")
        # Full pipeline, synchronously (Celery not required for the demo).
        self.stdout.write(f"Collected: {collect_for_filter(f)}")
        self.stdout.write(f"Scored:    {score_pending_jobs()}")
        self.stdout.write(f"Drafted:   {draft_scored_jobs()}")
        self.stdout.write(self.style.SUCCESS(f"Screened:  {answer_drafted_jobs()}"))
