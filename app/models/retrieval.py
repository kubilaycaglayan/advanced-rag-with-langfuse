"""models / retrieval responsibilities."""
from __future__ import annotations

from app.cache.intermediate import cache_value as _cache_value
from functools import lru_cache
from sentence_transformers import CrossEncoder
from sentence_transformers import SentenceTransformer
from typing import Any


@lru_cache(maxsize=4)
def embedder(name: str, revision: str | None = None) -> SentenceTransformer:
    return SentenceTransformer(name, device="cpu", revision=revision)


@lru_cache(maxsize=4)
def reranker(name: str, revision: str | None = None) -> Any:
    class CachedCrossEncoder:
        def __init__(self) -> None:
            self.model = CrossEncoder(name, device="cpu", revision=revision)

        def predict(self, pairs: Any, **kwargs: Any) -> Any:
            normalized = [[str(query), str(text)] for query, text in pairs]
            values = _cache_value("rerank", "cross_encoder", {
                "model": name, "revision": revision, "pairs": normalized, "parameters": kwargs,
            }, input={"model": name, "revision": revision, "pairs": normalized},
                compute=lambda: [float(score) for score in self.model.predict(normalized, **kwargs)])
            import numpy as np
            return np.asarray(values)

    return CachedCrossEncoder()


def encode_query(text: str, model: str, revision: str | None = None) -> list[float]:
    return _cache_value("embedding", "query", {"text": text, "model": model, "revision": revision,
                         "normalize": True}, input={"text": text, "model": model, "revision": revision},
                        compute=lambda: embedder(model, revision).encode(
                            text, normalize_embeddings=True, show_progress_bar=False).tolist())
