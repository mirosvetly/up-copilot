from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from .forms import TrackForm
from .models import Track


def track_list(request):
    return render(
        request,
        "tracks/list.html",
        {"tracks": Track.objects.all(), "is_settings": True},
    )


def track_edit(request, pk=None):
    track = get_object_or_404(Track, pk=pk) if pk else None
    if request.method == "POST":
        form = TrackForm(request.POST, instance=track)
        if form.is_valid():
            saved = form.save()
            messages.success(request, f"Трек «{saved.name}» сохранён.")
            return redirect("tracks:list")
    else:
        form = TrackForm(instance=track)
    return render(
        request,
        "tracks/edit.html",
        {"form": form, "track": track, "is_settings": True},
    )
