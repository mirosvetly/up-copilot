from django.test import TestCase, override_settings

from apps.jobs.models import ClientProfile, JobPosting
from apps.scoring.models import JobScore

from .card import card_text, keyboard_spec


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
