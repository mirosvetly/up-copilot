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


class CopyOpenButtonTests(TestCase):
    def _drafted_job(self):
        job = JobPosting.objects.create(
            job_id="cb1", title="t", budget_type="fixed",
            status=JobPosting.Status.SCORED,
            raw={"url": "https://www.upwork.com/jobs/~01abc"},
        )
        generate_cover(job)  # scored -> drafted, active draft exists
        return job

    def test_detail_renders_copy_and_open_button(self):
        job = self._drafted_job()
        r = self.client.get(f"/job/{job.pk}/")
        self.assertContains(r, "Скопировать письмо и открыть на Upwork")
        self.assertContains(r, "https://www.upwork.com/jobs/~01abc")  # data-url
        self.assertContains(r, "ucCopyOpen")
        self.assertContains(r, f"/job/{job.pk}/mark_sent/")  # button posts mark_sent

    def test_copy_button_marks_sent_then_undo_returns_to_drafted(self):
        job = self._drafted_job()  # status drafted
        self.client.post(f"/job/{job.pk}/mark_sent/", {"next": f"/job/{job.pk}/"})
        job.refresh_from_db()
        self.assertEqual(job.status, JobPosting.Status.APPLIED)
        # detail now shows the sent badge + Вернуть, not the copy button
        r = self.client.get(f"/job/{job.pk}/")
        self.assertContains(r, "Отправлено на Upwork")
        self.assertContains(r, "unsend")
        # undo
        self.client.post(f"/job/{job.pk}/unsend/", {"next": f"/job/{job.pk}/"})
        job.refresh_from_db()
        self.assertEqual(job.status, JobPosting.Status.DRAFTED)


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

    def test_generated_letter_has_no_em_dashes(self):
        from .generator import _dedash

        self.assertEqual(_dedash("Week 1 — schema, auth — RLS"), "Week 1, schema, auth, RLS")
        job = self._job()
        draft = generate_cover(job)
        self.assertNotIn("—", draft.body)
        self.assertNotIn("–", draft.body)
        self.assertNotIn("—", "".join(s["t"] for s in draft.segments))

    def test_version_survives_a_gap_left_by_a_deleted_draft(self):
        # count()-based versioning collided when a draft was deleted; max+1 must not.
        job = self._job()
        generate_cover(job)  # v0
        generate_cover(job)  # v1
        CoverLetterDraft.objects.filter(job=job, version=0).delete()  # gap: only v1 left
        third = generate_cover(job)
        self.assertEqual(third.version, 2)  # max(1)+1, not count()==1 -> collision
        self.assertTrue(third.is_active)

    def test_failed_create_does_not_orphan_the_active_draft(self):
        # A generate that raises mid-save must leave the previous active draft active,
        # not deactivate it (the bug that showed "not generated" while a draft existed).
        from unittest.mock import patch

        job = self._job()
        first = generate_cover(job)
        with patch.object(CoverLetterDraft.objects, "create", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                generate_cover(job)
        first.refresh_from_db()
        self.assertTrue(first.is_active)  # survivor still active
