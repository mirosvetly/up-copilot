"""Shared LLM access. Real provider is optional and lazily imported.

get_llm() returns a real client only when LLM_PROVIDER=anthropic AND a key is set;
otherwise None — the signal for each domain generator to use its deterministic
mock path. This keeps the whole app runnable with zero credentials.
"""
from __future__ import annotations

import json
import re

from django.conf import settings


class AnthropicLLM:
    def __init__(self):
        import anthropic  # lazy: only needed on the real path

        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._model = settings.ANTHROPIC_MODEL

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")

    def complete_json(self, system: str, user: str, max_tokens: int = 1024) -> dict:
        return _extract_json(self.complete(system, user, max_tokens))


def get_llm():
    if settings.LLM_PROVIDER == "anthropic" and settings.ANTHROPIC_API_KEY:
        return AnthropicLLM()
    return None


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM reply (handles ``` fences)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    blob = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(blob)
