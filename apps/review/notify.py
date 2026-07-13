"""Telegram ping for freshly-scored, high-scoring jobs — the "get in fast" alert.

Synchronous (plain Bot API over requests), so it runs from a management command
or cron with no aiogram/Celery/event-loop. The inline buttons are URL links
(open the card, open on Upwork), which work without a running bot poller; the
Approve/Skip callback bot in bot.py is optional on top of this.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from apps.jobs.models import JobPosting
from apps.jobs.presenters import _budget, _safe_url

log = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/sendMessage"


def _configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


def _text(job: JobPosting) -> str:
    score = getattr(job, "score", None)
    c = job.client
    lines = [
        f"🎯 Новая под тебя — score {score.score if score else '—'}/100",
        "",
        job.title,
        f"💵 {_budget(job)}"
        + (" · ✅ оплата подтверждена" if c and c.verified_payment else "")
        + (f" · нанимает {c.hire_rate}%" if c and c.hire_rate is not None else ""),
    ]
    if score and score.reasoning:
        lines.append("")
        lines.append(score.reasoning)
    lines.append("")
    # Card link in the text (not a button) — Telegram rejects localhost in
    # inline-button URLs, but accepts it as plain text.
    lines.append(f"📄 Карточка: {settings.SITE_URL}/job/{job.pk}/")
    lines.append("Зайди, сгенерь письмо и отправь, пока не перебили.")
    return "\n".join(lines)


def _is_public_url(u: str) -> bool:
    return u.startswith("https://") or (
        u.startswith("http://") and "localhost" not in u and "127.0.0.1" not in u
    )


def _buttons(job: JobPosting) -> list[list[dict]] | None:
    row = []
    upwork = _safe_url((job.raw or {}).get("url", ""))
    if upwork:
        row.append({"text": "🔗 Открыть на Upwork", "url": upwork})
    # Telegram inline-button URLs must be public; skip the card button on localhost.
    if _is_public_url(settings.SITE_URL):
        row.append({"text": "📄 Карточка", "url": f"{settings.SITE_URL}/job/{job.pk}/"})
    return [row] if row else None


def send_telegram(text: str, buttons: list | None = None) -> bool:
    if not _configured():
        return False
    import requests  # lazy: only on the real path

    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        resp = requests.post(
            _API.format(token=settings.TELEGRAM_BOT_TOKEN), json=payload, timeout=15
        )
        if not resp.ok:
            log.warning("Telegram sendMessage %s: %s", resp.status_code, resp.text[:200])
        return resp.ok
    except Exception:
        log.exception("Telegram send failed")
        return False


def notify_scored_jobs() -> dict:
    """Ping every scored job at/above NOTIFY_MIN_SCORE that hasn't been pinged yet.
    Dedup is review_notified_at, so a job alerts once even across re-runs."""
    if not _configured():
        return {"sent": 0, "skipped": "telegram not configured"}
    # Only ping fresh postings — a job that scored well but sat unnotified past the
    # freshness window is already buried, no point racing to it.
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(hours=settings.MAX_JOB_AGE_HOURS)
    jobs = (
        JobPosting.objects.filter(
            status=JobPosting.Status.SCORED,
            review_notified_at__isnull=True,
            score__score__gte=settings.NOTIFY_MIN_SCORE,
            posted_at__gte=cutoff,
        )
        .select_related("client", "score")
        .order_by("-score__score")
    )
    sent = 0
    for job in jobs:
        if send_telegram(_text(job), _buttons(job)):
            job.review_notified_at = timezone.now()
            job.save(update_fields=["review_notified_at", "updated_at"])
            sent += 1
    return {"sent": sent}
