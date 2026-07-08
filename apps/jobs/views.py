from __future__ import annotations

import logging

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .models import JobPosting
from .presenters import job_card, job_detail

log = logging.getLogger(__name__)


def _safe_next(request):
    nxt = request.POST.get("next", "")
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else reverse("jobs:feed")

# Feed action -> target status. transition_to() enforces legality.
_ACTIONS = {
    "approve": JobPosting.Status.REVIEWED,
    "skip": JobPosting.Status.SKIPPED,
    "undo": JobPosting.Status.SCORED,
    "mark_sent": JobPosting.Status.APPLIED,
    "unsend": JobPosting.Status.DRAFTED,  # revert an accidental "sent"
}


def feed(request, sent=False):
    from django.db.models import Count

    from apps.tracks.models import Track
    from apps.scoring.profile import track_config

    q = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "score")  # default: best-scored first
    track = request.GET.get("track", "all")
    applied = JobPosting.Status.APPLIED

    qs = (
        JobPosting.objects.exclude(status=JobPosting.Status.EXPIRED)
        .select_related("client", "score", "matched_filter__track")
    )
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(skills__icontains=q))
    # Sent jobs live in their own view; the review feed shows only unsent, so the
    # top is always the highest-scored job still waiting.
    qs = qs.filter(status=applied) if sent else qs.exclude(status=applied)

    # Direction pills (Все / <track> …) with live counts, computed before the
    # track filter is applied so each pill shows its full total.
    tracks = list(Track.objects.all())
    per_track = dict(
        qs.values_list("matched_filter__track_id").annotate(n=Count("id"))
    )
    track_pills = [{"key": "all", "label": _("Все"), "count": qs.count(), "active": track == "all"}]
    track_pills += [
        {"key": str(t.pk), "label": t.name, "count": per_track.get(t.pk, 0), "active": track == str(t.pk)}
        for t in tracks
    ]

    if track != "all":
        try:
            qs = qs.filter(matched_filter__track_id=int(track))
        except ValueError:
            track = "all"  # bad param -> show everything, don't 500

    # Each card highlights against its own track's skills. Resolve the default
    # once and memoize per track so the feed stays at O(1) track queries.
    default_track = Track.get_default()
    skills_by_track: dict = {}

    def skills_for(job):
        f = job.matched_filter
        t = (f.track if f else None) or default_track
        tid = t.id if t else None
        if tid not in skills_by_track:
            skills_by_track[tid] = {s.lower() for s in track_config(t)["skills"]}
        return skills_by_track[tid]

    cards = [job_card(j, my_skills_lc=skills_for(j)) for j in qs]

    def sort_key(c):
        skipped = c["state"] == "skipped"
        if sort == "score":
            return (skipped, -(c["score"] or -1), c["age_min"])  # score desc, fresh tiebreak
        return (skipped, c["age_min"])

    cards.sort(key=sort_key)

    counts = {"new": 0, "approved": 0, "sent": 0, "skipped": 0}
    for c in cards:
        counts[c["state"]] = counts.get(c["state"], 0) + 1
    queue = [c for c in cards if c["state"] == "approved"]

    return render(
        request,
        "jobs/feed.html",
        {
            "cards": cards,
            "visible_count": sum(1 for c in cards if c["state"] != "skipped"),
            "counts": counts,
            "queue": queue,
            "q": q,
            "sort": sort,
            "track": track,
            "track_pills": track_pills,
            "sent_view": sent,
            "is_feed": not sent,
            "is_sent": sent,
        },
    )


def _score_in_background():
    """Score pending jobs off the request thread — LLM calls are too slow to
    block on. Own DB connection, closed at the end; errors are swallowed."""
    import threading

    from django.db import connection

    def run():
        try:
            from apps.scoring.tasks import score_pending_jobs

            score_pending_jobs()
        except Exception:
            log.exception("Background scoring after refresh failed")
        finally:
            connection.close()

    threading.Thread(target=run, daemon=True).start()


@require_POST
def refresh(request):
    """Manual stand-in for the beat: poll the API now (fast, synchronous) and
    kick off scoring in the background so the request returns immediately."""
    from apps.jobs.models import SavedFilter
    from apps.jobs.tasks import collect_for_filter

    created, errors = 0, 0
    for f in SavedFilter.objects.filter(is_active=True):
        try:
            created += collect_for_filter(f)["created"]
        except Exception:
            log.exception("Manual refresh failed for filter %s", f.name)
            errors += 1
    _score_in_background()
    if errors and not created:
        messages.error(request, _("Не удалось получить вакансии из API. Проверь ключ и подключение."))
    else:
        messages.success(request, _(
            "Собрано новых: %(n)s. Идёт оценка — обнови страницу через минуту."
        ) % {"n": created})
    return redirect(_safe_next(request))


