from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from apps.core.llm import get_llm
from apps.jobs.models import JobPosting

from .embeddings import cosine, get_embedding_provider
from .llm_scorer import llm_compute
from .models import JobScore
from .profile import load_profile

# ponytail: transparent rule-based scorer + optional LLM scorer. Both keep the
# {score, breakdown, reasoning} contract so the UI/model never change.

_PROFILE_EMB_CACHE: dict[tuple, list[float]] = {}


def _add(reasons, text, w, neg=False):
    reasons.append({"text": text, "w": w, "neg": neg})


def _job_text(job: JobPosting) -> str:
    return " ".join([job.title, " ".join(job.skills), job.description or ""])


def _profile_text(profile: dict) -> str:
    skills = " ".join(profile.get("skills", []))
    projects = " ".join(
        p.get("repo", "") + " " + " ".join(p.get("skills", []))
        for p in profile.get("projects", [])
    )
    return f"{skills} {projects}"


def _profile_embedding(provider, profile: dict) -> list[float]:
    key = (type(provider).__name__, tuple(profile.get("skills", [])))
    if key not in _PROFILE_EMB_CACHE:
        _PROFILE_EMB_CACHE[key] = provider.embed_one(_profile_text(profile))
    return _PROFILE_EMB_CACHE[key]


def _compute(job: JobPosting, profile: dict, similarity: float = 0.0) -> dict:
    reasons: list[dict] = []
    score = 50
    skills_lc = {s.lower() for s in profile.get("skills", [])}
    min_rate = Decimal(str(profile.get("min_hourly_rate", 0)))

    # --- skill overlap ---
    matched = [s for s in job.skills if s.lower() in skills_lc]
    if matched:
        w = min(30, len(matched) * 8)
        score += w
        _add(reasons, f"Стек совпадает: {' · '.join(matched)} — {len(matched)} навык(ов)", w)
    else:
        score -= 18
        _add(reasons, "Стек не совпадает с твоим профилем", 18, neg=True)

    # --- verified payment ---
    client = job.client
    if client and client.verified_payment:
        score += 15
        _add(reasons, "Оплата подтверждена", 15)
    else:
        score -= 14
        _add(reasons, "Оплата не подтверждена", 14, neg=True)

    # --- budget vs floor (hourly only) ---
    if job.budget_type == JobPosting.BudgetType.HOURLY and job.budget_min is not None and min_rate:
        if job.budget_min >= min_rate:
            score += 12
            _add(reasons, f"Ставка ${job.budget_min}/час не ниже планки ${min_rate}", 12)
        else:
            score -= 10
            _add(reasons, f"Ставка ${job.budget_min}/час ниже планки ${min_rate}", 10, neg=True)

    # --- client track record ---
    if client:
        hr = client.hire_rate or 0
        if hr >= 70:
            score += 12
            _add(reasons, f"Hire rate {hr}%", 12)
        elif hr < 40:
            score -= 6
            _add(reasons, f"Низкий hire rate {hr}%", 6, neg=True)
        if client.total_spent is not None and client.total_spent == 0:
            score -= 14
            _add(reasons, "Клиент потратил $0", 14, neg=True)
        elif (client.total_spent or 0) >= 20000:
            score += 8
            _add(reasons, f"Потрачено ${int(client.total_spent):,}+", 8)
        # brand-new account relative to when the job was posted
        if client.member_since and job.posted_at:
            if (job.posted_at.date() - client.member_since).days < 45:
                score -= 6
                _add(reasons, "Аккаунт клиента создан недавно", 6, neg=True)

    # --- freshness / competition ---
    if job.posted_at:
        age_min = (timezone.now() - job.posted_at).total_seconds() / 60
        if age_min <= 15:
            score += 10
            _add(reasons, "Свежая публикация — низкая конкуренция", 10)
        elif age_min > 45:
            score -= 4
            _add(reasons, "Публикация устарела", 4, neg=True)
    if job.proposals_bucket == "< 5":
        score += 6
        _add(reasons, "Меньше 5 откликов", 6)
    elif job.proposals_bucket == "20+":
        score -= 6
        _add(reasons, "20+ откликов — высокая конкуренция", 6, neg=True)

    # --- semantic similarity (embedding) ---
    if similarity >= 0.35:
        score += 8
        _add(reasons, f"Семантическое совпадение с профилем (cos {similarity:.2f})", 8)

    # --- red flag phrases ---
    desc = (job.description or "").lower()
    hits = [p for p in profile.get("red_flag_phrases", []) if p.lower() in desc]
    if hits:
        pen = min(12, len(hits) * 8)
        score -= pen
        _add(reasons, f"Red flag в тексте: «{hits[0]}»", pen, neg=True)

    score = max(0, min(100, score))
    reasons.sort(key=lambda r: r["w"], reverse=True)
    pos = [r["text"] for r in reasons if not r["neg"]][:2]
    reasoning = "; ".join(pos) if pos else "Слабое совпадение по правилам."
    return {"score": score, "breakdown": reasons, "reasoning": reasoning}


def score_job(job: JobPosting, *, profile: dict | None = None) -> JobScore:
    """Score a job, persist JobScore (+embedding/similarity), advance new -> scored.

    JOB_SCORER=rule (default) uses the transparent heuristic; JOB_SCORER=llm with
    a configured Claude key uses the LLM scorer. Both fold in embedding similarity.
    """
    profile = profile or load_profile()
    provider = get_embedding_provider()
    job_vec = provider.embed_one(_job_text(job))
    similarity = cosine(_profile_embedding(provider, profile), job_vec)

    llm = get_llm() if settings.JOB_SCORER == "llm" else None
    if llm:
        result = llm_compute(job, profile, similarity, llm)
        model_name = "anthropic"
    else:
        result = _compute(job, profile, similarity)
        model_name = "rule-based-v1"

    obj, _ = JobScore.objects.update_or_create(
        job=job,
        defaults={
            "score": result["score"],
            "breakdown": result["breakdown"],
            "reasoning": result["reasoning"],
            "embedding": job_vec,
            "similarity": similarity,
            "model_name": model_name,
        },
    )
    if job.status == JobPosting.Status.NEW:
        job.transition_to(JobPosting.Status.SCORED)
    return obj
