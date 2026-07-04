from django.core.management import call_command
from django.test import TestCase

from apps.jobs.models import JobPosting

from .generator import ensure_screening, retrieve
from .models import ScreeningAnswer, ScreeningQuestion


class ScreeningTests(TestCase):
    def setUp(self):
        call_command("seed_kb")
        self.job = JobPosting.objects.create(
            job_id="sc1", title="Django", budget_type="hourly",
            raw={"screening_questions": [
                "How many years of experience with Django REST Framework?",
                "What is your weekly availability and timezone overlap?",
            ]},
        )

    def test_retrieve_matches_relevant_fact(self):
        facts = retrieve("How many years with Django REST Framework?")
        self.assertTrue(facts)
        self.assertIn("Django REST Framework", facts[0].content)

    def test_ensure_creates_questions_and_answers(self):
        made = ensure_screening(self.job)
        self.assertEqual(made, 2)
        self.assertEqual(ScreeningQuestion.objects.filter(job=self.job).count(), 2)
        self.assertEqual(ScreeningAnswer.objects.count(), 2)
        # availability question retrieves the availability fact
        q = ScreeningQuestion.objects.get(job=self.job, order=1)
        self.assertIn("hrs/week", q.answer.body)

    def test_ensure_is_idempotent(self):
        ensure_screening(self.job)
        made = ensure_screening(self.job)  # second run makes nothing new
        self.assertEqual(made, 0)
