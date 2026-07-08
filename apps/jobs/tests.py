from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from .models import JobPosting, SavedFilter
from .presenters import _budget, _fmt_spent
from .providers.gmail import parse_alert
from .providers.mock import MockProvider
from .providers.vibeworker import VibeworkerProvider
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

    def test_repoll_from_sparser_source_keeps_richer_raw_and_client(self):
        from datetime import datetime, timezone as tz

        from .providers.base import RawClient, RawJob

        def _job(source, client_id, **client_kw):
            return RawJob(
                job_id="x1", title="t", description="d", skills=[], budget_type="fixed",
                budget_min=None, budget_max=None, currency="USD", proposals_bucket="",
                posted_at=datetime(2026, 7, 7, tzinfo=tz.utc),
                client=RawClient(upwork_client_id=client_id, **client_kw),
                raw={"source": source, "scores": {"quickWin": 8} if source == "vibeworker" else None},
            )

        class Stub:
            def __init__(self, job):
                self.job = job

            def fetch_jobs(self, f):
                return [self.job]

        rich = _job("vibeworker", "vw:x1", hire_rate=85, total_spent=Decimal("40000"))
        sparse = _job("gmail-alert", "gm:x1")
        collect_for_filter(self.f, provider=Stub(rich))
        collect_for_filter(self.f, provider=Stub(sparse))  # same job re-arrives via email
        job = JobPosting.objects.get(job_id="x1")
        self.assertEqual(job.raw["source"], "vibeworker")  # richer data not clobbered
        self.assertEqual(job.client.upwork_client_id, "vw:x1")


VW_ROW = {
    "id": "vw_b797267068b246bfa8da8722",
    "title": "Build a Next.js dashboard with Supabase backend",
    "category": "Web Development",
    "jobType": "fixed",
    "budget": 800,
    "budgetMax": None,
    "experienceLevel": "Intermediate",
    "duration": "Less than 1 month",
    "connects": 11,
    "hoursPerWeek": None,
    "skills": ["Next.js", "TypeScript", "Supabase"],
    "clientLocation": "United States",
    "clientPaymentVerified": True,
    "clientTotalSpent": 42000,
    "clientHireRate": 78,
    "clientRating": 4.9,
    "clientAvgRate": None,
    "description": "Build a clean admin dashboard...",
    "upworkUrl": "https://www.upwork.com/jobs/~01abc234def567",
    "scores": {"quickWin": 8, "scopeClarity": 9, "redFlags": 10, "effortHours": 14},
    "postedAt": "2026-06-08T09:31:00+00:00",
    "receivedAt": "2026-06-08T09:32:14.000+00:00",
}


class _FakeResponse:
    def __init__(self, rows, status_code=200, quota=99):
        self._rows = rows
        self.status_code = status_code
        self.quota = quota
        self.text = '{"error": "boom"}'

    def json(self):
        return {"data": self._rows, "count": len(self._rows), "quotaRemaining": self.quota}


