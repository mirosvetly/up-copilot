"""LLM scoring path (JOB_SCORER=llm). Prompts Claude for a structured verdict.

Kept separate from the rule scorer so the mock/rule path has zero LLM imports."""
from __future__ import annotations

from apps.jobs.models import JobPosting

_SYSTEM = (
    "You are a freelance-job screener for a senior Python/Django + MQL5 + WebRTC "
    "developer. Score fit 0-100 and justify it. Reply with ONLY JSON: "
    '{"score": int, "reasoning": str, "breakdown": [{"text": str, "w": int, "neg": bool}]}. '
    "Each breakdown item is one factor; w is its 0-30 weight; neg=true for negatives."
)


def _prompt(job: JobPosting, profile: dict, similarity: float) -> str:
    return (
        f"My stack: {', '.join(profile.get('skills', []))}. "
        f"Min rate: ${profile.get('min_hourly_rate')}/hr.\n"
        f"Profile↔job embedding cosine: {similarity:.2f}\n\n"
        f"Job: {job.title}\nSkills: {', '.join(job.skills)}\n"
        f"Budget: {job.budget_type} {job.budget_min}-{job.budget_max}\n"
        f"Description:\n{job.description}"
    )


def llm_compute(job: JobPosting, profile: dict, similarity: float, llm) -> dict:
    data = llm.complete_json(_SYSTEM, _prompt(job, profile, similarity), max_tokens=700)
    score = max(0, min(100, int(data.get("score", 0))))
    breakdown = [
        {"text": str(b.get("text", "")), "w": int(b.get("w", 0)), "neg": bool(b.get("neg", False))}
        for b in data.get("breakdown", [])
    ]
    return {
        "score": score,
        "reasoning": str(data.get("reasoning", "")),
        "breakdown": breakdown,
    }
