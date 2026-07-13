from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.jobs.models import ClientProfile, JobPosting
from apps.scoring.models import JobScore

from .card import card_text, keyboard_spec
from .notify import notify_scored_jobs


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
    def test_localhost_card_not_a_button_but_in_text(self):
        from .notify import _buttons, _text
        job = self._job(80)
        # Telegram rejects localhost button URLs — only the Upwork button remains
        row = _buttons(job)[0]
        self.assertTrue(all("localhost" not in b["url"] for b in row))
        self.assertTrue(any("upwork.com" in b["url"] for b in row))
        self.assertIn("localhost:8012/job/", _text(job))  # card link lives in the text

    @override_settings(TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    def test_noop_without_token(self):
        self._job(95)
        self.assertEqual(notify_scored_jobs()["sent"], 0)  # skipped, not crashed
