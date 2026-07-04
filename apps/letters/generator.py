"""Cover-letter generation. Mock path builds a deterministic segmented draft
from relevant GitHub repos; real path prompts Claude. Same CoverLetterDraft output."""
from __future__ import annotations

from apps.core.llm import get_llm
from apps.jobs.models import JobPosting

from .github import Repo, get_github
from .models import CoverLetterDraft

_SYSTEM = (
    "You write concise, specific Upwork cover letters in the freelancer's voice. "
    "No fluff, 120-160 words, reference the named GitHub projects, end with 'Best,\\nDenis'."
)


def _prompt(job: JobPosting, repos: list[Repo], reasoning: str) -> str:
    repo_lines = "\n".join(f"- {r.name}: {r.description} ({', '.join(r.skills)})" for r in repos)
    return (
        f"Job title: {job.title}\n\nJob description:\n{job.description}\n\n"
        f"Why it fits (scorer): {reasoning}\n\n"
        f"My relevant GitHub projects:\n{repo_lines}\n\n"
        "Write the cover letter."
    )


def _mock_segments(job: JobPosting, repos: list[Repo], version: int) -> list[dict]:
    top = job.skills[0] if job.skills else "software"
    r0 = repos[0]
    r1 = repos[1] if len(repos) > 1 else None
    if version % 2 == 0:
        segs = [
            {"t": f"Hi — I build production {top} systems, and \"{job.title}\" is squarely in my wheelhouse.\n\n", "src": None},
            {"t": f"I recently shipped {r0.name}", "src": r0.name},
            {"t": f" ({r0.description}), which maps directly onto what you need.\n\n", "src": None},
        ]
    else:
        segs = [
            {"t": f"Hello! Owning \"{job.title}\" end-to-end is exactly the kind of {top} work I take on.\n\n", "src": None},
            {"t": f"My {r0.name} project", "src": r0.name},
            {"t": f" already covers {r0.description}, so I can move fast.\n\n", "src": None},
        ]
    if r1:
        segs += [
            {"t": f"I've also built {r1.name}", "src": r1.name},
            {"t": ", so the adjacent pieces won't surprise me. Tested code and clear async updates as standard.\n\n", "src": None},
        ]
    segs.append({"t": "I can start this week and overlap 4+ hours with US Eastern. Happy to walk through the repos on a quick call.\n\nBest,\nDenis", "src": None})
    return segs


def generate_cover(job: JobPosting) -> CoverLetterDraft:
    repos = get_github().relevant(job.skills)
    reasoning = job.score.reasoning if getattr(job, "score", None) else ""
    version = job.cover_drafts.count()
    llm = get_llm()
    if llm:
        body = llm.complete(_SYSTEM, _prompt(job, repos, reasoning), max_tokens=512)
        segments = [{"t": body, "src": None}]
        model_name = "anthropic"
    else:
        segments = _mock_segments(job, repos, version)
        body = "".join(s["t"] for s in segments)
        model_name = "mock-template-v1"

    job.cover_drafts.update(is_active=False)
    draft = CoverLetterDraft.objects.create(
        job=job, version=version, body=body, segments=segments,
        sources=[r.name for r in repos], is_active=True, model_name=model_name,
    )
    if job.status == JobPosting.Status.SCORED:
        job.transition_to(JobPosting.Status.DRAFTED)
    return draft
