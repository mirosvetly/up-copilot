from django.core.management.base import BaseCommand

from apps.screening.models import KnowledgeBase

ENTRIES = [
    ("experience", ["django", "drf", "rest", "framework", "years", "experience"],
     "6 years with Django REST Framework — 4 production DRF APIs, the most recent handling ~2M requests/day with token auth, throttling and Celery-backed async tasks."),
    ("integrations", ["integrated", "trading", "market", "data", "api", "brokerage", "alpaca", "metatrader", "feeds"],
     "Yes — Alpaca and two brokerage/market-data feeds, including MetaTrader 5 bridges. I handle idempotency, webhook verification and reconciliation."),
    ("availability", ["availability", "weekly", "hours", "timezone", "overlap", "available"],
     "30–35 hrs/week, with 4+ hours overlapping US Eastern for standups and pairing. My timezone is ICT (UTC+7)."),
    ("samples", ["mt5", "mql5", "code", "samples", "share", "expert", "advisor"],
     "Yes — I can share a private repo with two MT5 Expert Advisors and a backtest report on a call."),
    ("backtesting", ["backtest", "tick", "data", "provided", "testing"],
     "Yes. I'll run in-sample and out-of-sample tests on your tick data and share the report plus the exact settings used."),
    ("webrtc", ["webrtc", "production", "shipped", "video", "signaling"],
     "Yes, two apps — one 1:1 telehealth-style, one small-group. Both with a signaling server and TURN fallback."),
    ("compliance", ["hipaa", "compliance", "phi", "requirements", "familiar"],
     "I follow HIPAA-aware practices — no PHI in logs, encrypted transport and at-rest. Not a compliance officer, but I can work to your BAA."),
    ("start", ["start", "today", "begin", "when"],
     "I can take a look this week and give you a quick scope."),
    ("rate", ["rate", "budget", "hourly", "cost", "price"],
     "My rate is $40+/hr depending on scope; open to a fixed price for well-defined deliverables."),
]


class Command(BaseCommand):
    help = "Seed the KnowledgeBase with Denis's screening facts (idempotent)."

    def handle(self, *args, **options):
        made = 0
        for category, keywords, content in ENTRIES:
            _, created = KnowledgeBase.objects.get_or_create(
                content=content, defaults={"category": category, "keywords": keywords}
            )
            made += int(created)
        self.stdout.write(self.style.SUCCESS(f"KnowledgeBase entries created: {made}"))
