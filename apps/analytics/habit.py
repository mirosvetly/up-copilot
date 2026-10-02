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


def _streaks(days: set[date], today: date, quiet: set[date] = frozenset(),
             freeze_every: int = 7) -> tuple[int, int, set[date]]:
    """(current, best, frozen days). A day with a proposal extends the streak; a quiet day
    (no job worth sending) and one missed day per `freeze_every` days (a freeze) keep it
    without extending it; today with nothing sent yet is still pending."""
    if not days:
        return 0, 0, set()
    run = best = 0
    last_freeze, frozen = None, set()
    d = min(days)
    while d <= today:
        if d in days:
            run += 1
        elif d == today or d in quiet:
            pass
        elif last_freeze is None or (d - last_freeze).days >= freeze_every:
            frozen.add(d); last_freeze = d
        else:
            run = 0
        best = max(best, run)
        d += timedelta(days=1)
    return run, best, frozen


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
    # Quiet day: jobs were collected but none worth a ping. The market was empty, not you.
    collected, good = set(), set()
    for created, score in JobPosting.objects.filter(created_at__date__gte=min(days, default=today)).values_list(
            "created_at", "score__score"):
        day = timezone.localtime(created).date()
        collected.add(day)
        if score is not None and score >= settings.NOTIFY_MIN_SCORE:
            good.add(day)
    quiet = collected - good
    current, best, frozen = _streaks(days, today, quiet)

    # Calendar: WEEKS columns of Mon..Sun, ending with the current week.
    start = today - timedelta(days=today.weekday() + 7 * (WEEKS - 1))
    weeks = []
    for w in range(WEEKS):
        col = []
        for i in range(7):
            d = start + timedelta(days=7 * w + i)
            n = per_day.get(d, 0)
            level = 0 if not n else 3 if n >= goal else 1 if n == 1 else 2
            col.append({"date": d, "n": n, "level": level, "future": d > today, "today": d == today,
                        "frozen": d in frozen, "quiet": not n and d in quiet and d < today})
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
        "frozen_recent": max((d for d in frozen if (today - d).days < 7), default=None),
        "best": best,
        "total": counts["total"],
        "weeks": weeks,
        "trophies": trophies,
        "unlocked": sum(t["unlocked"] for t in trophies),
        "next": nxt,
    }