@override_settings(VIBEWORKER_API_KEY="vw_test_key")
class VibeworkerProviderTests(TestCase):
    def _fetch(self, rows, saved_filter):
        with patch("apps.jobs.providers.vibeworker.requests.get") as get:
            get.return_value = _FakeResponse(rows)
            jobs = VibeworkerProvider().fetch_jobs(saved_filter)
        return jobs, get

    def test_maps_row_to_raw_job(self):
        f = SavedFilter.objects.create(name="all", keywords=[])
        jobs, _ = self._fetch([VW_ROW], f)
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual(j.job_id, "01abc234def567")  # upwork id from url, not vw_ id
        self.assertEqual(j.budget_type, "fixed")
        self.assertEqual(j.budget_min, Decimal("800"))
        self.assertIsNone(j.budget_max)
        self.assertEqual(j.posted_at.isoformat(), "2026-06-08T09:31:00+00:00")
        self.assertEqual(j.raw["scores"]["quickWin"], 8)  # scores kept for later phases
        c = j.client
        self.assertTrue(c.verified_payment)
        self.assertEqual(c.hire_rate, 78)
        self.assertEqual(c.total_spent, Decimal("42000"))
        self.assertEqual(c.avg_rating, Decimal("4.9"))
        self.assertEqual(c.country, "United States")

    def test_fans_out_keywords_and_dedups(self):
        f = SavedFilter.objects.create(name="kw", keywords=["react", "nextjs"])
        jobs, get = self._fetch([VW_ROW], f)
        self.assertEqual(get.call_count, 2)  # one request per keyword
        self.assertEqual(len(jobs), 1)  # same job from both requests → deduped
        sent = [c.kwargs["params"]["keywords"] for c in get.call_args_list]
        self.assertEqual(sent, ["react", "nextjs"])

    def test_filter_params_and_verified_payment(self):
        row = dict(VW_ROW, clientPaymentVerified=False)
        f = SavedFilter.objects.create(
            name="strict", keywords=[], min_budget=Decimal("500"), require_verified_payment=True
        )
        jobs, get = self._fetch([row], f)
        self.assertEqual(jobs, [])  # unverified client filtered client-side
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["minBudget"], "500")
        self.assertEqual(params["sort"], "newest")

    def test_maps_upwork_url_for_detail_page(self):
        # The detail presenter reads raw["url"]; Vibeworker calls it upworkUrl.
        f = SavedFilter.objects.create(name="all", keywords=[])
        jobs, _ = self._fetch([VW_ROW], f)
        self.assertEqual(jobs[0].raw["url"], VW_ROW["upworkUrl"])

    def test_missing_key_raises(self):
        f = SavedFilter.objects.create(name="all", keywords=[])
        with override_settings(VIBEWORKER_API_KEY=""):
            with self.assertRaises(RuntimeError):
                VibeworkerProvider().fetch_jobs(f)

    def test_mid_fanout_error_keeps_partial_results(self):
        # Jobs from earlier requests were already charged against the quota —
        # a failure on a later request must not throw them away.
        f = SavedFilter.objects.create(name="kw", keywords=["react", "nextjs"])
        with patch("apps.jobs.providers.vibeworker.requests.get") as get:
            get.side_effect = [_FakeResponse([VW_ROW]), _FakeResponse([], status_code=429)]
            jobs = VibeworkerProvider().fetch_jobs(f)
        self.assertEqual(len(jobs), 1)

    def test_quota_exhausted_stops_fanout(self):
        f = SavedFilter.objects.create(name="kw", keywords=["react", "nextjs"])
        with patch("apps.jobs.providers.vibeworker.requests.get") as get:
            get.return_value = _FakeResponse([VW_ROW], quota=0)
            jobs = VibeworkerProvider().fetch_jobs(f)
        self.assertEqual(get.call_count, 1)  # second keyword request skipped
        self.assertEqual(len(jobs), 1)

    def test_collect_jobs_survives_provider_error(self):
        # A broken filter must not abort the beat loop — and must retry on its
        # poll_interval_min cadence, not on every 60s beat tick.
        from .tasks import collect_jobs

        f = SavedFilter.objects.create(name="boom", keywords=[])
        with patch("apps.jobs.tasks.get_provider") as gp:
            gp.return_value.fetch_jobs.side_effect = RuntimeError("api down")
            totals = collect_jobs()
        self.assertEqual(totals["filters"], 0)  # logged and skipped, no crash
        f.refresh_from_db()
        self.assertIsNotNone(f.last_polled_at)  # failure still counts as a poll


ALERT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "upwork_alert_email.txt"


