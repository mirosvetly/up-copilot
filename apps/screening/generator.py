"""Answer client screening questions via RAG over the KnowledgeBase.

Mock path returns the best-matching KB fact; real path prompts Claude with the
retrieved facts as context. Same ScreeningAnswer output."""
from __future__ import annotations

import re

from apps.core.llm import get_llm

from .models import KnowledgeBase, ScreeningAnswer, ScreeningQuestion

_SYSTEM = (
    "You answer Upwork screening questions as the freelancer Denis, in the first "
    "person, 1-3 sentences, concrete and honest. Use only the provided facts."
)


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zа-я0-9]+", text.lower()) if len(w) > 2}


def retrieve(question_text: str, limit: int = 3) -> list[KnowledgeBase]:
    """Rank KB entries by keyword/content overlap with the question."""
    q = _tokens(question_text)
    scored = []
    for kb in KnowledgeBase.objects.all():
        hay = _tokens(" ".join(kb.keywords) + " " + kb.content)
        overlap = len(q & hay)
        if overlap:
            scored.append((overlap, kb))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [kb for _, kb in scored[:limit]]


def generate_answer(question: ScreeningQuestion) -> ScreeningAnswer:
    facts = retrieve(question.text)
    llm = get_llm()
    if llm:
        ctx = "\n".join(f"- {f.content}" for f in facts) or "(no facts on file)"
        body = llm.complete(_SYSTEM, f"Facts:\n{ctx}\n\nQuestion: {question.text}", max_tokens=200)
        model_name = "anthropic"
    else:
        body = facts[0].content if facts else "Yes — happy to walk through this on a quick call."
        model_name = "mock-rag-v1"
    answer, _ = ScreeningAnswer.objects.update_or_create(
        question=question, defaults={"body": body, "model_name": model_name}
    )
    return answer


def ensure_screening(job) -> int:
    """Create ScreeningQuestion rows from job.raw and draft any missing answers."""
    questions = (job.raw or {}).get("screening_questions", [])
    made = 0
    for i, text in enumerate(questions):
        q, _ = ScreeningQuestion.objects.get_or_create(job=job, order=i, defaults={"text": text})
        if not ScreeningAnswer.objects.filter(question=q).exists():
            generate_answer(q)
            made += 1
    return made
