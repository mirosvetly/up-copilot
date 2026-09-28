"""Daily-proposals habit: today's goal, streak, a GitHub-style calendar and trophies.

A day counts toward the streak with at least one proposal sent; the daily goal is
the brighter target on top. Days are local (settings.TIME_ZONE)."""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.jobs.models import JobPosting

from .models import MoneyEntry

WEEKS = 16

# (key, emoji, title, kind, threshold). kind: total | streak | goal_day | interview | hire | income ($)
TROPHIES = [
    ("first", "📨", "Первый отклик", "total", 1),
    ("goal", "🎯", "Цель дня выполнена", "goal_day", 1),
    ("s3", "🔥", "Серия 3 дня", "streak", 3),
    ("t10", "🥉", "10 откликов", "total", 10),
    ("s7", "🔥", "Серия неделя", "streak", 7),
    ("t25", "🥈", "25 откликов", "total", 25),
    ("s14", "🔥", "Серия 2 недели", "streak", 14),
    ("t50", "🥇", "50 откликов", "total", 50),
    ("s30", "💎", "Серия месяц", "streak", 30),
    ("t100", "🏅", "100 откликов", "total", 100),
    ("interview", "💬", "Первое собеседование", "interview", 1),
    ("hire", "🏆", "Первый заказ", "hire", 1),
    ("usd100", "💵", "Первые $100", "income", 100),
    ("usd500", "💰", "Первые $500", "income", 500),
    ("usd1000", "🤑", "Первая $1 000", "income", 1000),
    ("usd5000", "🚀", "Первые $5 000", "income", 5000),
]


def _streaks(days: set[date], today: date) -> tuple[int, int]:
    """(current, best). Today with nothing sent yet doesn't break the streak."""
    cur, d = 0, today if today in days else today - timedelta(days=1)
    while d in days:
        cur, d = cur + 1, d - timedelta(days=1)
    best = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        best, prev = max(best, run), d
    return cur, best


def _unlocked(kind, need, *, total, best, goal_days, interviews, hires, income) -> tuple[bool, int]:
    have = {"total": total, "streak": best, "goal_day": goal_days,
            "interview": interviews, "hire": hires, "income": int(income)}[kind]
    return have >= need, max(0, need - have)


def habit(today: date | None = None, goal: int | None = None) -> dict:
    goal = goal or settings.DAILY_PROPOSALS_GOAL
    today = today or timezone.localdate()
    sent = JobPosting.objects.filter(applied_at__isnull=False).values_list("applied_at", flat=True)
    per_day = Counter(timezone.localtime(t).date() for t in sent)
    days = set(per_day)
    current, best = _streaks(days, today)

    # Calendar: WEEKS columns of Mon..Sun, ending with the current week.
    start = today - timedelta(days=today.weekday() + 7 * (WEEKS - 1))
    weeks = []
    for w in range(WEEKS):
        col = []
        for i in range(7):
            d = start + timedelta(days=7 * w + i)
            n = per_day.get(d, 0)
            level = 0 if not n else 3 if n >= goal else 1 if n == 1 else 2
            col.append({"date": d, "n": n, "level": level, "future": d > today, "today": d == today})
        weeks.append(col)

    counts = dict(
        total=sum(per_day.values()), best=best,
        goal_days=sum(1 for n in per_day.values() if n >= goal),
        interviews=JobPosting.objects.filter(interviewed_at__isnull=False).count(),
        hires=JobPosting.objects.filter(hired_at__isnull=False).count(),
        income=MoneyEntry.objects.filter(kind=MoneyEntry.Kind.INCOME).aggregate(v=Sum("usd"))["v"] or 0,
    )
    trophies = []
    for key, emoji, title, kind, need in TROPHIES:
        ok, left = _unlocked(kind, need, **counts)
        trophies.append({"key": key, "emoji": emoji, "title": title, "unlocked": ok, "left": left, "kind": kind})
    nxt = next((t for t in trophies if not t["unlocked"]), None)

    return {
        "goal": goal,
        "today": per_day.get(today, 0),
        "today_left": max(0, goal - per_day.get(today, 0)),
        "streak": current,
        "best": best,
        "total": counts["total"],
        "weeks": weeks,
        "trophies": trophies,
        "unlocked": sum(t["unlocked"] for t in trophies),
        "next": nxt,
    }
