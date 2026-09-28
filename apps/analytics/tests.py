from django.test import TestCase

from apps.jobs.models import JobPosting

from . import metrics


class MetricsTests(TestCase):
    def setUp(self):
        for i, status in enumerate([JobPosting.Status.NEW, JobPosting.Status.APPLIED, JobPosting.Status.REVIEWED]):
            JobPosting.objects.create(
                job_id=f"m{i}", title="t", budget_type="fixed",
                skills=["Django", "Python"], status=status,
            )

    def test_funnel_found_counts_all(self):
        f = metrics.funnel()
        self.assertEqual(str(f[0]["label"]), "Найдено")
        self.assertEqual(f[0]["count"], 3)
        # funnel_counts now keys by stable slug (language-independent), not label
        self.assertEqual(dict(metrics.funnel_counts())["applied"], 1)

    def test_keywords_and_prometheus(self):
        kws = {k["kw"]: k for k in metrics.keywords()}
        self.assertEqual(kws["Django"]["n"], 3)
        self.assertIn('upwork_funnel{stage="found"} 3', metrics.prometheus_text())

    def test_endpoints_render(self):
        self.assertEqual(self.client.get("/analytics/").status_code, 200)
        r = self.client.get("/metrics/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/plain", r["Content-Type"])


class HabitTests(TestCase):
    def _sent(self, jid, when):
        from apps.jobs.models import JobPosting
        return JobPosting.objects.create(job_id=jid, title="t", budget_type="fixed",
                                         status=JobPosting.Status.APPLIED, applied_at=when)

    def test_streak_goal_calendar_and_trophies(self):
        from datetime import datetime, time, timedelta

        from django.utils import timezone

        from .habit import habit

        today = timezone.localdate()
        at = lambda d: timezone.make_aware(datetime.combine(d, time(12)))
        for i, d in enumerate([today - timedelta(days=2), today - timedelta(days=1)]):
            self._sent(f"a{i}", at(d))
        for i in range(3):  # goal met today
            self._sent(f"t{i}", at(today))
        self._sent("old", at(today - timedelta(days=10)))  # separate, older run

        h = habit(goal=3)
        self.assertEqual((h["today"], h["today_left"], h["streak"], h["best"], h["total"]), (3, 0, 3, 3, 6))
        cell = next(c for w in h["weeks"] for c in w if c["today"])
        self.assertEqual((cell["n"], cell["level"]), (3, 3))
        got = {t["key"] for t in h["trophies"] if t["unlocked"]}
        self.assertTrue({"first", "goal", "s3"} <= got)
        self.assertNotIn("t10", got)

    def test_empty_today_keeps_yesterdays_streak(self):
        from datetime import datetime, time, timedelta

        from django.utils import timezone

        from .habit import habit

        y = timezone.localdate() - timedelta(days=1)
        self._sent("y", timezone.make_aware(datetime.combine(y, time(12))))
        self.assertEqual(habit()["streak"], 1)  # the day isn't over yet

    def test_undo_clears_applied_at(self):
        from apps.jobs.models import JobPosting
        j = JobPosting.objects.create(job_id="u", title="t", budget_type="fixed", status=JobPosting.Status.DRAFTED)
        j.transition_to(JobPosting.Status.APPLIED)
        self.assertIsNotNone(j.applied_at)
        j.transition_to(JobPosting.Status.DRAFTED)
        self.assertIsNone(JobPosting.objects.get(pk=j.pk).applied_at)


class MoneyTests(TestCase):
    def test_totals_balance_and_costs(self):
        from decimal import Decimal

        from django.utils import timezone

        from .models import MoneyEntry
        from .money import money

        MoneyEntry.objects.create(kind="connects", usd=0, connects=104, note="start")
        MoneyEntry.objects.create(kind="connects", usd=Decimal("12.00"), connects=80)
        MoneyEntry.objects.create(kind="subscription", usd=Decimal("20.00"))
        MoneyEntry.objects.create(kind="income", usd=Decimal("90.00"))
        now = timezone.now()
        JobPosting.objects.create(job_id="a", title="t", budget_type="fixed", status="applied",
                                  applied_at=now, connects_spent=90, interviewed_at=now)
        JobPosting.objects.create(job_id="b", title="t", budget_type="fixed", status="applied",
                                  applied_at=now, connects_spent=20)
        m = money()
        self.assertEqual((m["spent"], m["income"], m["net"]), (Decimal("32.00"), Decimal("90.00"), Decimal("58.00")))
        self.assertEqual((m["bought"], m["used"], m["balance"]), (184, 110, 74))
        self.assertEqual(m["price"], Decimal("0.15"))  # $12 / 80 paid connects; the $0 start line is ignored
        self.assertEqual(m["per_proposal"], Decimal("8.25"))  # 55 connects avg x $0.15
        self.assertEqual(m["per_interview"], Decimal("32.00"))
        self.assertIsNone(m["per_hire"])

    def test_bad_input_is_rejected(self):
        from .models import MoneyEntry
        self.client.post("/analytics/money/", {"kind": "income", "usd": "-5"})
        self.client.post("/analytics/money/", {"kind": "nope", "usd": "5"})
        self.assertEqual(MoneyEntry.objects.count(), 0)
        self.client.post("/analytics/money/", {"kind": "income", "usd": "12.5"})
        self.assertEqual(MoneyEntry.objects.get().usd, 12.5)
