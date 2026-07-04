import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run the Telegram review bot (long-polling). No-op without a token."

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            self.stdout.write(self.style.WARNING(
                "TELEGRAM_BOT_TOKEN not set — nothing to run. "
                "Set it in .env to enable the review bot."
            ))
            return
        from apps.review.bot import run_polling

        self.stdout.write("Telegram bot polling. Ctrl-C to stop.")
        asyncio.run(run_polling())
