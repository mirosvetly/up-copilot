"""EN -> RU translation for reading job posts and reviewing draft letters.

Free by default (Google via deep-translator, no key, no LLM cost). translate_ru
returns "" on empty input, the mock provider, or any failure — callers then
fall back to the original English, so translation never breaks a page.
"""
from __future__ import annotations

import logging

from django.conf import settings

log = logging.getLogger(__name__)

_MAX = 4500  # Google's request cap is ~5000 chars; chunk below it


def _chunks(text: str, size: int) -> list[str]:
    """Pack paragraphs into <= size pieces; hard-split any oversized paragraph."""
    chunks: list[str] = []
    cur = ""
    for para in text.split("\n"):
        piece = f"{cur}\n{para}" if cur else para
        if len(piece) <= size:
            cur = piece
            continue
        if cur:
            chunks.append(cur)
        while len(para) > size:
            chunks.append(para[:size])
            para = para[size:]
        cur = para
    if cur:
        chunks.append(cur)
    return chunks


def _google(text: str) -> str:
    from deep_translator import GoogleTranslator  # lazy: only on the real path

    # auto source: reasons may already be Russian (rule scorer) — don't force EN
    tr = GoogleTranslator(source="auto", target="ru")
    if len(text) <= _MAX:
        return tr.translate(text) or ""
    return "\n".join(tr.translate(c) or "" for c in _chunks(text, _MAX))


def translate_ru(text: str) -> str:
    text = (text or "").strip()
    if not text or settings.TRANSLATE_PROVIDER == "mock":
        return ""
    try:
        return _google(text)
    except Exception:
        log.exception("Translation failed")
        return ""
