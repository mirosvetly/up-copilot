"""One poll cycle: collect fresh jobs, score them, Telegram-ping the good ones.

Run it on a schedule (launchd/cron every few minutes) so alerts arrive even when
the browser is closed:

    * * * * *  cd /path/to/app && venv/bin/python manage.py poll_notify

Safe to run back-to-back: collection dedups via SeenJob and pings dedup via
review_notified_at.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Collect + score new jobs, then Telegram-ping ones scoring >= NOTIFY_MIN_SCORE."

    def handle(self, *args, **opts):
        from apps.jobs.models import SavedFilter
        from apps.jobs.tasks import collect_for_filter
        from apps.review.notify import notify_scored_jobs
        from apps.scoring.tasks import score_pending_jobs

        created = 0
        for f in SavedFilter.objects.filter(is_active=True):
            try:
                created += collect_for_filter(f)["created"]
            except Exception as exc:  # one bad filter shouldn't abort the cycle
                self.stderr.write(f"collect failed for {f.name}: {exc}")
        scored = score_pending_jobs()["scored"]
        result = notify_scored_jobs()
        self.stdout.write(
            self.style.SUCCESS(
                f"collected {created}, scored {scored}, pinged {result.get('sent', 0)}"
                + (f" ({result['skipped']})" if result.get("skipped") else "")
            )
        )
