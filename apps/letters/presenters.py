from __future__ import annotations

from apps.scoring.profile import resolve_track, track_config

from .github import color_map


def cover_context(draft, *, edit=False) -> dict:
    """Display fields for the cover-letter card: highlighted segments + legend."""
    cmap = color_map(track_config(resolve_track(draft.job))["projects"])
    segments = []
    for s in draft.segments:
        src = s.get("src")
        if src and src in cmap:
            c = cmap[src]
            segments.append({
                "t": s["t"], "bg": c + "22", "border": f"1.5px solid {c}",
                "radius": "3px", "pad": "1px 2px", "color": "#f0f0f0",
                "title": f"Взято из {src}",
            })
        else:
            segments.append({
                "t": s["t"], "bg": "transparent", "border": "none",
                "radius": "0", "pad": "0", "color": "#e5e5e5", "title": "",
            })
    legend = [{"label": name, "color": cmap.get(name, "#b6d086")} for name in draft.sources]
    return {
        "id": draft.id,
        "version": draft.version,
        "body": draft.body,
        "segments": segments,
        "legend": legend,
        "edit": edit,
        "model_name": draft.model_name,
    }
