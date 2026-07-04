import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("upwork_copilot")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Pipeline heartbeats. Every stage is status-gated and idempotent, so running
# them each minute lets jobs flow collect -> score -> draft -> screen -> notify
# without an explicit chain. Poll cadence lives in SavedFilter.poll_interval_min.
app.conf.beat_schedule = {
    "collect-jobs": {"task": "apps.jobs.tasks.collect_jobs", "schedule": 60.0},
    "score-jobs": {"task": "apps.scoring.tasks.score_pending_jobs", "schedule": 60.0},
    "draft-jobs": {"task": "apps.letters.tasks.draft_scored_jobs", "schedule": 60.0},
    "answer-screening": {"task": "apps.screening.tasks.answer_drafted_jobs", "schedule": 60.0},
    "notify-review": {"task": "apps.review.tasks.notify_new_drafts", "schedule": 60.0},
}
