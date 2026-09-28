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
    """HTML (sent with parse_mode=HTML): every dynamic string is escaped."""
    from html import escape

    score = getattr(job, "score", None)
    c = job.client
    lines = _head(job)
    extra = (["✅ оплата подтверждена"] if c and c.verified_payment else []) + (
        [f"нанимает {c.hire_rate}%"] if c and c.hire_rate is not None else [])
    if extra:
        lines.append(" · ".join(extra))
    lines += ["", f"<b>{escape(job.title)}</b>"]
    if score and score.reasoning:
        lines.append("")
        lines.append(escape(score.reasoning))
    lines.append("")
    lines.append("Открой карточку, сгенерь письмо и отправь, пока не перебили.")
    return "\n".join(lines)


def _age(job: JobPosting) -> str:
    """How long ago the job was posted: fresh ones still have an empty boost top-4."""
    if not job.posted_at:
        return ""
    m = int((timezone.now() - job.posted_at).total_seconds() // 60)
    return f"⏱ {m} мин назад" if m < 120 else f"⏱ {m // 60} ч назад"


# ponytail: the client countries we actually see; anything else stays in English.
_COUNTRY_RU = {
    "United States": "США", "USA": "США", "United Kingdom": "Великобритания", "Canada": "Канада",
    "Australia": "Австралия", "New Zealand": "Новая Зеландия", "Ireland": "Ирландия",
    "United Arab Emirates": "ОАЭ", "Saudi Arabia": "Саудовская Аравия", "Qatar": "Катар",
    "Kuwait": "Кувейт", "Israel": "Израиль", "Turkey": "Турция", "Singapore": "Сингапур",
    "India": "Индия", "Pakistan": "Пакистан", "Philippines": "Филиппины", "Indonesia": "Индонезия",
    "Malaysia": "Малайзия", "Japan": "Япония", "Hong Kong": "Гонконг", "China": "Китай",
    "Nigeria": "Нигерия", "Kenya": "Кения", "Egypt": "Египет", "South Africa": "ЮАР",
    "Germany": "Германия", "France": "Франция", "Italy": "Италия", "Spain": "Испания",
    "Portugal": "Португалия", "Netherlands": "Нидерланды", "Belgium": "Бельгия",
    "Switzerland": "Швейцария", "Austria": "Австрия", "Sweden": "Швеция", "Norway": "Норвегия",
    "Denmark": "Дания", "Finland": "Финляндия", "Poland": "Польша", "Ukraine": "Украина",
    "Georgia": "Грузия", "Montenegro": "Черногория", "Serbia": "Сербия", "Cyprus": "Кипр",
    "Brazil": "Бразилия", "Mexico": "Мексика", "Argentina": "Аргентина",
}


def _points(n: int) -> str:
    """62 балла, 55 баллов, 21 балл."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} балл"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} балла"
    return f"{n} баллов"


def _head(job: JobPosting) -> list[str]:
    """Top lines of every ping, in the order you decide by: price, score, country, age."""
    from html import escape

    score = getattr(job, "score", None)
    c = job.client
    country = c.country if c and c.country else ""
    lines = [f"💵 {escape(_budget(job))}", f"🎯 {_points(score.score) if score else '—'}"]
    if country:
        lines.append(f"🌍 {escape(_COUNTRY_RU.get(country, country))}")
    if _age(job):
        lines.append(_age(job))
    return lines


def _card_url(job: JobPosting) -> str:
    # Telegram rejects "localhost" in link and button URLs but accepts an IP, so
    # swap it for 127.0.0.1: same server, and the button opens on this Mac.
    return f"{settings.SITE_URL.replace('://localhost', '://127.0.0.1')}/job/{job.pk}/"


def _buttons(job: JobPosting) -> list[list[dict]] | None:
    row = [{"text": "📄 Карточка", "url": _card_url(job)}]
    upwork = _safe_url((job.raw or {}).get("url", ""))
    if upwork:
        row.append({"text": "🔗 Открыть на Upwork", "url": upwork})
    return [row]


def send_telegram(text: str, buttons: list | None = None, *, chat_id: str = "", html: bool = False) -> bool:
    if not _configured():
        return False
    import requests  # lazy: only on the real path

    payload = {
        "chat_id": chat_id or settings.TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if html:
        payload["parse_mode"] = "HTML"
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
        .select_related("client", "score", "matched_filter__track")
        .order_by("-score__score")
    )
    sent = 0
    for job in jobs:
        track = job.matched_filter.track if job.matched_filter else None
        if send_telegram(_text(job), _buttons(job), chat_id=track.telegram_chat_id if track else "", html=True):
            job.review_notified_at = timezone.now()
            job.save(update_fields=["review_notified_at", "updated_at"])
            sent += 1
    return {"sent": sent}


def _autopilot_text(job: JobPosting, letter: str) -> str:
    from html import escape

    return "\n".join([
        *_head(job),
        "",
        f"🤖 <b>{escape(job.title)}</b>",
        "",
        # <pre> gets a one-tap Copy button in Telegram clients.
        f"<pre>{escape(letter)}</pre>",
        *(["", "🐣 Есть 3 отзыва? Выключи режим новичка в настройках трека"]
          if job.matched_filter.track.newcomer_mode else []),
    ])


def notify_autopilot_jobs() -> dict:
    """For tracks in autopilot mode: draft the letter now and send it whole, ready to paste.

    Runs before notify_scored_jobs; a job whose draft fails stays SCORED, so the plain
    score ping picks it up as a fallback."""
    if not _configured():
        return {"sent": 0}
    from datetime import timedelta

    from apps.letters.generator import generate_cover
    from apps.tracks.models import Track

    cutoff = timezone.now() - timedelta(hours=settings.MAX_JOB_AGE_HOURS)
    jobs = (
        JobPosting.objects.filter(
            # DRAFTED too: a send that failed after drafting retries next run.
            status__in=[JobPosting.Status.SCORED, JobPosting.Status.DRAFTED],
            review_notified_at__isnull=True,
            score__score__gte=settings.AUTOPILOT_MIN_SCORE,
            posted_at__gte=cutoff,
            matched_filter__track__mode=Track.Mode.AUTOPILOT,
        )
        .select_related("client", "score", "matched_filter__track")
        .order_by("-score__score")
    )
    sent = 0
    for job in jobs:
        try:
            draft = job.cover_drafts.filter(is_active=True).first()
            if not (draft and draft.body.strip()):  # an empty draft (thinking ate the budget) gets redone
                draft = generate_cover(job)
            letter = draft.body
        except Exception:
            log.exception("Autopilot draft failed for job %s", job.pk)
            continue
        if not letter.strip():
            continue
        track = job.matched_filter.track
        if send_telegram(
            _autopilot_text(job, letter), _buttons(job), chat_id=track.telegram_chat_id, html=True
        ):
            job.review_notified_at = timezone.now()
            job.save(update_fields=["review_notified_at", "updated_at"])
            sent += 1
    return {"sent": sent}
