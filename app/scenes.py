"""Scene summaries: a second index of LLM summaries over windows of consecutive passages.

Some answers are spread over a scene whose passages never name the people involved (dialogue such as "you will
..."), so neither dense search nor the cross-encoder can tie them to a question. Each window of ``scene_window``
consecutive passages of one EPUB section (step ``scene_stride``) is summarised once, naming who does what; the
summaries are embedded into their own collection and point back to their passages.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import requests
from qdrant_client import QdrantClient, models

try:
    from .identity import canonical_json
    from .prompt_templates import PROMPT_TEMPLATES
    from .resolved_config import ResolvedPipelineConfig
except ImportError:
    from identity import canonical_json
    from prompt_templates import PROMPT_TEMPLATES
    from resolved_config import ResolvedPipelineConfig


def _cache_path() -> Path:
    return Path(os.getenv("SCENE_SUMMARY_CACHE", "/data/scene-summaries.jsonl"))


def _prompt_hash() -> str:
    return hashlib.sha256(PROMPT_TEMPLATES["scene_summary_system"].encode("utf-8")).hexdigest()


def scene_collection(collection: str, config: ResolvedPipelineConfig) -> str:
    identity = {"passages": collection, "window": config.scene_window, "stride": config.scene_stride,
                "prompt": _prompt_hash(), "model": config.generation_model.name, "embedding_model": config.embedding_model.__dict__}
    return f"{collection}_scenes_{hashlib.sha256(canonical_json(identity).encode()).hexdigest()[:12]}"


def _summary_key(members: list[str], config: ResolvedPipelineConfig) -> str:
    return hashlib.sha256(canonical_json({"members": members, "prompt": _prompt_hash(), "model": config.generation_model.name}).encode()).hexdigest()


def passages_in_order(qdrant: QdrantClient, collection: str) -> list[Any]:
    points, offset = [], None
    while True:
        batch, offset = qdrant.scroll(collection_name=collection, limit=2000, offset=offset, with_payload=True)
        points += batch
        if offset is None:
            break
    return sorted(points, key=lambda p: (p.payload["book_file"], p.payload["section"], p.payload["paragraph"], p.payload["part"]))


def scene_windows(points: list[Any], window: int, stride: int) -> list[list[Any]]:
    """Windows of ``window`` consecutive passages within one section, every ``stride`` passages, the last one ending at
    the section end."""
    windows, start = [], 0
    while start < len(points):
        section = (points[start].payload["book_file"], points[start].payload["section"])
        end = start
        while end < len(points) and (points[end].payload["book_file"], points[end].payload["section"]) == section:
            end += 1
        for first in range(start, end, stride):
            windows.append(points[first:min(first + window, end)])
            if first + window >= end:
                break
        start = end
    return windows


def _summarise(points: list[Any], config: ResolvedPipelineConfig) -> str:
    body = "\n".join(point.payload["text"] for point in points)
    response = requests.post(os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat", json={
        "model": config.generation_model.name, "think": False, "stream": False,
        "messages": [{"role": "system", "content": PROMPT_TEMPLATES["scene_summary_system"]},
                     {"role": "user", "content": f"Book: {points[0].payload['book']}\n\nEXCERPT:\n{body}"}],
        "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 220}}, timeout=(10, 600))
    response.raise_for_status()
    text = response.json().get("message", {}).get("content", "").strip()
    if not text:
        raise RuntimeError("scene summary came back empty")
    return text


def build_scene_index(collection: str, config: ResolvedPipelineConfig, qdrant: QdrantClient, encoder: Any) -> dict[str, Any]:
    """Summarise every window (reusing cached summaries) and index the summaries. Slow on first build: one LLM call
    per window."""
    name = scene_collection(collection, config)
    windows = scene_windows(passages_in_order(qdrant, collection), config.scene_window, config.scene_stride)
    if qdrant.collection_exists(name) and qdrant.count(collection_name=name, exact=True).count == len(windows):
        return {"collection": name, "scenes_indexed": len(windows), "already_indexed": True}
    path = _cache_path()
    cache: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            cache[row["key"]] = row["summary"]
    summaries = []
    with path.open("a", encoding="utf-8") as out:
        for points in windows:
            members = [str(point.id) for point in points]
            key = _summary_key(members, config)
            if key not in cache:
                cache[key] = _summarise(points, config)
                out.write(json.dumps({"key": key, "members": members, "summary": cache[key]}) + "\n")
                out.flush()
            summaries.append((members, cache[key]))
    vectors = encoder.encode([summary for _, summary in summaries], batch_size=64, show_progress_bar=False, normalize_embeddings=True).tolist()
    if qdrant.collection_exists(name):
        qdrant.delete_collection(name)
    qdrant.create_collection(collection_name=name, vectors_config=models.VectorParams(size=len(vectors[0]), distance=models.Distance.COSINE))
    points = [models.PointStruct(id=str(uuid.UUID(_summary_key(members, config)[:32])), vector=vector, payload={"members": members, "summary": summary})
              for (members, summary), vector in zip(summaries, vectors)]
    for start in range(0, len(points), 128):
        qdrant.upsert(collection_name=name, points=points[start:start + 128], wait=True)
    return {"collection": name, "scenes_indexed": len(points), "already_indexed": False}
