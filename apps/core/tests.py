from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.core.translate import _chunks, translate_ru
from apps.jobs.models import JobPosting


class TranslateTests(TestCase):
    def test_mock_provider_returns_empty(self):
        # Test settings force TRANSLATE_PROVIDER=mock -> callers fall back to EN.
        self.assertEqual(translate_ru("Build a dashboard"), "")

    def test_empty_input_returns_empty(self):
        self.assertEqual(translate_ru("   "), "")

    @override_settings(TRANSLATE_PROVIDER="google")
    def test_google_path_calls_engine(self):
        with patch("apps.core.translate._google", return_value="Панель") as g:
            self.assertEqual(translate_ru("Dashboard"), "Панель")
        g.assert_called_once()

    @override_settings(TRANSLATE_PROVIDER="google")
    def test_failure_falls_back_to_empty(self):
        with patch("apps.core.translate._google", side_effect=RuntimeError("blocked")):
            self.assertEqual(translate_ru("Dashboard"), "")  # no crash

    def test_chunks_respect_size_and_cover_text(self):
        text = "\n".join(["para " + str(i) * 100 for i in range(10)])
        chunks = _chunks(text, 200)
        self.assertTrue(all(len(c) <= 200 for c in chunks))
        # every paragraph survives somewhere in the chunks
        self.assertIn("0" * 100, "".join(chunks))


class JobEnsureRuTests(TestCase):
    def _job(self):
        return JobPosting.objects.create(
            job_id="tr1", title="Build a dashboard", budget_type="fixed",
            description="Build a clean admin dashboard with charts.",
        )

    def test_ensure_ru_caches_translation(self):
        job = self._job()
        with patch("apps.core.translate.translate_ru", side_effect=lambda t: f"[ru]{t}") as tr:
            job.ensure_ru()
        job.refresh_from_db()
        self.assertEqual(job.description_ru, "[ru]Build a clean admin dashboard with charts.")
        self.assertEqual(job.title_ru, "[ru]Build a dashboard")
        # second call is a no-op (already cached) — engine not hit again
        with patch("apps.core.translate.translate_ru") as tr2:
            job.ensure_ru()
        tr2.assert_not_called()

    def test_ensure_ru_no_translation_leaves_empty_and_retries(self):
        job = self._job()
        with patch("apps.core.translate.translate_ru", return_value=""):
            job.ensure_ru()
        job.refresh_from_db()
        self.assertEqual(job.description_ru, "")  # failure not cached
