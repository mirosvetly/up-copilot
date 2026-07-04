from __future__ import annotations

from django.conf import settings

from .base import EmbeddingProvider


class VoyageEmbedding(EmbeddingProvider):
    """Real embeddings via Voyage AI (Anthropic's recommended provider)."""

    dim = 1024

    def __init__(self, model: str = "voyage-3"):
        import voyageai  # lazy

        self._client = voyageai.Client(api_key=settings.VOYAGE_API_KEY)
        self._model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed(texts, model=self._model).embeddings
