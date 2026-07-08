"""LLM scoring path (JOB_SCORER=llm). Prompts Claude for a structured verdict.

Kept separate from the rule scorer so the mock/rule path has zero LLM imports."""
from __future__ import annotations

from apps.jobs.models import JobPosting


def _system(profile: dict) -> str:
    role = profile.get("scorer_role") or "freelancer"
    analysis_prompt = profile.get("job_analysis_prompt") or "Score fit 0-100 and justify it."
    return (
        f"You are a freelance-job screener for this freelancer: {role}. "
        f"{analysis_prompt} "
        "Output ONLY a single JSON object and NOTHING before or after it (no prose, no code fence): "
        '{"score": int, "reasoning": str, "breakdown": [{"text": str, "w": int, "neg": bool}]}. '
        "Each breakdown item is one factor; w is its 0-30 weight; neg=true for negatives. "
        "Keep it compact: at most 6 breakdown items, each text under 15 words, reasoning under 40 words."
    )


def _client_line(job: JobPosting) -> str:
    c = getattr(job, "client", None)
    if not c:
        return "Client: unknown"
    bits = [
        "payment verified" if c.verified_payment else "payment NOT verified",
        f"${int(c.total_spent)} spent" if c.total_spent is not None else "spend unknown",
        f"hire rate {c.hire_rate}%" if c.hire_rate is not None else "hire rate unknown",
        f"rating {c.avg_rating}" if c.avg_rating is not None else "no rating",
        c.country or "location unknown",
    ]
    return "Client: " + ", ".join(bits)


def _competition_line(job: JobPosting) -> str:
    raw = job.raw or {}
    bits = []
    if raw.get("connects") is not None:
        bits.append(f"{raw['connects']} connects required to apply "
                    "(higher usually means a more contested / premium posting)")
    if job.proposals_bucket:
        bits.append(f"proposals so far: {job.proposals_bucket}")
    vw = raw.get("scores") or {}
    if vw.get("redFlags") is not None:
        bits.append(f"client cleanliness {vw['redFlags']}/10 (HIGHER is better; 10 = no red flags)")
    if vw.get("quickWin") is not None:
        bits.append(f"quick-win score {vw['quickWin']}/10")
    return "Competition & signals: " + ("; ".join(bits) if bits else "n/a")


def _prompt(job: JobPosting, profile: dict, similarity: float) -> str:
    return (
        f"My stack: {', '.join(profile.get('skills', []))}. "
        f"Min rate: ${profile.get('min_hourly_rate')}/hr.\n"
        f"Profile↔job embedding cosine: {similarity:.2f}\n"
        f"{_client_line(job)}\n"
        f"{_competition_line(job)}\n\n"
        f"Job: {job.title}\nSkills: {', '.join(job.skills)}\n"
        f"Budget: {job.budget_type} {job.budget_min}-{job.budget_max}\n"
        f"Description:\n{job.description}"
    )


def llm_compute(job: JobPosting, profile: dict, similarity: float, llm) -> dict:
    data = llm.complete_json(_system(profile), _prompt(job, profile, similarity), max_tokens=1500)
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
