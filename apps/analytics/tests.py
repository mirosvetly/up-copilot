from django.test import TestCase

from apps.jobs.models import JobPosting

from . import metrics


class MetricsTests(TestCase):
    def setUp(self):
        for i, status in enumerate([JobPosting.Status.NEW, JobPosting.Status.APPLIED, JobPosting.Status.REVIEWED]):
            JobPosting.objects.create(
                job_id=f"m{i}", title="t", budget_type="fixed",
                skills=["Django", "Python"], status=status,
            )

    def test_funnel_found_counts_all(self):
        f = metrics.funnel()
        self.assertEqual(str(f[0]["label"]), "Найдено")
        self.assertEqual(f[0]["count"], 3)
        # funnel_counts now keys by stable slug (language-independent), not label
        self.assertEqual(dict(metrics.funnel_counts())["applied"], 1)

    def test_keywords_and_prometheus(self):
        kws = {k["kw"]: k for k in metrics.keywords()}
        self.assertEqual(kws["Django"]["n"], 3)
        self.assertIn('upwork_funnel{stage="found"} 3', metrics.prometheus_text())

    def test_endpoints_render(self):
        self.assertEqual(self.client.get("/analytics/").status_code, 200)
        r = self.client.get("/metrics/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/plain", r["Content-Type"])
