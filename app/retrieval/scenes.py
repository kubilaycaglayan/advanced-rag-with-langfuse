"""retrieval / scenes responsibilities."""
from __future__ import annotations

from app.indexing.scenes import scene_collection
from app.pipelines.config import ResolvedPipelineConfig
from app.retrieval.search import qdrant_client
from typing import Any


def scene_lookup(collection: str, config: ResolvedPipelineConfig, wanted: str) -> tuple[Any | None, str]:
    """Resolve a scene id (full or 8-character prefix) against the scene index."""
    wanted = (wanted or "").strip().strip("[]")
    if len(wanted) < 6:
        return None, f"scene id {wanted!r} is too short"
    name = scene_collection(collection, config)
    qdrant = qdrant_client()
    if not qdrant.collection_exists(name):
        return None, "the scene index is not built for this collection"
    matches, offset = [], None
    while True:
        batch, offset = qdrant.scroll(collection_name=name, limit=1000, offset=offset, with_payload=True)
        matches += [point for point in batch if str(point.id).startswith(wanted)]
        if offset is None or len(matches) > 1:
            break
    if len(matches) == 1:
        return matches[0], ""
    if len(matches) > 1:
        return None, f"scene id {wanted!r} is ambiguous ({len(matches)} scenes)"
    return None, f"no scene with id {wanted!r}"
