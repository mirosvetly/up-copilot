from __future__ import annotations

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.scoring.profile import load_profile

from .models import JobPosting
from .presenters import job_card, job_detail

# Feed action -> target status. transition_to() enforces legality.
_ACTIONS = {
    "approve": JobPosting.Status.REVIEWED,
    "skip": JobPosting.Status.SKIPPED,
    "undo": JobPosting.Status.SCORED,
    "mark_sent": JobPosting.Status.APPLIED,
}


def feed(request):
    q = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "fresh")
    qs = (
        JobPosting.objects.exclude(status=JobPosting.Status.EXPIRED)
        .select_related("client", "score")
    )
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(skills__icontains=q))

    my_skills_lc = {s.lower() for s in load_profile().get("skills", [])}
    cards = [job_card(j, my_skills_lc=my_skills_lc) for j in qs]

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
            "is_feed": True,
        },
    )


def detail(request, pk):
    from apps.letters.models import CoverLetterDraft
    from apps.letters.presenters import cover_context
    from apps.screening.models import ScreeningQuestion

    job = get_object_or_404(
        JobPosting.objects.select_related("client", "score"), pk=pk
    )
    dj = job_detail(job)
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
        messages.error(request, f"Неизвестное действие: {action}")
    else:
        try:
            job.transition_to(target)
        except ValueError as exc:
            messages.warning(request, str(exc))
    nxt = request.POST.get("next", "")
    if nxt.startswith("/") and not nxt.startswith("//"):  # local path, not //evil.com
        return redirect(nxt)
    return redirect("jobs:feed")
