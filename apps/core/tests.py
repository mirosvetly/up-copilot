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
    def test_real_path_calls_engine(self):
        with patch("apps.core.translate._translate", return_value="Панель") as g:
            self.assertEqual(translate_ru("Dashboard"), "Панель")
        g.assert_called_once()

    @override_settings(TRANSLATE_PROVIDER="google")
    def test_failure_falls_back_to_empty(self):
        with patch("apps.core.translate._translate", side_effect=RuntimeError("blocked")):
            self.assertEqual(translate_ru("Dashboard"), "")  # no crash

    @override_settings(TRANSLATE_PROVIDER="google")
    def test_hung_engine_times_out_to_empty(self):
        import time
        # A translator that never returns must not hang the page — the daemon
        # timeout kicks in and the caller falls back to English.
        with patch("apps.core.translate._TIMEOUT_S", 0.3), \
             patch("apps.core.translate._translate", side_effect=lambda t: time.sleep(30)):
            self.assertEqual(translate_ru("Dashboard"), "")

    def test_chunks_respect_size_and_cover_text(self):
        text = "\n".join(["para " + str(i) * 100 for i in range(10)])
        chunks = _chunks(text, 200)
        self.assertTrue(all(len(c) <= 200 for c in chunks))
        # every paragraph survives somewhere in the chunks
        self.assertIn("0" * 100, "".join(chunks))


class GetLlmRoutingTests(TestCase):
    @override_settings(SCORER_LLM_PROVIDER="", LLM_PROVIDER="mock")
    def test_none_without_real_provider(self):
        from apps.core.llm import get_llm
        self.assertIsNone(get_llm())

    @override_settings(LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="k")
    def test_ollama_provider_overrides_llm_provider(self):
        from apps.core.llm import get_llm, OllamaLLM
        # scoring can ask for ollama even while letters stay on anthropic
        self.assertIsInstance(get_llm(provider="ollama"), OllamaLLM)

    @override_settings(OLLAMA_MODEL="qwen2.5:14b", OLLAMA_BASE_URL="http://localhost:11434",
                       OLLAMA_TIMEOUT=120)
    def test_ollama_complete_json_parses_message(self):
        from apps.core.llm import OllamaLLM
        with patch("requests.post") as post:
            post.return_value.json.return_value = {"message": {"content": '{"score": 71}'}}
            post.return_value.raise_for_status.return_value = None
            out = OllamaLLM().complete_json("sys", "user", max_tokens=500)
        self.assertEqual(out["score"], 71)
        # asked Ollama for strict JSON and the configured model
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["format"], "json")
        self.assertEqual(body["model"], "qwen2.5:14b")


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
