"""Turn a JobPosting into the display fields the feed template needs.

Mirrors the design prototype's deriveJob(): freshness label/colour, aging bar,
score colour, skill-tag highlighting, budget string, status -> UI state.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.scoring.profile import resolve_track, track_config

from .models import JobPosting


def _safe_url(u) -> str:
    """Only let http(s) URLs reach href/window.open — a javascript:/data: URL
    from external job data (API/email) would be an XSS sink otherwise."""
    u = (u or "").strip()
    return u if u.lower().startswith(("https://", "http://")) else ""

FRESH_WINDOW_MIN = 60
_UI_STATE = {
    JobPosting.Status.NEW: "new",
    JobPosting.Status.SCORED: "new",
    JobPosting.Status.DRAFTED: "new",
    JobPosting.Status.REVIEWED: "approved",
    JobPosting.Status.APPLIED: "sent",
    JobPosting.Status.SKIPPED: "skipped",
    JobPosting.Status.EXPIRED: "skipped",
}


def _age_minutes(job):
    if not job.posted_at:
        return None
    return int((timezone.now() - job.posted_at).total_seconds() // 60)


def _age_parts(m):
    if m is None:
        return "—", _("время неизвестно")
    if m < 60:
        return f"{m}м", _("%(m)s мин назад") % {"m": m}
    h, mm = divmod(m, 60)
    return f"{h}ч" + (f" {mm}м" if mm else ""), _("%(h)s ч %(mm)s мин назад") % {"h": h, "mm": mm}


def _fresh_meta(m):
    if m is None:
        return "—", "#737373", "rgba(115,115,115,0.16)"
    if m <= 15:
        return _("Свежая"), "#b6d086", "rgba(182,208,134,0.14)"
    if m <= 45:
        return _("Стареет"), "#f59e0b", "rgba(245,158,11,0.14)"
    return _("Устарела"), "#737373", "rgba(115,115,115,0.16)"


def _score_meta(s):
    if s is None:
        return "#8a8a8a", "rgba(138,138,138,0.1)", "rgba(138,138,138,0.28)"
    if s > 75:
        return "#4ade80", "rgba(74,222,128,0.1)", "rgba(74,222,128,0.3)"
    if s >= 50:
        return "#facc15", "rgba(250,204,21,0.1)", "rgba(250,204,21,0.3)"
    return "#8a8a8a", "rgba(138,138,138,0.1)", "rgba(138,138,138,0.28)"


def _hire_color(h):
    h = h or 0
    return "#4ade80" if h >= 70 else "#f59e0b" if h >= 40 else "#f87171"


def _budget(job):
    def fmt(v):
        v = Decimal(v)
        return f"{v:,.0f}" if v == v.to_integral() else f"{v:,.2f}"

    if job.budget_type == JobPosting.BudgetType.HOURLY:
        if job.budget_min is not None and job.budget_max is not None:
            return f"${fmt(job.budget_min)}–{fmt(job.budget_max)}/hr"
        if job.budget_min is not None:
            return f"${fmt(job.budget_min)}/hr"
        return _("почасовая")
    if job.budget_min is not None:
        return f"${fmt(job.budget_min)} fixed"
    return _("фикс")


def job_card(job, *, my_skills_lc=None):
    if my_skills_lc is None:
        # Highlight against the job's own track skills (dev job -> dev stack).
        my_skills_lc = {s.lower() for s in track_config(resolve_track(job))["skills"]}
    m = _age_minutes(job)
    age_big, posted_text = _age_parts(m)
    fresh_label, fresh_color, fresh_soft = _fresh_meta(m)
    score_obj = getattr(job, "score", None)
    score = score_obj.score if score_obj else None
    score_color, score_soft, score_border = _score_meta(score)
    state = _UI_STATE[JobPosting.Status(job.status)]
    bar_pct = 0 if m is None else max(2, min(100, round((1 - m / FRESH_WINDOW_MIN) * 100)))
    # No proposal count from Vibeworker; required connects is the competition
    # proxy (Upwork raises the apply price on contested postings).
    connects = (job.raw or {}).get("connects")
    try:
        connects = int(connects) if connects is not None else None
    except (TypeError, ValueError):
        connects = None
    overheated = connects is not None and connects >= settings.HOT_CONNECTS_THRESHOLD
    f = job.matched_filter
    search_kw_lc = {k.lower() for k in ((f.keywords if f else []) or [])}
    client = job.client
    return {
        "id": job.pk,
        "job_id": job.job_id,
        "title": job.title,
        "age_big": age_big,
        "posted_text": posted_text,
        "age_min": m if m is not None else 10**9,  # sort key: unknown sinks
        "fresh_label": fresh_label,
        "fresh_color": fresh_color,
        "fresh_soft": fresh_soft,
        "bar_pct": bar_pct,
        "score": score,
        "score_display": score if score is not None else "—",
        # status=new with no JobScore yet -> Haiku hasn't reached it. Drives the
        # "оценка…" spinner so an unscored card doesn't read as "scored badly".
        "scoring": score is None and state == "new",
        "score_color": score_color,
        "score_soft": score_soft,
        "score_border": score_border,
        "tags": [
            {"label": t, "mine": t.lower() in my_skills_lc, "in_search": t.lower() in search_kw_lc}
            for t in job.skills
        ],
        "budget": _budget(job),
        "verified": bool(client and client.verified_payment),
        "hire_rate": client.hire_rate if client else None,
        "hire_color": _hire_color(client.hire_rate if client else 0),
        "proposals": job.proposals_bucket,
        "connects": connects,
        "overheated": overheated,
        "state": state,
        "card_border": "rgba(74,222,128,0.4)" if state == "approved"
        else "rgba(182,208,134,0.4)" if state == "sent" else "#404040",
        "card_opacity": "0.42" if state == "skipped" else "1",
    }


_RU_MONTHS = ["", "января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря"]

_RISK_META = {
    "low": (_("Низкий риск"), "#4ade80", "rgba(74,222,128,0.08)", "circle-check"),
    "med": (_("Средний риск"), "#f59e0b", "rgba(245,158,11,0.08)", "alert-triangle"),
    "high": (_("Высокий риск"), "#f87171", "rgba(248,113,113,0.08)", "alert-triangle"),
}

_STATUS_TRACKER = {
    JobPosting.Status.NEW: (_("Новая — на ревью"), "#a3a3a3", _("Ещё не оценена.")),
    JobPosting.Status.SCORED: (_("Оценена — на ревью"), "#a3a3a3", _("Просмотри и одобри или пропусти.")),
    JobPosting.Status.DRAFTED: (_("Черновик готов"), "#facc15", _("Письмо сгенерировано, ждёт одобрения.")),
    JobPosting.Status.REVIEWED: (_("Одобрено"), "#4ade80", _("В очереди на ручную отправку. Открой на Upwork и отправь.")),
    JobPosting.Status.APPLIED: (_("Отправлено вручную"), "#b6d086", _("Отмечено как отправленное. Жди ответа клиента.")),
    JobPosting.Status.SKIPPED: (_("Пропущено"), "#737373", _("Исключена из ленты. Можно вернуть.")),
    JobPosting.Status.EXPIRED: (_("Устарела"), "#737373", _("Публикация устарела.")),
}


def _fmt_spent(v):
    if v is None:
        return "—"
    v = Decimal(v)
    if v >= 1000:
        k = f"{v / 1000:.1f}".rstrip("0").rstrip(".")  # 210000->"210", 6200->"6.2"
        return f"${k}K+"
    return f"${int(v)}"


def _ru_member_since(d):
    return f"{_RU_MONTHS[d.month]} {d.year}" if d else "—"


def job_detail(job, lang="ru"):
    """Display fields for the Detail screen. `lang` ("ru"/"en") picks the content
    language for title, description and the scoring reasons (originals are EN;
    RU are the cached translations)."""
    ru = lang == "ru"
    card = job_card(job)
    title = (job.title_ru or job.title) if ru else job.title
    description = (job.description_ru or job.description) if ru else job.description
    score_obj = getattr(job, "score", None)
    bd = []
    if score_obj:
        bd = score_obj.breakdown_ru if (ru and score_obj.breakdown_ru) else score_obj.breakdown
    reasons = []
    for r in bd:
        neg = r.get("neg", False)
        reasons.append({
            "text": r["text"],
            "w": ("−" if neg else "+") + str(r["w"]),
            "neg": neg,
        })
    client = job.client
    risk = _RISK_META[client.risk_level] if client else _RISK_META["high"]
    tracker = _STATUS_TRACKER[JobPosting.Status(job.status)]
    return {
        **card,
        "title": title,
        "description": description,
        "content_lang": lang,
        "reasons": reasons,
        "upwork_url": _safe_url((job.raw or {}).get("url", "")),
        "model_name": score_obj.model_name if score_obj else "—",
        "status_label": tracker[0],
        "status_color": tracker[1],
        "status_hint": tracker[2],
        "is_sent": job.status == JobPosting.Status.APPLIED,
        "client_card": None if not client else {
            "risk_label": risk[0], "risk_color": risk[1], "risk_bg": risk[2], "risk_icon": risk[3],
            "verified": client.verified_payment,
            "pay_text": _("Подтверждена") if client.verified_payment else _("Не подтверждена"),
            "pay_color": "#4ade80" if client.verified_payment else "#f87171",
            "spent": _fmt_spent(client.total_spent),
            "hire_rate": client.hire_rate or 0,
            "hire_color": _hire_color(client.hire_rate),
            "country": client.country or "—",
            "rating_text": f"{client.avg_rating} ★" if client.avg_rating else _("нет отзывов"),
            "jobs": client.total_jobs if client.total_jobs is not None else "—",
            "hires": client.total_hires if client.total_hires is not None else "—",
            "member_since": _ru_member_since(client.member_since),
        },
    }
