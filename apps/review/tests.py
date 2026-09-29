from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.jobs.models import ClientProfile, JobPosting
from apps.scoring.models import JobScore

from .card import card_text, keyboard_spec
from .notify import notify_autopilot_jobs, notify_scored_jobs


@override_settings(SITE_URL="http://testhost")
class CardTests(TestCase):
    def setUp(self):
        c = ClientProfile.objects.create(
            upwork_client_id="c1", verified_payment=True, hire_rate=82,
            total_spent=210000, country="United States",
        )
        self.job = JobPosting.objects.create(
            job_id="rv1", title="Senior Django Developer", budget_type="hourly",
            budget_min=45, budget_max=65, skills=["Django"], client=c,
            status=JobPosting.Status.DRAFTED,
        )
        JobScore.objects.create(job=self.job, score=88, reasoning="Стек совпадает")

    def test_card_text_has_key_fields(self):
        t = card_text(self.job)
        self.assertIn("Senior Django Developer", t)
        self.assertIn("Score 88/100", t)
        self.assertIn("$45–65/hr", t)
        self.assertIn("низкий риск", t)
        self.assertIn(f"http://testhost/job/{self.job.pk}/", t)

    def test_keyboard_spec_shape(self):
        spec = keyboard_spec(7)
        self.assertEqual(spec[0][0]["cb"], "approve:7")
        self.assertEqual(spec[0][1]["cb"], "skip:7")
        self.assertIn("edit=1", spec[1][0]["url"])


@override_settings(TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="1", NOTIFY_MIN_SCORE=70,
                   SITE_URL="http://testhost")
