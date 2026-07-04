"""Funnel / keyword / heatmap aggregates from real rows, shaped for the
analytics template (colours precomputed, mirroring the design's builders)."""
from __future__ import annotations

from collections import Counter

from django.db.models import Avg
from django.utils import timezone

from apps.jobs.models import JobPosting
from apps.letters.models import CoverLetterDraft
from apps.scoring.models import JobScore

S = JobPosting.Status
_DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
_BUCKETS = ["00", "03", "06", "09", "12", "15", "18", "21"]


def funnel_counts() -> list[tuple[str, int]]:
    return [
        ("Найдено", JobPosting.objects.count()),
        ("Прошло скоринг", JobScore.objects.values("job").distinct().count()),
        ("Черновик готов", CoverLetterDraft.objects.values("job").distinct().count()),
        ("Одобрено", JobPosting.objects.filter(status__in=[S.REVIEWED, S.APPLIED]).count()),
        ("Отправлено", JobPosting.objects.filter(status=S.APPLIED).count()),
        ("Интервью", JobPosting.objects.filter(interviewed_at__isnull=False).count()),
        ("Найм", JobPosting.objects.filter(hired_at__isnull=False).count()),
    ]


def funnel() -> list[dict]:
    steps = funnel_counts()
    total = steps[0][1] or 1
    out = []
    for i, (label, count) in enumerate(steps):
        prev = steps[i - 1][1] if i else count
        shade = max(0.28, 0.9 - i * 0.1)
        out.append({
            "label": label, "count": count,
            "pct": max(6, round(count / total * 100)),
            "conv": "100%" if i == 0 else f"{round(count / prev * 100) if prev else 0}%",
            "color": f"rgba(182,208,134,{shade})",
            "text_color": "#171717" if i < 4 else "#dfe9c9",
        })
    return out


def keywords(limit: int = 7) -> list[dict]:
    total, applied = Counter(), Counter()
    for j in JobPosting.objects.only("skills", "status"):
        is_applied = j.status == S.APPLIED
        for s in j.skills:
            total[s] += 1
            if is_applied:
                applied[s] += 1
    rows = []
    for kw, n in total.most_common(limit):
        conv = round(applied[kw] / n * 100) if n else 0
        rows.append({"kw": kw, "n": n, "conv": conv})
    mx = max((r["conv"] for r in rows), default=1) or 1
    for r in rows:
        r["bar_w"] = round(r["conv"] / mx * 100)
        r["color"] = "#4ade80" if r["conv"] >= 30 else "#facc15" if r["conv"] >= 15 else "#8a8a8a"
    return rows


def heatmap() -> dict:
    m = [[0] * 8 for _ in range(7)]
    for j in JobPosting.objects.filter(score__score__gt=75).only("posted_at"):
        if not j.posted_at:
            continue
        dt = timezone.localtime(j.posted_at)
        m[dt.weekday()][dt.hour // 3] += 1
    mx = max((v for row in m for v in row), default=0) or 1
    rows = []
    for di, day in enumerate(_DAYS):
        cells = []
        for v in m[di]:
            alpha = 0.05 if v == 0 else 0.1 + 0.9 * (v / mx)
            cells.append({
                "text": v if v else "",
                "bg": f"rgba(182,208,134,{alpha:.3f})",
                "border": "1px solid rgba(182,208,134,0.5)" if v >= max(2, mx * 0.7) else "1px solid transparent",
                "text_color": "#171717" if v >= max(2, mx * 0.7) else "#c5dc9f",
            })
        rows.append({"day": day, "cells": cells})
    return {"buckets": _BUCKETS, "rows": rows}


def stat_cards() -> list[dict]:
    applied = JobPosting.objects.filter(status=S.APPLIED).count()
    interview = JobPosting.objects.filter(interviewed_at__isnull=False).count()
    avg = JobScore.objects.filter(
        job__status__in=[S.REVIEWED, S.APPLIED]
    ).aggregate(a=Avg("score"))["a"]
    return [
        {"label": "Найдено", "value": JobPosting.objects.count()},
        {"label": "Отправлено", "value": applied},
        {"label": "Ответ клиента", "value": f"{round(interview / applied * 100) if applied else 0}%"},
        {"label": "Найм", "value": JobPosting.objects.filter(hired_at__isnull=False).count()},
        {"label": "Ср. score одобр.", "value": round(avg) if avg else "—"},
    ]


def prometheus_text() -> str:
    lines = ["# HELP upwork_funnel Jobs reaching each pipeline stage",
             "# TYPE upwork_funnel gauge"]
    slug = {"Найдено": "found", "Прошло скоринг": "scored", "Черновик готов": "drafted",
            "Одобрено": "reviewed", "Отправлено": "applied", "Интервью": "interview", "Найм": "hire"}
    for label, count in funnel_counts():
        lines.append(f'upwork_funnel{{stage="{slug[label]}"}} {count}')
    return "\n".join(lines) + "\n"
