from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.jobs.models import ClientProfile, JobPosting
from apps.jobs.providers.mock import MockProvider
from apps.jobs.tasks import collect_for_filter

from .scorer import score_job

PROFILE = {
    "min_hourly_rate": 40,
    "skills": ["Django", "DRF", "Python", "Celery", "MQL5", "MetaTrader 5", "WebRTC"],
    "red_flag_phrases": ["should be quick"],
}


class ScorerTests(TestCase):
    def _job(self, **kw):
        defaults = dict(job_id="s1", title="t", budget_type="hourly", skills=[])
        defaults.update(kw)
        return JobPosting.objects.create(**defaults)

    @override_settings(JOB_SCORER="llm", ANTHROPIC_SCORER_MODEL="claude-haiku-4-5-20251001")
    def test_llm_scoring_uses_the_cheaper_scorer_model(self):
        with patch("apps.scoring.scorer.get_llm") as gl, \
             patch("apps.scoring.scorer.llm_compute") as lc:
            gl.return_value = object()  # truthy -> take the LLM path
            lc.return_value = {"score": 60, "breakdown": [], "reasoning": "ok"}
            score_job(self._job(skills=["Django"]))
        gl.assert_called_once_with("claude-haiku-4-5-20251001")

    @override_settings(JOB_SCORER="llm")
    def test_llm_json_error_falls_back_to_rule_scorer(self):
        # A malformed-JSON response (seen ~1.6% of the time) must not crash or
        # stall the job — degrade to the rule scorer instead.
        with patch("apps.scoring.scorer.get_llm") as gl, \
             patch("apps.scoring.scorer.llm_compute", side_effect=ValueError("bad json")):
            gl.return_value = object()
            job = self._job(skills=["Django"], budget_min=50)
            s = score_job(job)
        self.assertEqual(s.model_name, "rule-fallback")
        job.refresh_from_db()
        self.assertEqual(job.status, JobPosting.Status.SCORED)  # still advanced, not stuck

    def test_strong_match_scores_high_and_transitions(self):
        c = ClientProfile.objects.create(
            upwork_client_id="c1", verified_payment=True, hire_rate=82, total_spent=210000
        )
        job = self._job(skills=["Django", "DRF", "Celery"], budget_min=50, client=c)
        s = score_job(job, profile=PROFILE)
        self.assertGreater(s.score, 75)
        job.refresh_from_db()
        self.assertEqual(job.status, JobPosting.Status.SCORED)

    def test_unknown_hire_rate_is_not_penalized(self):
        # gmail alerts carry no hire rate: None must be neutral, not "0%"
        c = ClientProfile.objects.create(upwork_client_id="c-none", verified_payment=True)
        job = self._job(job_id="s-none", skills=["Django"], budget_min=50, client=c)
        s = score_job(job, profile=PROFILE)
        self.assertFalse([r for r in s.breakdown if "hire rate" in r["text"].lower()])

    def test_bad_match_scores_low(self):
        c = ClientProfile.objects.create(
            upwork_client_id="c2", verified_payment=False, hire_rate=20, total_spent=0
        )
        job = self._job(
            job_id="s2", skills=["WordPress", "PHP"], budget_min=15,
            description="Should be quick for the right person.", client=c,
        )
        s = score_job(job, profile=PROFILE)
        self.assertLess(s.score, 40)
        self.assertTrue(any(r["neg"] for r in s.breakdown))

    def test_scores_all_mock_jobs(self):
        from apps.jobs.models import SavedFilter

        f = SavedFilter.objects.create(name="all", keywords=[])
        collect_for_filter(f, provider=MockProvider())
        for job in JobPosting.objects.select_related("client"):
            s = score_job(job, profile=PROFILE)
            self.assertTrue(0 <= s.score <= 100)
            self.assertTrue(s.embedding and s.similarity is not None)


class EmbeddingTests(TestCase):
    def test_deterministic(self):
        from .embeddings.mock import MockEmbedding

        e = MockEmbedding()
        self.assertEqual(e.embed_one("django celery"), e.embed_one("django celery"))

    def test_related_is_more_similar_than_unrelated(self):
        from .embeddings import cosine
        from .embeddings.mock import MockEmbedding

        e = MockEmbedding()
        prof = e.embed_one("django drf python postgresql celery fastapi")
        good = e.embed_one("Senior Django DRF PostgreSQL Celery REST API developer")
        bad = e.embed_one("wordpress php css theme responsive menu")
        self.assertGreater(cosine(prof, good), cosine(prof, bad))


class LLMScorerTests(TestCase):
    def test_parses_and_clamps(self):
        from .llm_scorer import llm_compute

        class Fake:
            def complete_json(self, system, user, max_tokens=0):
                return {"score": 140, "reasoning": "r", "breakdown": [{"text": "x", "w": 10, "neg": False}]}

        job = JobPosting(job_id="l1", title="t", budget_type="fixed", skills=[])
        r = llm_compute(job, {"skills": []}, 0.5, Fake())
        self.assertEqual(r["score"], 100)  # clamped to 0-100
        self.assertEqual(r["breakdown"][0]["text"], "x")
