from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.jobs.models import JobPosting

from .generator import generate_cover
from .models import CoverLetterDraft


def _back(pk):
    # #cover anchors the scroll to the letter card so the page doesn't jump to top
    return redirect(reverse("jobs:detail", args=[pk]) + "#cover")


@require_POST
def generate(request, pk):
    job = get_object_or_404(JobPosting, pk=pk)
    generate_cover(job)  # also handles regenerate (new version)
    return _back(pk)


@require_POST
def save(request, pk):
    """Persist a hand-edited body on the active draft."""
    draft = get_object_or_404(CoverLetterDraft, job_id=pk, is_active=True)
    draft.body = request.POST.get("body", draft.body)
    draft.segments = [{"t": draft.body, "src": None}]  # edited => single plain span
    draft.save(update_fields=["body", "segments", "updated_at"])
    return _back(pk)
