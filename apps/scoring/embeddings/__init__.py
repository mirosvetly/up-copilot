from django.conf import settings

from .base import EmbeddingProvider, cosine
from .mock import MockEmbedding


def get_embedding_provider() -> EmbeddingProvider:
    if settings.EMBEDDING_PROVIDER == "voyage" and settings.VOYAGE_API_KEY:
        from .voyage import VoyageEmbedding

        return VoyageEmbedding()
    return MockEmbedding()


__all__ = ["EmbeddingProvider", "cosine", "get_embedding_provider"]
