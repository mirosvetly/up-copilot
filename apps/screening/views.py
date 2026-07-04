from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from apps.jobs.models import JobPosting

from .generator import ensure_screening
from .models import ScreeningAnswer


@require_POST
def generate(request, pk):
    job = get_object_or_404(JobPosting, pk=pk)
    ensure_screening(job)
    return redirect("jobs:detail", pk=pk)


@require_POST
def save(request, pk):
    """Persist hand-edited answers. Fields named answer_<answer_id>."""
    for key, value in request.POST.items():
        if key.startswith("answer_"):
            ScreeningAnswer.objects.filter(
                pk=key.removeprefix("answer_"), question__job_id=pk
            ).update(body=value)
    return redirect("jobs:detail", pk=pk)
