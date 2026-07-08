"""Seed the SeenJob ledger from job_ids already in the DB, so existing jobs are
remembered and a re-poll doesn't re-import (and re-score) them."""
from django.db import migrations


def backfill(apps, schema_editor):
    JobPosting = apps.get_model("jobs", "JobPosting")
    SeenJob = apps.get_model("jobs", "SeenJob")
    ids = JobPosting.objects.values_list("job_id", flat=True)
    SeenJob.objects.bulk_create(
        [SeenJob(job_id=i) for i in ids], ignore_conflicts=True, batch_size=500
    )


class Migration(migrations.Migration):
    dependencies = [("jobs", "0006_seenjob")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
