"""aiogram wiring. Imported lazily (only run_bot / notify need it) so the rest
of the app and its tests never require aiogram or a token."""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

from apps.jobs.models import JobPosting

from .card import card_text, keyboard_spec

log = logging.getLogger(__name__)


def _markup(spec):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [
        [
            InlineKeyboardButton(text=b["text"], callback_data=b["cb"]) if "cb" in b
            else InlineKeyboardButton(text=b["text"], url=b["url"])
            for b in row
        ]
        for row in spec
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@sync_to_async
def _transition(pk, target):
    JobPosting.objects.get(pk=pk).transition_to(target)


@sync_to_async
def _mark_sent(pk) -> bool:
    """True when this tap moved the job to "applied"; False if it already was (or is gone)."""
    job = JobPosting.objects.filter(pk=pk).first()
    if not job or job.status == JobPosting.Status.APPLIED:
        return False
    job.transition_to(JobPosting.Status.APPLIED)
    return True


def build_dispatcher():
    from aiogram import Dispatcher, F
    from aiogram.types import CallbackQuery

    dp = Dispatcher()

    @dp.callback_query(F.data.startswith("approve:"))
    async def approve(cb: "CallbackQuery"):
        await _transition(int(cb.data.split(":")[1]), JobPosting.Status.REVIEWED)
        await cb.answer("Одобрено — в очереди на отправку")

    @dp.callback_query(F.data.startswith("skip:"))
    async def skip(cb: "CallbackQuery"):
        await _transition(int(cb.data.split(":")[1]), JobPosting.Status.SKIPPED)
        await cb.answer("Пропущено")

    @dp.callback_query(F.data.startswith("sent:"))
    async def sent(cb: "CallbackQuery"):
        # Sent straight from Telegram to Upwork: one tap here counts it (streak, stats).
        try:
            fresh = await _mark_sent(int(cb.data.split(":")[1]))
        except ValueError:
            fresh = False
        await cb.answer("✅ Отмечено как отправлено" if fresh else "Уже отмечено")
        from aiogram.types import InlineKeyboardMarkup
        rows = [[b for b in row if not b.callback_data] for row in cb.message.reply_markup.inline_keyboard]
        await cb.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r]))

    return dp


@sync_to_async
def _pending_drafts():
    return list(
        JobPosting.objects.filter(
            status=JobPosting.Status.DRAFTED, review_notified_at__isnull=True
        ).select_related("client", "score")
    )


@sync_to_async
def _mark_notified(job):
    job.review_notified_at = timezone.now()
    job.save(update_fields=["review_notified_at", "updated_at"])


async def push_drafts(bot, chat_id):
    sent = 0
    for job in await _pending_drafts():
        text = await sync_to_async(card_text)(job)
        await bot.send_message(
            chat_id, text, reply_markup=_markup(keyboard_spec(job.pk)),
            disable_web_page_preview=True,
        )
        await _mark_notified(job)
        sent += 1
    return sent


async def run_polling():
    from aiogram import Bot

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    dp = build_dispatcher()
    log.info("Starting Telegram polling")
    await dp.start_polling(bot)
