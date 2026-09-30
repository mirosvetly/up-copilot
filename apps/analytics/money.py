"""Upwork money: what went in (connects, subscription), what came out (income),
and what one proposal / interview / hire actually costs."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from apps.jobs.models import JobPosting

from .models import MoneyEntry

CONNECT_PRICE = Decimal("0.15")  # Upwork list price per connect; used until you log a paid purchase


def _sum(qs, field):
    return qs.aggregate(v=Sum(field))["v"] or 0


def money() -> dict:
    entries = MoneyEntry.objects.all()
    income = _sum(entries.filter(kind=MoneyEntry.Kind.INCOME), "usd")
    spent = _sum(entries.exclude(kind=MoneyEntry.Kind.INCOME), "usd")
    buys = entries.filter(kind=MoneyEntry.Kind.CONNECTS)
    bought = _sum(buys, "connects")
    paid_buys = buys.filter(usd__gt=0)  # a $0 line is a starting balance or free monthly connects
    paid_connects = _sum(paid_buys, "connects")
    price = (_sum(paid_buys, "usd") / paid_connects) if paid_connects else CONNECT_PRICE

    sent = JobPosting.objects.filter(applied_at__isnull=False)
    logged = sent.filter(connects_spent__isnull=False)
    used = _sum(logged, "connects_spent") + _sum(entries.filter(kind=MoneyEntry.Kind.SPENT), "connects")
    per_proposal = (Decimal(used) / logged.count() * price) if logged.exists() else None
    interviews = JobPosting.objects.filter(interviewed_at__isnull=False).count()
    hires = JobPosting.objects.filter(hired_at__isnull=False).count()

    def per(n):
        return (spent / n) if n and spent else None

    return {
        "spent": spent,
        "income": income,
        "net": income - spent,
        "net_abs": abs(income - spent),
        "bought": bought,
        "used": used,
        "balance": bought - used,
        "price": price,
        "per_proposal": per_proposal,
        "logged": logged.count(),
        "sent": sent.count(),
        "viewed": sent.filter(viewed_at__isnull=False).count(),  # from the Vollna webhook
        "interviews": interviews,
        "hires": hires,
        "per_interview": per(interviews),
        "per_hire": per(hires),
        "entries": entries[:12],
        "kinds": MoneyEntry.Kind.choices,
    }
