from __future__ import annotations

import hashlib
import math
import re

from .base import EmbeddingProvider

DIM = 256


class MockEmbedding(EmbeddingProvider):
    """Deterministic hashed bag-of-words vector. Shared vocabulary -> higher
    cosine, so similarity is meaningful without any API. Stable across runs
    (hashlib, not salted hash())."""

    dim = DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * DIM
        for tok in re.findall(r"[a-zа-я0-9]+", text.lower()):
            if len(tok) <= 2:
                continue
            idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec
