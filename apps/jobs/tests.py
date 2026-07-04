from decimal import Decimal

from django.test import TestCase

from .models import JobPosting, SavedFilter
from .presenters import _budget, _fmt_spent
from .providers.mock import MockProvider
from .tasks import collect_for_filter


class BudgetFormatTests(TestCase):
    def test_fixed_keeps_trailing_zeros(self):
        j = JobPosting(budget_type="fixed", budget_min=Decimal("2500"))
        self.assertEqual(_budget(j), "$2,500 fixed")

    def test_hourly_range(self):
        j = JobPosting(budget_type="hourly", budget_min=Decimal("45"), budget_max=Decimal("65"))
        self.assertEqual(_budget(j), "$45–65/hr")

    def test_hourly_round_rate(self):
        j = JobPosting(budget_type="hourly", budget_min=Decimal("50"), budget_max=None)
        self.assertEqual(_budget(j), "$50/hr")


class SpentFormatTests(TestCase):
    def test_round_hundred_thousands_no_exponent(self):
        self.assertEqual(_fmt_spent(Decimal("210000.00")), "$210K+")  # regression: not "$2.1E+2K+"

    def test_fractional_k(self):
        self.assertEqual(_fmt_spent(Decimal("6200")), "$6.2K+")

    def test_small_and_none(self):
        self.assertEqual(_fmt_spent(Decimal("0")), "$0")
        self.assertEqual(_fmt_spent(None), "—")


class StatusMachineTests(TestCase):
    def test_legal_transition(self):
        job = JobPosting.objects.create(job_id="t1", title="x", budget_type="fixed")
        job.transition_to(JobPosting.Status.SCORED)
        self.assertEqual(job.status, JobPosting.Status.SCORED)

    def test_illegal_transition_raises(self):
        job = JobPosting.objects.create(job_id="t2", title="x", budget_type="fixed")
        with self.assertRaises(ValueError):
            job.transition_to(JobPosting.Status.APPLIED)  # new -> applied is illegal


class CollectorTests(TestCase):
    def setUp(self):
        self.f = SavedFilter.objects.create(name="all", keywords=[])
        self.provider = MockProvider()

    def test_collect_creates_and_dedups(self):
        first = collect_for_filter(self.f, provider=self.provider)
        self.assertEqual(first["created"], 4)
        # Second run sees the same 4 but creates none (dedup on job_id).
        second = collect_for_filter(self.f, provider=self.provider)
        self.assertEqual(second["created"], 0)
        self.assertEqual(JobPosting.objects.count(), 4)

    def test_dedup_preserves_status(self):
        collect_for_filter(self.f, provider=self.provider)
        job = JobPosting.objects.get(job_id="mock-j1")
        job.transition_to(JobPosting.Status.SKIPPED)
        collect_for_filter(self.f, provider=self.provider)  # re-poll
        job.refresh_from_db()
        self.assertEqual(job.status, JobPosting.Status.SKIPPED)  # not reset to new

    def test_keyword_filter(self):
        f = SavedFilter.objects.create(name="mql", keywords=["MQL5"])
        r = collect_for_filter(f, provider=self.provider)
        self.assertEqual(r["seen"], 1)  # only the MT5 job matches


class JobActionViewTests(TestCase):
    def _job(self, status=JobPosting.Status.SCORED):
        return JobPosting.objects.create(
            job_id="v1", title="t", budget_type="fixed", status=status
        )

    def test_approve_redirects_to_local_next(self):
        job = self._job()
        r = self.client.post(f"/job/{job.pk}/approve/", {"next": f"/job/{job.pk}/"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], f"/job/{job.pk}/")
        job.refresh_from_db()
        self.assertEqual(job.status, JobPosting.Status.REVIEWED)

    def test_next_rejects_protocol_relative_open_redirect(self):
        job = self._job()
        r = self.client.post(f"/job/{job.pk}/approve/", {"next": "//evil.com"})
        self.assertEqual(r["Location"], "/")  # falls back to feed, not off-site

    def test_illegal_transition_does_not_500(self):
        job = self._job(status=JobPosting.Status.APPLIED)  # applied -> approve is illegal
        r = self.client.post(f"/job/{job.pk}/approve/", {"next": "/"})
        self.assertEqual(r.status_code, 302)  # handled, no crash
        job.refresh_from_db()
        self.assertEqual(job.status, JobPosting.Status.APPLIED)
