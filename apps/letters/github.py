"""GitHub RAG layer: surface portfolio repos relevant to a job's stack.

MockGitHub reads repos from stack_profile.yaml (no network); GitHubClient hits
the real API when GITHUB_PROVIDER=github and a token is set.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from django.conf import settings

from apps.scoring.profile import load_profile

# Palette matching the design's source-highlight legend.
_COLORS = ["#b6d086", "#60a5fa", "#c084fc", "#f59e0b", "#4ade80"]


@dataclass
class Repo:
    name: str
    skills: list[str]
    color: str = "#b6d086"
    description: str = ""
    languages: list[str] = field(default_factory=list)
    url: str = ""


class GitHubProvider(ABC):
    @abstractmethod
    def repos(self) -> list[Repo]:
        raise NotImplementedError

    def relevant(self, job_skills: list[str], limit: int = 3) -> list[Repo]:
        """Repos whose skills overlap the job, most-overlap first."""
        js = {s.lower() for s in job_skills}
        scored = []
        for r in self.repos():
            overlap = len({s.lower() for s in r.skills} & js)
            if overlap:
                scored.append((overlap, r))
        scored.sort(key=lambda t: t[0], reverse=True)
        picked = [r for _, r in scored[:limit]]
        return picked or self.repos()[:1]


class MockGitHub(GitHubProvider):
    def repos(self) -> list[Repo]:
        projects = load_profile().get("projects", [])
        return [
            Repo(
                name=p["repo"],
                skills=p.get("skills", []),
                color=_COLORS[i % len(_COLORS)],
                description=f"{', '.join(p.get('skills', [])[:3])} project",
                languages=p.get("skills", [])[:3],
            )
            for i, p in enumerate(projects)
        ]


class GitHubClient(GitHubProvider):
    """Real GitHub API. Maps each repo to profile skills for relevance."""

    def repos(self) -> list[Repo]:
        import requests  # lazy

        user = settings.GITHUB_USER
        headers = {"Authorization": f"Bearer {settings.GITHUB_TOKEN}"}
        resp = requests.get(
            f"https://api.github.com/users/{user}/repos?sort=updated&per_page=30",
            headers=headers, timeout=15,
        )
        resp.raise_for_status()
        out = []
        for i, r in enumerate(resp.json()):
            langs = [r["language"]] if r.get("language") else []
            out.append(Repo(
                name=r["name"], skills=langs + (r.get("topics") or []),
                color=_COLORS[i % len(_COLORS)],
                description=r.get("description") or "", languages=langs,
                url=r.get("html_url", ""),
            ))
        return out


def get_github() -> GitHubProvider:
    if settings.GITHUB_PROVIDER == "github" and settings.GITHUB_TOKEN:
        return GitHubClient()
    return MockGitHub()


def color_map() -> dict[str, str]:
    """repo name -> highlight colour, for rendering cover-letter sources."""
    return {r.name: r.color for r in get_github().repos()}
