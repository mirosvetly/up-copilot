"""EN -> RU translation for reading job posts and reviewing draft letters.

Free by default (Google via deep-translator, no key, no LLM cost). translate_ru
returns "" on empty input, the mock provider, or any failure — callers then
fall back to the original English, so translation never breaks a page.
"""
from __future__ import annotations

import logging
import threading

from django.conf import settings

log = logging.getLogger(__name__)

_GOOGLE_MAX = 4500   # Google's request cap is ~5000 chars; chunk below it
_MYMEMORY_MAX = 480  # MyMemory caps each request near 500 chars
# deep-translator 1.9 has no timeout knob and its requests.get can hang forever
# (the free Google endpoint sometimes just never answers), which left the "RU
# loading" spinner spinning for good. Bound every call so it always resolves;
# on timeout we fall back to the English original like any other failure.
_TIMEOUT_S = 8


def _timed(fn, arg):
    # A daemon worker so a hung request never blocks process exit; join() caps
    # the wait, and TimeoutError makes translate_ru fall back to English.
    box: dict = {}

    def run():
        try:
            box["v"] = fn(arg)
        except Exception as exc:  # noqa: BLE001 — surfaced to the caller below
            box["e"] = exc

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(_TIMEOUT_S)
    if th.is_alive():
        raise TimeoutError("translation timed out")
    if "e" in box:
        raise box["e"]
    return box.get("v", "")


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


def _make_translator():
    """Return (translator, chunk_size). MyMemory is the default: it answers from
    networks where Google's free endpoint is blocked or just hangs. Set
    TRANSLATE_ENGINE=google for accounts where Google is reachable (no daily cap)."""
    from deep_translator import GoogleTranslator, MyMemoryTranslator

    if settings.TRANSLATE_ENGINE == "google":
        # auto source: reasons may already be Russian (rule scorer) — don't force EN
        return GoogleTranslator(source="auto", target="ru"), _GOOGLE_MAX
    return MyMemoryTranslator(source="en-GB", target="ru-RU"), _MYMEMORY_MAX


def _translate(text: str) -> str:
    tr, cap = _make_translator()
    if len(text) <= cap:
        return tr.translate(text) or ""
    return "\n".join(tr.translate(c) or "" for c in _chunks(text, cap))


def translate_ru(text: str) -> str:
    text = (text or "").strip()
    if not text or settings.TRANSLATE_PROVIDER == "mock":
        return ""
    try:
        return _timed(_translate, text)
    except Exception:
        log.exception("Translation failed")
        return ""


def _translate_batch(items: list[str]) -> list[str]:
    tr, _ = _make_translator()
    return tr.translate_batch(items)


def translate_ru_batch(texts: list[str]) -> list[str]:
    """Translate many short strings in one call (e.g. scoring reasons) instead of
    one HTTP round-trip each. Returns "" per item on failure/mock (caller keeps EN)."""
    texts = [t or "" for t in texts]
    idx = [i for i, t in enumerate(texts) if t.strip()]
    if not idx or settings.TRANSLATE_PROVIDER == "mock":
        return ["" for _ in texts]
    try:
        got = _timed(_translate_batch, [texts[i] for i in idx])
        out = ["" for _ in texts]
        for k, i in enumerate(idx):
            out[i] = got[k] or ""
        return out
    except Exception:
        log.exception("Batch translation failed")
        return ["" for _ in texts]
