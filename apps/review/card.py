"""Pure card assembly — no aiogram import, so it's unit-testable without the
bot library or a token. bot.py turns keyboard_spec() into aiogram markup."""
from __future__ import annotations

from django.conf import settings

from apps.jobs.models import JobPosting
from apps.jobs.presenters import _budget

_RISK_RU = {"low": "низкий риск", "med": "средний риск", "high": "высокий риск"}


def card_text(job: JobPosting) -> str:
    score = getattr(job, "score", None)
    cover = job.cover_drafts.filter(is_active=True).first()
    n_q = job.screening_questions.count()
    c = job.client
    lines = [
        f"🆕 {job.title}",
        f"⭐ Score {score.score if score else '—'}/100 · 💵 {_budget(job)}",
    ]
    if c:
        lines.append(f"👤 {_RISK_RU.get(c.risk_level, '?')} · {c.country or '—'} · hire {c.hire_rate or 0}%")
    if score and score.reasoning:
        lines.append(f"\n{score.reasoning}")
    lines.append(
        f"\n📝 Черновик: {'готов' if cover else 'нет'} · вопросов: {n_q}"
    )
    lines.append(f"🔗 {settings.SITE_URL}/job/{job.pk}/")
    return "\n".join(lines)


def keyboard_spec(pk: int) -> list[list[dict]]:
    """Rows of buttons. cb = callback_data; url = link button."""
    return [
        [{"text": "✅ Одобрить", "cb": f"approve:{pk}"},
         {"text": "✂️ Пропустить", "cb": f"skip:{pk}"}],
        [{"text": "✏️ Редактировать", "url": f"{settings.SITE_URL}/job/{pk}/?edit=1"}],
    ]
