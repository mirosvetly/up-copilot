from decimal import Decimal

from django.test import TestCase

from apps.jobs.models import JobPosting, SavedFilter
from apps.letters.generator import generate_cover
from apps.scoring.profile import resolve_track, track_config
from apps.scoring.scorer import score_job

from .models import Track


class MigrationSeedTests(TestCase):
    def test_default_track_seeded_from_yaml(self):
        # The data migration seeds one default track before any test runs.
        t = Track.get_default()
        self.assertIsNotNone(t)
        self.assertTrue(t.is_default)
        self.assertIn("Django", t.skills)


class ResolveTrackTests(TestCase):
    def setUp(self):
        self.dev = Track.objects.create(name="Dev", is_default=True, skills=["Django"])
        self.land = Track.objects.create(
            name="Landing", skills=["Webflow", "Framer"], min_hourly_rate=30,
            red_flag_phrases=["logo only"], signoff="Cheers,\nMax",
        )

    def _job(self, track):
        f = SavedFilter.objects.create(name=f"f-{track.name if track else 'none'}", track=track)
        return JobPosting.objects.create(
            job_id=f"j-{track.pk if track else 0}", title="t", budget_type="fixed",
            matched_filter=f,
        )

    def test_job_inherits_track_from_filter(self):
        job = self._job(self.land)
        self.assertEqual(resolve_track(job), self.land)

    def test_job_without_filter_falls_back_to_default(self):
        job = JobPosting.objects.create(job_id="nf", title="t", budget_type="fixed")
        self.assertEqual(resolve_track(job), self.dev)

    def test_filter_without_track_falls_back_to_default(self):
        job = self._job(None)
        self.assertEqual(resolve_track(job), self.dev)

    def test_track_config_shape(self):
        cfg = track_config(self.land)
        self.assertEqual(cfg["skills"], ["Webflow", "Framer"])
        self.assertEqual(cfg["min_hourly_rate"], 30)
        self.assertEqual(cfg["signoff"], "Cheers,\nMax")
        self.assertEqual(cfg["track_id"], self.land.pk)

    def test_none_track_config_is_safe(self):
        cfg = track_config(None)  # fresh DB, no tracks
        self.assertEqual(cfg["skills"], [])
        self.assertIn("signoff", cfg)


class PerTrackProcessingTests(TestCase):
    def setUp(self):
        self.dev = Track.objects.create(
            name="Dev", is_default=True, skills=["Django", "Celery"], min_hourly_rate=40,
        )
        self.land = Track.objects.create(
            name="Landing", skills=["Webflow", "Framer"], min_hourly_rate=25,
            projects=[{"repo": "landing-kit", "skills": ["Webflow", "Framer"]}],
            signoff="Cheers,\nMax",
        )

    def _job(self, track, skills):
        f = SavedFilter.objects.create(name=f"f-{track.name}", track=track)
        return JobPosting.objects.create(
            job_id=f"j-{track.name}", title="Build a site", budget_type="hourly",
            budget_min=Decimal("50"), skills=skills, matched_filter=f,
        )

    def test_same_job_scores_differently_per_track(self):
        # A Webflow job matches the landing track's stack, not the dev track's.
        dev_job = self._job(self.dev, ["Webflow", "Framer"])
        land_job = self._job(self.land, ["Webflow", "Framer"])
        dev_score = score_job(dev_job).score
        land_score = score_job(land_job).score
        self.assertGreater(land_score, dev_score)  # stack match only on landing track

    def test_screening_uses_track_instructions(self):
        from apps.screening.generator import _system

        self.land.screening_instructions = "Answer as a landing-page specialist."
        self.land.save(update_fields=["screening_instructions"])
        job = self._job(self.land, ["Webflow"])
        self.assertEqual(_system(job), "Answer as a landing-page specialist.")

    def test_letter_uses_track_signoff_and_projects(self):
        job = self._job(self.land, ["Webflow"])
        job.status = JobPosting.Status.SCORED
        job.save(update_fields=["status"])
        draft = generate_cover(job)
        self.assertIn("Cheers,", draft.body)  # landing signoff
        self.assertIn("landing-kit", draft.sources)  # landing portfolio


class SingleDefaultTests(TestCase):
    def test_saving_second_default_clears_the_first_everywhere(self):
        # Root-cause guard lives in Track.save, so even the admin path is safe.
        a = Track.objects.create(name="Aaa", is_default=True)
        b = Track.objects.create(name="Zzz", is_default=True)  # via plain .create, not the form
        a.refresh_from_db()
        self.assertFalse(a.is_default)
        self.assertEqual(Track.objects.filter(is_default=True).count(), 1)
        self.assertEqual(Track.get_default(), b)  # the one just marked, not name-first