class NotifyScoredTests(TestCase):
    def _job(self, score, job_id="n1"):
        from django.utils import timezone
        job = JobPosting.objects.create(job_id=job_id, title="React dev", budget_type="fixed",
                                        status=JobPosting.Status.SCORED, posted_at=timezone.now(),
                                        raw={"url": "https://www.upwork.com/jobs/~01x"})
        JobScore.objects.create(job=job, score=score, reasoning="fits")
        self._job_pk = job.pk
        return job

    def test_skips_stale_posting(self):
        from datetime import timedelta
        from django.utils import timezone
        job = self._job(90, "stale")
        JobPosting.objects.filter(pk=job.pk).update(posted_at=timezone.now() - timedelta(hours=48))
        with patch("apps.review.notify.send_telegram", return_value=True) as send:
            self.assertEqual(notify_scored_jobs()["sent"], 0)  # too old to race to
        send.assert_not_called()

    def test_pings_high_score_and_marks_notified(self):
        job = self._job(85)
        with patch("apps.review.notify.send_telegram", return_value=True) as send:
            self.assertEqual(notify_scored_jobs()["sent"], 1)
        send.assert_called_once()
        job.refresh_from_db()
        self.assertIsNotNone(job.review_notified_at)  # dedup marker set

    def test_skips_low_score(self):
        self._job(55)
        with patch("apps.review.notify.send_telegram", return_value=True) as send:
            self.assertEqual(notify_scored_jobs()["sent"], 0)
        send.assert_not_called()

    def test_does_not_reping_already_notified(self):
        self._job(90)
        with patch("apps.review.notify.send_telegram", return_value=True):
            notify_scored_jobs()
        with patch("apps.review.notify.send_telegram", return_value=True) as send2:
            self.assertEqual(notify_scored_jobs()["sent"], 0)  # second run pings nobody
        send2.assert_not_called()

    def test_buttons_include_upwork_and_card_on_public_site(self):
        from .notify import _buttons
        row = _buttons(self._job(80))[0]  # SITE_URL=http://testhost is public
        urls = [b["url"] for b in row]
        self.assertTrue(any("upwork.com" in u for u in urls))
        self.assertTrue(any("testhost/job/" in u for u in urls))

    @override_settings(SITE_URL="http://localhost:8012")
    def test_localhost_card_becomes_ip_button(self):
        from .notify import _buttons
        row = _buttons(self._job(80))[0]
        # Telegram rejects "localhost" in button URLs but accepts an IP
        self.assertEqual(row[0]["url"], f"http://127.0.0.1:8012/job/{self._job_pk}/")
        self.assertTrue(all("localhost" not in b["url"] for b in row))

    @override_settings(TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    def test_noop_without_token(self):
        self._job(95)
        self.assertEqual(notify_scored_jobs()["sent"], 0)  # skipped, not crashed


@override_settings(TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="1", NOTIFY_MIN_SCORE=70,
                   AUTOPILOT_MIN_SCORE=80, SITE_URL="http://testhost", ANTHROPIC_API_KEY="")
class AutopilotTests(TestCase):
    def _job(self, mode, chat="", job_id="a1"):
        from django.utils import timezone

        from apps.jobs.models import SavedFilter
        from apps.tracks.models import Track
        track = Track.objects.create(name=f"t-{job_id}", mode=mode, telegram_chat_id=chat)
        f = SavedFilter.objects.create(name=f"f-{job_id}", track=track)
        job = JobPosting.objects.create(job_id=job_id, title="Site <build>", budget_type="fixed",
                                        status=JobPosting.Status.SCORED, posted_at=timezone.now(),
                                        matched_filter=f, raw={"url": "https://www.upwork.com/jobs/~01x"})
        JobScore.objects.create(job=job, score=90, reasoning="fits")
        return job

    def test_sends_full_letter_to_track_chat_then_manual_ping_skips_it(self):
        job = self._job("autopilot", chat="42")
        with patch("apps.review.notify.send_telegram", return_value=True) as send:
            self.assertEqual(notify_autopilot_jobs()["sent"], 1)
            self.assertEqual(notify_scored_jobs()["sent"], 0)  # already handled
        text = send.call_args.args[0]
        self.assertIn("<pre>", text)
        self.assertIn("Site &lt;build&gt;", text)  # HTML-escaped
        self.assertEqual(send.call_args.kwargs["chat_id"], "42")
        job.refresh_from_db()
        self.assertEqual(job.status, JobPosting.Status.DRAFTED)

    def test_failed_send_retries_without_redrafting(self):
        job = self._job("autopilot")
        with patch("apps.review.notify.send_telegram", return_value=False):
            notify_autopilot_jobs()
        with patch("apps.review.notify.send_telegram", return_value=True):
            self.assertEqual(notify_autopilot_jobs()["sent"], 1)
        self.assertEqual(job.cover_drafts.count(), 1)

    def test_manual_track_not_autopiloted_and_off_track_not_polled(self):
        from apps.jobs.models import SavedFilter
        self._job("manual", job_id="m1")
        off = self._job("off", job_id="o1")
        with patch("apps.review.notify.send_telegram", return_value=True):
            self.assertEqual(notify_autopilot_jobs()["sent"], 0)
        self.assertNotIn(off.matched_filter, SavedFilter.live())

    def test_empty_draft_is_redone_not_sent(self):
        from apps.letters.models import CoverLetterDraft
        job = self._job("autopilot", job_id="e1")
        CoverLetterDraft.objects.create(job=job, version=1, body="", is_active=True)
        with patch("apps.review.notify.send_telegram", return_value=True) as send:
            self.assertEqual(notify_autopilot_jobs()["sent"], 1)
        self.assertNotIn("<pre></pre>", send.call_args.args[0])


class AgeLabelTests(TestCase):
    def test_minutes_then_hours(self):
        from datetime import timedelta

        from django.utils import timezone

        from .notify import _age
        now = timezone.now()
        self.assertEqual(_age(JobPosting(posted_at=now - timedelta(minutes=7))), "⏱ 7 мин назад")
        self.assertEqual(_age(JobPosting(posted_at=now - timedelta(hours=5))), "⏱ 5 ч назад")
        self.assertEqual(_age(JobPosting(posted_at=None)), "")

    def test_head_order_and_russian_plurals(self):
        from django.utils import timezone

        from apps.scoring.models import JobScore

        from .notify import _head, _points
        self.assertEqual([_points(n) for n in (1, 21, 62, 11, 12, 55)],
                         ["1 балл", "21 балл", "62 балла", "11 баллов", "12 баллов", "55 баллов"])
        c = ClientProfile.objects.create(upwork_client_id="ng", country="Nigeria")
        j = JobPosting.objects.create(job_id="h", title="t", budget_type="fixed", budget_min=100,
                                      client=c, posted_at=timezone.now())
        JobScore.objects.create(job=j, score=62, reasoning="r")
        head = _head(JobPosting.objects.select_related("client", "score").get(pk=j.pk))
        self.assertEqual(head[:3], ["💵 $100 fixed", "🎯 62 балла", "🇳🇬 Нигерия"])
