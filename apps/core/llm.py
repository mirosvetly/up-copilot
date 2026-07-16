"""Shared LLM access. Real provider is optional and lazily imported.

get_llm() returns a real client only when LLM_PROVIDER=anthropic AND a key is set;
otherwise None — the signal for each domain generator to use its deterministic
mock path. This keeps the whole app runnable with zero credentials.
"""
from __future__ import annotations

import json
import logging
import re

from django.conf import settings

log = logging.getLogger(__name__)


class AnthropicLLM:
    def __init__(self, model: str | None = None):
        import anthropic  # lazy: only needed on the real path

        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._model = model or settings.ANTHROPIC_MODEL

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text")
        if not text and msg.content:
            # Sonnet-5's extended thinking can eat the whole max_tokens budget,
            # leaving no text block. Surface it instead of returning "" silently.
            log.warning(
                "Empty text from %s (stop=%s, blocks=%s) — max_tokens=%d likely too low",
                self._model, msg.stop_reason, [b.type for b in msg.content], max_tokens,
            )
        return text

    def complete_json(self, system: str, user: str, max_tokens: int = 1024) -> dict:
        return _extract_json(self.complete(system, user, max_tokens))


class OllamaLLM:
    """Local model via Ollama's native API — no key, no cloud, works offline and
    on networks where hosted APIs are blocked. Free, so it's the cheap path for
    bulk scoring. Uses format=json so the verdict is always valid JSON."""

    def __init__(self, model: str | None = None):
        self._model = model or settings.OLLAMA_MODEL
        self._url = settings.OLLAMA_BASE_URL.rstrip("/") + "/api/chat"

    def _chat(self, system: str, user: str, max_tokens: int, fmt: str | None = None) -> str:
        import requests  # lazy: only on the real path

        body = {
            "model": self._model,
            "stream": False,
            # Keep the model resident between jobs so a batch doesn't pay the
            # ~15s cold-load on every call.
            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"num_predict": max_tokens, "temperature": 0},
        }
        if fmt:
            body["format"] = fmt
        resp = requests.post(self._url, json=body, timeout=settings.OLLAMA_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "") or ""

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        return self._chat(system, user, max_tokens)

    def complete_json(self, system: str, user: str, max_tokens: int = 1024) -> dict:
        return _extract_json(self._chat(system, user, max_tokens, fmt="json"))


def get_llm(model: str | None = None, provider: str | None = None):
    """Real client for the given provider (defaults to LLM_PROVIDER), else None.
    `model` overrides the Anthropic model (ignored by Ollama, which uses
    OLLAMA_MODEL). `provider` lets scoring pick a different backend than letters
    — e.g. free local Ollama for scoring, Anthropic Sonnet for cover letters."""
    provider = provider or settings.LLM_PROVIDER
    if provider == "ollama":
        return OllamaLLM()
    if provider == "anthropic" and settings.ANTHROPIC_API_KEY:
        return AnthropicLLM(model)
    return None


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM reply (handles ``` fences)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    blob = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(blob)