class GmailAlertParseTests(TestCase):
    def setUp(self):
        self.text = ALERT_FIXTURE.read_text()

    def _parse(self, text=None, subject="New job alert: AI-Assisted React Native / Expo Developer for Voic..."):
        from datetime import datetime, timezone as tz

        return parse_alert(text or self.text, subject, datetime(2026, 7, 7, 4, 37, tzinfo=tz.utc))

    def test_parses_fixture_alert(self):
        j = self._parse()
        self.assertEqual(j.job_id, "022074351669139735349")
        # Subject holds the longer title; the "..." truncation mark is stripped.
        self.assertEqual(j.title, "AI-Assisted React Native / Expo Developer for Voic")
        self.assertEqual(j.budget_type, "hourly")
        self.assertEqual(j.budget_min, Decimal("10.00"))
        self.assertEqual(j.budget_max, Decimal("70.00"))
        self.assertEqual(j.skills, ["React Native", "Expo.io"])
        self.assertIn("voice-first mobile app", j.description)
        self.assertNotIn("utm_medium", j.description)  # tracking links stripped
        self.assertNotIn("Est. time", j.description)  # budget-line tail stays out
        self.assertEqual(j.raw["url"], "https://www.upwork.com/jobs/~022074351669139735349")
        self.assertEqual(j.posted_at.isoformat(), "2026-07-07T04:37:00+00:00")
        c = j.client
        self.assertTrue(c.verified_payment)
        self.assertEqual(c.avg_rating, Decimal("5.0"))  # 4.95 rounded to model's 1 dp
        self.assertEqual(c.total_spent, Decimal("326000"))
        self.assertEqual(c.country, "United States")

    def test_fixed_budget_and_clientline_without_stars(self):
        text = self.text.replace(
            "Hourly: $10.00 - $70.00", "Fixed: $1,000.00"
        ).replace("Payment verified · 4.95 stars · $326K spent · United States",
                  "Payment verified · $120 spent · ARE")
        j = self._parse(text)
        self.assertEqual(j.budget_type, "fixed")
        self.assertEqual(j.budget_min, Decimal("1000.00"))
        self.assertIsNone(j.budget_max)
        self.assertIsNone(j.client.avg_rating)
        self.assertEqual(j.client.total_spent, Decimal("120"))
        self.assertEqual(j.client.country, "ARE")

    def test_hourly_zeros_mean_unspecified(self):
        text = self.text.replace("Hourly: $10.00 - $70.00", "Hourly: $0.00 - $0.00")
        j = self._parse(text)
        self.assertIsNone(j.budget_min)
        self.assertIsNone(j.budget_max)

    def test_money_in_description_does_not_hijack_client_line(self):
        # "$X spent" is ordinary job-post phrasing; the real client line is
        # the LAST such line, just before "View job details".
        text = self.text.replace(
            "We’re building a minimalist voice-first mobile app",
            "We have over $3,000 spent on ads so far · results were weak.\n\n"
            "We’re building a minimalist voice-first mobile app",
        )
        j = self._parse(text)
        self.assertTrue(j.client.verified_payment)
        self.assertEqual(j.client.total_spent, Decimal("326000"))
        self.assertEqual(j.client.country, "United States")

    def test_skills_heading_in_description_does_not_replace_real_skills(self):
        text = self.text.replace(
            "We’re building a minimalist voice-first mobile app",
            "Skills:\nmust know react\nmust know node\n\n"
            "We’re building a minimalist voice-first mobile app",
        )
        j = self._parse(text)
        self.assertEqual(j.skills, ["React Native", "Expo.io"])

    def test_budget_like_title_not_parsed_as_budget(self):
        text = self.text.replace(
            "AI-Assisted React Native / Expo Developer for V...:",
            "Fixed: $500 max budget, logo design for startu...:",
        )
        j = self._parse(text)
        self.assertEqual(j.budget_type, "hourly")  # from the real budget line
        self.assertEqual(j.budget_min, Decimal("10.00"))

    def test_crlf_body_parses_like_lf(self):
        # Real IMAP bodies use CRLF; regression for skills coming back empty.
        j = self._parse(self.text.replace("\n", "\r\n"))
        self.assertEqual(j.skills, ["React Native", "Expo.io"])
        self.assertEqual(j.budget_type, "hourly")

    def test_non_alert_email_returns_none(self):
        self.assertIsNone(parse_alert("Your password was changed.", "Security alert", None))


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
