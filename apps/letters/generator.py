"""Cover-letter generation. Mock path builds a deterministic segmented draft
from relevant GitHub repos; real path prompts Claude. Same CoverLetterDraft output."""
from __future__ import annotations

from apps.core.llm import get_llm
from apps.jobs.models import JobPosting
from apps.scoring.profile import resolve_track, track_config

from .github import Repo, get_github
from .models import CoverLetterDraft


def _system(cfg: dict) -> str:
    return f"{cfg['cover_letter_instructions']} End with exactly:\n{cfg['signoff']}"


def _prompt(job: JobPosting, repos: list[Repo], reasoning: str) -> str:
    repo_lines = "\n".join(f"- {r.name}: {r.description} ({', '.join(r.skills)})" for r in repos)
    return (
        f"Job title: {job.title}\n\nJob description:\n{job.description}\n\n"
        f"Why it fits (scorer): {reasoning}\n\n"
        f"My relevant GitHub projects:\n{repo_lines}\n\n"
        "Write the cover letter."
    )


def _no_repo_segments(job: JobPosting, cfg: dict) -> list[dict]:
    """Cover letter for a track with no portfolio yet — no repo references."""
    top = job.skills[0] if job.skills else "software"
    return [
        {"t": f"Hi — \"{job.title}\" is squarely the kind of {top} work I take on. "
              f"I move fast, keep scope tight, and share tested code with clear async updates.\n\n"
              f"I can start this week and hop on a quick call to walk through the plan.\n\n{cfg['signoff']}",
         "src": None},
    ]


def _mock_segments(job: JobPosting, repos: list[Repo], version: int, cfg: dict) -> list[dict]:
    if not repos:
        return _no_repo_segments(job, cfg)
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
    segs.append({"t": f"I can start this week and overlap on a quick call. Happy to walk through the repos and scope.\n\n{cfg['signoff']}", "src": None})
    return segs


def generate_cover(job: JobPosting) -> CoverLetterDraft:
    cfg = track_config(resolve_track(job))
    repos = get_github(projects=cfg["projects"]).relevant(job.skills)
    reasoning = job.score.reasoning if getattr(job, "score", None) else ""
    version = job.cover_drafts.count()
    llm = get_llm()
    if llm:
        body = llm.complete(_system(cfg), _prompt(job, repos, reasoning), max_tokens=512)
        segments = [{"t": body, "src": None}]
        model_name = "anthropic"
    else:
        segments = _mock_segments(job, repos, version, cfg)
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
