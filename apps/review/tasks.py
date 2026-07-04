from __future__ import annotations

import asyncio
import logging

from celery import shared_task
from django.conf import settings

log = logging.getLogger(__name__)


@shared_task
def notify_new_drafts() -> dict:
    """Push a review card for each freshly-drafted job. No-op without a token."""
    if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID):
        log.warning("Telegram not configured (TELEGRAM_BOT_TOKEN/CHAT_ID) — skipping")
        return {"sent": 0, "skipped": True}

    from aiogram import Bot

    from .bot import push_drafts

    async def _run():
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        try:
            return await push_drafts(bot, settings.TELEGRAM_CHAT_ID)
        finally:
            await bot.session.close()

    return {"sent": asyncio.run(_run())}
