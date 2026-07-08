from django.test import TestCase

from apps.jobs.models import JobPosting

from .generator import generate_cover
from .github import MockGitHub
from .models import CoverLetterDraft


PROJECTS = [
    {"repo": "django-trade-api", "skills": ["Django", "DRF", "Celery"]},
    {"repo": "webrtc-signal", "skills": ["WebRTC", "Node.js"]},
]


class GitHubTests(TestCase):
    def test_relevant_by_overlap(self):
        repos = MockGitHub(projects=PROJECTS).relevant(["Django", "Celery"])
        self.assertEqual(repos[0].name, "django-trade-api")

    def test_relevant_falls_back_when_no_overlap(self):
        repos = MockGitHub(projects=PROJECTS).relevant(["COBOL"])
        self.assertEqual(len(repos), 1)  # never empty


class GeneratorTests(TestCase):
    def _job(self, status=JobPosting.Status.SCORED):
        return JobPosting.objects.create(
            job_id="g1", title="Django API", budget_type="hourly",
            skills=["Django", "Celery"], status=status,
        )

    def test_generate_creates_active_draft_and_transitions(self):
        job = self._job()
        draft = generate_cover(job)
        self.assertTrue(draft.is_active)
        self.assertIn("Best,\nMax", draft.body)
        self.assertTrue(any(s.get("src") for s in draft.segments))  # GitHub-sourced span
        job.refresh_from_db()
        self.assertEqual(job.status, JobPosting.Status.DRAFTED)

    def test_regenerate_versions_and_single_active(self):
        job = self._job()
        generate_cover(job)
        second = generate_cover(job)
        self.assertEqual(second.version, 1)
        self.assertEqual(CoverLetterDraft.objects.filter(job=job, is_active=True).count(), 1)
        self.assertEqual(CoverLetterDraft.objects.filter(job=job).count(), 2)
