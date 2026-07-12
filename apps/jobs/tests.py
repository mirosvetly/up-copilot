from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from .models import JobPosting, SavedFilter
from .presenters import _budget, _fmt_spent, job_card
from .providers.gmail import parse_alert
from .providers.mock import MockProvider
from .providers.vibeworker import VibeworkerProvider
from .tasks import collect_for_filter


class OverheatedTests(TestCase):
    def _card(self, connects):
        job = JobPosting(job_id="o1", title="t", budget_type="hourly", skills=[],
                         raw={"connects": connects} if connects is not None else {})
        return job_card(job, my_skills_lc=set())

    @override_settings(HOT_CONNECTS_THRESHOLD=16)
    def test_high_connects_marks_overheated(self):
        c = self._card(20)
        self.assertTrue(c["overheated"])
        self.assertEqual(c["connects"], 20)

    @override_settings(HOT_CONNECTS_THRESHOLD=16)
    def test_low_connects_not_overheated(self):
        self.assertFalse(self._card(8)["overheated"])

    @override_settings(HOT_CONNECTS_THRESHOLD=16)
    def test_missing_connects_not_overheated(self):
        c = self._card(None)  # Gmail jobs / older rows have no connects field
        self.assertFalse(c["overheated"])
        self.assertIsNone(c["connects"])