@require_POST
def skip_all(request):
    """Bulk-clear the untouched review backlog (status new/scored) for the current
    track, deleting the rows so the DB doesn't bloat. Drafts, approved and sent
    jobs are kept — only never-touched ones go."""
    from apps.jobs.models import ClientProfile

    track = request.POST.get("track", "all")
    qs = JobPosting.objects.filter(
        status__in=[JobPosting.Status.NEW, JobPosting.Status.SCORED]
    )
    if track != "all":
        try:
            qs = qs.filter(matched_filter__track_id=int(track))
        except ValueError:
            pass
    n = qs.count()
    qs.delete()  # cascades JobScore / drafts; orphaned clients tidied below
    ClientProfile.objects.filter(jobs__isnull=True).delete()
    messages.success(request, _("Удалено вакансий из ленты: %(n)s.") % {"n": n})
    return redirect(_safe_next(request))


def _translations_ready(job) -> bool:
    if job.description and not job.description_ru:
        return False
    s = getattr(job, "score", None)
    return not (s and s.breakdown and not s.breakdown_ru)


def _translate_in_background(pk):
    """Translate a job's title/description/reasons off the request thread, so the
    detail page opens instantly in English and the RU pulls in when it's ready."""
    import threading

    from django.db import connection

    def run():
        try:
            job = JobPosting.objects.select_related("score").filter(pk=pk).first()
            if job:
                job.ensure_ru()
                if getattr(job, "score", None):
                    job.score.ensure_ru()
        except Exception:
            log.exception("Background translation failed for job %s", pk)
        finally:
            connection.close()

    threading.Thread(target=run, daemon=True).start()


def tr_status(request, pk):
    """Poll target: is this job's RU translation cached yet?"""
    from django.http import JsonResponse

    job = get_object_or_404(JobPosting.objects.select_related("score"), pk=pk)
    return JsonResponse({"ready": _translations_ready(job)})


def detail(request, pk):
    from django.utils.translation import get_language

    from apps.letters.models import CoverLetterDraft
    from apps.letters.presenters import cover_context
    from apps.screening.models import ScreeningQuestion

    # Content language for this card: ?lang overrides, else follows the UI language.
    lang = request.GET.get("lang") or (get_language() or "ru")
    lang = "ru" if str(lang).startswith("ru") else "en"

    job = get_object_or_404(
        JobPosting.objects.select_related("client", "score", "matched_filter__track"), pk=pk
    )
    # Don't block the page on translation: if RU is wanted but not cached yet,
    # serve English now, translate in the background, and let the page pull RU in.
    translating = False
    if lang == "ru" and not _translations_ready(job):
        _translate_in_background(job.pk)
        lang = "en"
        translating = True
    dj = job_detail(job, lang=lang)
    draft = CoverLetterDraft.objects.filter(job=job, is_active=True).first()
    cover = cover_context(draft, edit=request.GET.get("edit") == "1") if draft else None

    screening = []
    for q in ScreeningQuestion.objects.filter(job=job).select_related("answer"):
        ans = getattr(q, "answer", None)
        screening.append({"id": ans.id if ans else None, "num": q.order + 1,
                          "q": q.text, "a": ans.body if ans else ""})
    return render(
        request,
        "jobs/detail.html",
        {
            "job": dj,
            "pk": job.pk,
            "cover": cover,
            "content_lang": lang,
            "translating": translating,
            "screening": screening,
            "has_screening_questions": bool((job.raw or {}).get("screening_questions")),
            "is_feed": True,  # sidebar keeps "Лента" active, like the design
        },
    )


@require_POST
def job_action(request, pk, action):
    job = get_object_or_404(JobPosting, pk=pk)
    target = _ACTIONS.get(action)
    if target is None:
        messages.error(request, _("Неизвестное действие: %(action)s") % {"action": action})
    else:
        try:
            job.transition_to(target)
        except ValueError as exc:
            messages.warning(request, str(exc))
    nxt = request.POST.get("next", "")
    if nxt.startswith("/") and not nxt.startswith("//"):  # local path, not //evil.com
        return redirect(nxt)
    return redirect("jobs:feed")