class EmbeddingCacheTests(TestCase):
    def test_editing_projects_refreshes_profile_vector(self):
        from apps.scoring.embeddings import get_embedding_provider
        from apps.scoring.profile import track_config
        from apps.scoring.scorer import _profile_embedding

        t = Track.objects.create(name="T", skills=["Python"], projects=[{"repo": "a", "skills": ["Python"]}])
        provider = get_embedding_provider()
        v1 = _profile_embedding(provider, track_config(t))
        t.projects = [{"repo": "b", "skills": ["Rust"]}]
        t.save(update_fields=["projects"])
        v2 = _profile_embedding(provider, track_config(t))
        self.assertNotEqual(v1, v2)  # projects change -> fresh vector, not the cached one


class EmptyPortfolioLetterTests(TestCase):
    def test_cover_letter_generates_without_projects(self):
        from apps.jobs.models import JobPosting, SavedFilter
        from apps.letters.generator import generate_cover

        t = Track.objects.create(name="Landing", projects=[], signoff="Cheers,\nMax")
        f = SavedFilter.objects.create(name="lf", track=t)
        job = JobPosting.objects.create(
            job_id="np", title="Build a landing page", budget_type="fixed",
            skills=["Webflow"], status=JobPosting.Status.SCORED, matched_filter=f,
        )
        draft = generate_cover(job)  # must not IndexError
        self.assertIn("Cheers,", draft.body)
        self.assertEqual(draft.sources, [])


class SettingsPageTests(TestCase):
    def setUp(self):
        self.track = Track.objects.create(name="Dev", is_default=True, skills=["Django"])

    def test_list_and_edit_pages_render(self):
        self.assertEqual(self.client.get("/settings/tracks/").status_code, 200)
        self.assertEqual(self.client.get(f"/settings/tracks/{self.track.pk}/").status_code, 200)
        self.assertEqual(self.client.get("/settings/tracks/new/").status_code, 200)

    def test_create_track_parses_lines_and_json(self):
        r = self.client.post("/settings/tracks/new/", {
            "name": "Landing", "scorer_role": "landing dev", "signoff": "Cheers,\nMax",
            "skills": "Webflow\nFramer\n", "min_hourly_rate": "25",
            "projects": '[{"repo": "landing-kit", "skills": ["Webflow"]}]',
            "red_flag_phrases": "logo only\n",
            "job_analysis_prompt": "", "cover_letter_instructions": "",
            "screening_instructions": "",
        })
        self.assertEqual(r.status_code, 302)
        t = Track.objects.get(name="Landing")
        self.assertEqual(t.skills, ["Webflow", "Framer"])
        self.assertEqual(t.projects, [{"repo": "landing-kit", "skills": ["Webflow"]}])
        self.assertEqual(t.red_flag_phrases, ["logo only"])

    def test_projects_with_non_list_skills_rejected(self):
        r = self.client.post("/settings/tracks/new/", {
            "name": "BadSkills", "scorer_role": "x", "signoff": "x",
            "skills": "", "min_hourly_rate": "0",
            "projects": '[{"repo": "demo", "skills": null}]',
            "red_flag_phrases": "", "job_analysis_prompt": "",
            "cover_letter_instructions": "", "screening_instructions": "",
        })
        self.assertEqual(r.status_code, 200)  # form error, not a later crash
        self.assertFalse(Track.objects.filter(name="BadSkills").exists())

    def test_invalid_projects_json_is_rejected(self):
        r = self.client.post("/settings/tracks/new/", {
            "name": "Broken", "scorer_role": "x", "signoff": "x",
            "skills": "", "min_hourly_rate": "0", "projects": "{not json",
            "red_flag_phrases": "", "job_analysis_prompt": "",
            "cover_letter_instructions": "", "screening_instructions": "",
        })
        self.assertEqual(r.status_code, 200)  # re-render with error, no 500
        self.assertFalse(Track.objects.filter(name="Broken").exists())

    def test_marking_default_clears_other_defaults(self):
        other = Track.objects.create(name="Landing")
        self.client.post(f"/settings/tracks/{other.pk}/", {
            "name": "Landing", "is_default": "on", "scorer_role": "x", "signoff": "x",
            "skills": "", "min_hourly_rate": "0", "projects": "[]",
            "red_flag_phrases": "", "job_analysis_prompt": "",
            "cover_letter_instructions": "", "screening_instructions": "",
        })
        self.track.refresh_from_db()
        other.refresh_from_db()
        self.assertTrue(other.is_default)
        self.assertFalse(self.track.is_default)  # old default cleared