class ToggleKeywordTests(TestCase):
    def _job(self):
        from apps.tracks.models import Track
        t = Track.objects.create(name="Dev", is_default=True)
        f = SavedFilter.objects.create(name="dev", track=t, keywords=["react"])
        return JobPosting.objects.create(job_id="kw", title="t", budget_type="fixed",
                                         status=JobPosting.Status.SCORED,
                                         skills=["Strapi", "React"], matched_filter=f), f

    def test_tag_in_search_flag(self):
        job, _ = self._job()
        tags = {t["label"]: t["in_search"] for t in job_card(job, my_skills_lc=set())["tags"]}
        self.assertTrue(tags["React"])    # keyword "react" already in the search
        self.assertFalse(tags["Strapi"])  # not yet

    def test_toggle_adds_then_removes_keyword(self):
        job, f = self._job()
        self.client.post(f"/job/{job.pk}/toggle-keyword/", {"kw": "Strapi", "next": "/"})
        f.refresh_from_db()
        self.assertIn("Strapi", f.keywords)
        self.client.post(f"/job/{job.pk}/toggle-keyword/", {"kw": "Strapi", "next": "/"})
        f.refresh_from_db()
        self.assertNotIn("Strapi", f.keywords)  # second click removes it

    def test_toggle_dedups_case_insensitively(self):
        job, f = self._job()
        self.client.post(f"/job/{job.pk}/toggle-keyword/", {"kw": "React", "next": "/"})
        f.refresh_from_db()
        self.assertEqual(f.keywords, [])  # "React" matched existing "react" -> removed, not doubled


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

    @override_settings(MAX_JOB_AGE_HOURS=24)
    def test_stale_jobs_are_not_imported(self):
        from datetime import timedelta

        from django.utils import timezone

        from .providers.base import RawClient, RawJob

        now = timezone.now()

        def mk(jid, age_h):
            return RawJob(
                job_id=jid, title="t", description="d", skills=[], budget_type="fixed",
                budget_min=None, budget_max=None, currency="USD", proposals_bucket="",
                posted_at=now - timedelta(hours=age_h),
                client=RawClient(upwork_client_id="c:" + jid), raw={"source": "vibeworker"},
            )

        class Stub:
            def fetch_jobs(self, f):
                return [mk("fresh", 2), mk("stale", 48)]

        collect_for_filter(self.f, provider=Stub())
        ids = set(JobPosting.objects.values_list("job_id", flat=True))
        self.assertIn("fresh", ids)
        self.assertNotIn("stale", ids)  # older than 24h -> skipped, never scored

    def test_deleted_jobs_are_not_reimported(self):
        from .models import SeenJob

        # First poll imports the mock jobs and records them as seen.
        first = collect_for_filter(self.f, provider=self.provider)
        self.assertEqual(first["created"], 4)
        self.assertEqual(SeenJob.objects.count(), 4)
        # User clears them from the DB (like "Skip all").
        JobPosting.objects.all().delete()
        # Re-poll: the API returns the same jobs, but the ledger skips them —
        # nothing re-created, so nothing re-scored (no paying twice).
        again = collect_for_filter(self.f, provider=self.provider)
        self.assertEqual(again["created"], 0)
        self.assertEqual(JobPosting.objects.count(), 0)

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
        from django.utils import timezone

        from .providers.base import RawClient, RawJob

        def _job(source, client_id, **client_kw):
            return RawJob(
                job_id="x1", title="t", description="d", skills=[], budget_type="fixed",
                budget_min=None, budget_max=None, currency="USD", proposals_bucket="",
                posted_at=timezone.now(),  # fresh, so the age filter keeps it
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

    def test_non_upwork_rows_are_dropped(self):
        # Vibeworker sometimes returns freelancer.com etc. — Upwork only. The
        # host must match, not a substring (notupwork.com / upwork.com.evil.com
        # both contain "upwork.com" but are not Upwork).
        from apps.jobs.providers.vibeworker import _is_upwork

        self.assertTrue(_is_upwork("https://www.upwork.com/jobs/~01a"))
        self.assertTrue(_is_upwork("https://upwork.com/jobs/~01a"))
        self.assertFalse(_is_upwork("https://www.freelancer.com/projects/x"))
        self.assertFalse(_is_upwork("https://notupwork.com/jobs/~01a"))       # substring bypass
        self.assertFalse(_is_upwork("https://upwork.com.evil.com/jobs/~01a"))  # subdomain bypass
        self.assertFalse(_is_upwork("https://evil.com/?u=upwork.com"))         # query bypass

        f = SavedFilter.objects.create(name="all", keywords=[])
        bad = dict(VW_ROW, id="vw_fl", upworkUrl="https://upwork.com.evil.com/x")
        with patch("apps.jobs.providers.vibeworker.requests.get") as get:
            get.return_value = _FakeResponse([VW_ROW, bad])
            jobs = VibeworkerProvider().fetch_jobs(f)
        self.assertEqual(len(jobs), 1)  # only the genuine upwork.com host kept
        self.assertIn("upwork.com/jobs", jobs[0].raw["url"])

    def test_maps_upwork_url_for_detail_page(self):
        # The detail presenter reads raw["url"]; Vibeworker calls it upworkUrl.
        f = SavedFilter.objects.create(name="all", keywords=[])
        jobs, _ = self._fetch([VW_ROW], f)
        self.assertEqual(jobs[0].raw["url"], VW_ROW["upworkUrl"])

    @override_settings(COLLECT_MAX_CONNECTS=16)
    def test_crowded_rows_dropped_at_collect(self):
        f = SavedFilter.objects.create(name="all", keywords=[])
        crowded = dict(VW_ROW, id="vw_hot", upworkUrl="https://upwork.com/jobs/~02hot",
                       connects=20)
        jobs, _ = self._fetch([VW_ROW, crowded], f)  # VW_ROW has connects 11
        self.assertEqual(len(jobs), 1)  # the 20-connect posting never enters the DB
        self.assertEqual(jobs[0].job_id, "01abc234def567")

    @override_settings(COLLECT_MAX_CONNECTS=0)
    def test_crowd_filter_off_keeps_everything(self):
        f = SavedFilter.objects.create(name="all", keywords=[])
        crowded = dict(VW_ROW, id="vw_hot", upworkUrl="https://upwork.com/jobs/~02hot",
                       connects=99)
        jobs, _ = self._fetch([VW_ROW, crowded], f)
        self.assertEqual(len(jobs), 2)  # 0 disables the cap

    @override_settings(EXCLUDE_KEYWORDS=["wordpress", "webflow"])
    def test_excluded_by_title_not_by_skill_tag(self):
        f = SavedFilter.objects.create(name="all", keywords=[])
        nocode = dict(VW_ROW, id="vw_wp", upworkUrl="https://upwork.com/jobs/~02wp",
                      title="WordPress + Elementor Landing Page", skills=["PHP"])
        # A real Next.js job that merely TAGS WordPress must survive.
        codejob = dict(VW_ROW, id="vw_code", upworkUrl="https://upwork.com/jobs/~03code",
                       title="Next.js Full-Stack Developer", skills=["Next.js", "WordPress"])
        jobs, _ = self._fetch([nocode, codejob], f)
        self.assertEqual({j.job_id for j in jobs}, {"03code"})  # only the no-code title dropped

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


class FeedTrackFilterTests(TestCase):
    def setUp(self):
        from apps.tracks.models import Track

        Track.objects.all().delete()  # drop the migration-seeded track for a clean pill set
        self.dev = Track.objects.create(name="DevTrack", is_default=True)
        self.land = Track.objects.create(name="LandTrack")
        self.fdev = SavedFilter.objects.create(name="d", track=self.dev)
        self.fland = SavedFilter.objects.create(name="l", track=self.land)
        JobPosting.objects.create(job_id="d1", title="Django job", budget_type="fixed", matched_filter=self.fdev)
        JobPosting.objects.create(job_id="l1", title="Webflow job", budget_type="fixed", matched_filter=self.fland)

    def test_all_shows_both(self):
        r = self.client.get("/")
        self.assertContains(r, "Django job")
        self.assertContains(r, "Webflow job")

    def test_track_filter_narrows_to_one_track(self):
        r = self.client.get(f"/?track={self.land.pk}")
        self.assertNotContains(r, "Django job")
        self.assertContains(r, "Webflow job")

    def test_pills_carry_counts_and_bad_track_falls_back_to_all(self):
        r = self.client.get("/?track=notanid")
        self.assertContains(r, "Django job")  # invalid track -> show all, no 500
        pills = r.context["track_pills"]
        self.assertEqual(pills[0]["label"], "Все")
        self.assertEqual({p["label"]: p["count"] for p in pills}["DevTrack"], 1)


class SkipAllViewTests(TestCase):
    def setUp(self):
        from apps.tracks.models import Track

        self.dev = Track.objects.create(name="Dev", is_default=True)
        self.fdev = SavedFilter.objects.create(name="d", track=self.dev)
        self.new = JobPosting.objects.create(job_id="sa-new", title="t", budget_type="fixed",
                                             status=JobPosting.Status.NEW, matched_filter=self.fdev)
        self.scored = JobPosting.objects.create(job_id="sa-sc", title="t", budget_type="fixed",
                                                status=JobPosting.Status.SCORED, matched_filter=self.fdev)
        self.drafted = JobPosting.objects.create(job_id="sa-dr", title="t", budget_type="fixed",
                                                 status=JobPosting.Status.DRAFTED, matched_filter=self.fdev)
        self.applied = JobPosting.objects.create(job_id="sa-ap", title="t", budget_type="fixed",
                                                 status=JobPosting.Status.APPLIED, matched_filter=self.fdev)
        self.skipped = JobPosting.objects.create(job_id="sa-sk", title="t", budget_type="fixed",
                                                 status=JobPosting.Status.SKIPPED, matched_filter=self.fdev)

    def test_skip_all_deletes_only_untouched(self):
        r = self.client.post("/skip-all/", {"track": "all", "next": "/"})
        self.assertEqual(r.status_code, 302)
        ids = set(JobPosting.objects.values_list("job_id", flat=True))
        # new+scored+skipped deleted (skipped cards must clear too); drafted/applied kept
        self.assertEqual(ids, {"sa-dr", "sa-ap"})

    def test_skip_all_respects_track_filter(self):
        from apps.tracks.models import Track

        other = Track.objects.create(name="Other")
        fo = SavedFilter.objects.create(name="o", track=other)
        JobPosting.objects.create(job_id="sa-other", title="t", budget_type="fixed",
                                  status=JobPosting.Status.NEW, matched_filter=fo)
        self.client.post("/skip-all/", {"track": str(other.pk), "next": "/"})
        # only the other-track NEW job removed; dev-track new/scored untouched
        self.assertFalse(JobPosting.objects.filter(job_id="sa-other").exists())
        self.assertTrue(JobPosting.objects.filter(job_id="sa-new").exists())


class RefreshViewTests(TestCase):
    def test_refresh_collects_now_and_redirects(self):
        # Collection is synchronous (fast); scoring is kicked to a background
        # thread, so we only assert the sync part here.
        SavedFilter.objects.create(name="all", keywords=[], is_active=True)
        r = self.client.post("/refresh/", {"next": "/"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/")
        self.assertTrue(JobPosting.objects.exists())  # mock provider collected jobs

    def test_refresh_offsite_next_falls_back_to_feed(self):
        r = self.client.post("/refresh/", {"next": "//evil.com"})
        self.assertEqual(r["Location"], "/")  # not off-site

    def test_refresh_ajax_returns_json(self):
        SavedFilter.objects.create(name="all", keywords=[], is_active=True)
        r = self.client.post("/refresh/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 200)
        self.assertIn("created", r.json())  # browser auto-poll gets JSON, not a redirect


class SentViewTests(TestCase):
    def setUp(self):
        JobPosting.objects.create(job_id="n1", title="new job", budget_type="fixed",
                                  status=JobPosting.Status.NEW)
        JobPosting.objects.create(job_id="s1", title="sent job", budget_type="fixed",
                                  status=JobPosting.Status.APPLIED)

    def test_review_feed_excludes_sent(self):
        r = self.client.get("/")
        self.assertContains(r, "new job")
        self.assertNotContains(r, "sent job")  # sent moved out of the review feed

    def test_sent_view_shows_only_sent(self):
        r = self.client.get("/sent/")
        self.assertContains(r, "sent job")
        self.assertNotContains(r, "new job")


class LazyTranslationTests(TestCase):
    def test_detail_serves_english_and_flags_translating_when_ru_missing(self):
        job = JobPosting.objects.create(
            job_id="lt1", title="t", budget_type="fixed", description="Some description",
        )
        r = self.client.get(f"/job/{job.pk}/?lang=ru")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["translating"])         # RU not cached -> background it
        self.assertEqual(r.context["content_lang"], "en")  # page opens in English

    def test_detail_serves_ru_when_cached_no_translating(self):
        job = JobPosting.objects.create(
            job_id="lt2", title="t", budget_type="fixed",
            description="Some description", description_ru="Некое описание",
        )
        r = self.client.get(f"/job/{job.pk}/?lang=ru")
        self.assertFalse(r.context["translating"])
        self.assertEqual(r.context["content_lang"], "ru")

    def test_tr_status_endpoint(self):
        job = JobPosting.objects.create(job_id="lt3", title="t", budget_type="fixed", description="d")
        self.assertFalse(self.client.get(f"/job/{job.pk}/tr-status/").json()["ready"])
        job.description_ru = "перевод"
        job.save(update_fields=["description_ru"])
        self.assertTrue(self.client.get(f"/job/{job.pk}/tr-status/").json()["ready"])


class ContentLangTests(TestCase):
    def test_job_detail_picks_language_for_title_and_description(self):
        from .presenters import job_detail

        job = JobPosting.objects.create(
            job_id="cl1", title="Build app", title_ru="Собрать приложение",
            description="Long desc", description_ru="Длинное описание", budget_type="fixed",
        )
        self.assertEqual(job_detail(job, "ru")["description"], "Длинное описание")
        self.assertEqual(job_detail(job, "en")["description"], "Long desc")
        self.assertEqual(job_detail(job, "ru")["title"], "Собрать приложение")
        self.assertEqual(job_detail(job, "en")["title"], "Build app")

    def test_job_detail_uses_ru_breakdown_when_available(self):
        from apps.scoring.models import JobScore

        from .presenters import job_detail

        job = JobPosting.objects.create(job_id="cl2", title="t", budget_type="fixed")
        JobScore.objects.create(
            job=job, score=60,
            breakdown=[{"text": "Stack match", "w": 10, "neg": False}],
            breakdown_ru=[{"text": "Совпадение стека", "w": 10, "neg": False}],
        )
        job.refresh_from_db()
        self.assertEqual(job_detail(job, "ru")["reasons"][0]["text"], "Совпадение стека")
        self.assertEqual(job_detail(job, "en")["reasons"][0]["text"], "Stack match")


class I18nTests(TestCase):
    def test_feed_defaults_to_russian(self):
        self.assertContains(self.client.get("/"), "Лента вакансий")

    def test_feed_renders_in_english_via_cookie(self):
        self.client.cookies["django_language"] = "en"
        r = self.client.get("/")
        self.assertContains(r, "Job feed")
        self.assertNotContains(r, "Лента вакансий")  # no Russian chrome leaking through

    def test_set_language_switches(self):
        r = self.client.post("/i18n/setlang/", {"language": "en", "next": "/"})
        self.assertEqual(r.status_code, 302)
        self.assertContains(self.client.get("/"), "Settings")  # sticks via cookie


class UpworkUrlSafetyTests(TestCase):
    def test_javascript_url_is_stripped(self):
        from .presenters import job_detail

        job = JobPosting.objects.create(
            job_id="xss1", title="t", budget_type="fixed",
            raw={"url": "javascript:alert(document.cookie)"},
        )
        self.assertEqual(job_detail(job)["upwork_url"], "")  # not passed to href/window.open

    def test_https_url_passes(self):
        from .presenters import job_detail

        job = JobPosting.objects.create(
            job_id="ok1", title="t", budget_type="fixed",
            raw={"url": "https://www.upwork.com/jobs/~01a"},
        )
        self.assertEqual(job_detail(job)["upwork_url"], "https://www.upwork.com/jobs/~01a")


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
