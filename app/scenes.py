"""Scene summaries: a second index of LLM summaries over windows of consecutive passages.

Some answers are spread over a scene whose passages never name the people involved (dialogue such as "you will
..."), so neither dense search nor the cross-encoder can tie them to a question. Each window of ``scene_window``
consecutive passages of one EPUB section (step ``scene_stride``) is summarised once, naming who does what; the
summaries are embedded into their own collection and point back to their passages.

The summarising model sometimes writes names the excerpt does not use: a first name it knows from the books, a wrong
one ("Martin" for Mikael Blomkvist) or an invented person. Each summary is checked against the names in its excerpt;
a name the excerpt writes differently is replaced by the excerpt's form, and a summary with a name that cannot be
traced to the excerpt is written again with the excerpt's names listed.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import uuid
from collections import Counter, defaultdict
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


_NAME = r"[A-ZÅÄÖ][a-zåäöéü]{2,}(?:-[A-ZÅÄÖ][a-zåäöéü]+)?"
# "In Chapter 5 of *The Girl ...*," and similar openings: the model is never told the chapter, so drop the reference.
_META = re.compile(r"^\s*In (?:Chapter \d+(?: of)? )?\*?The Girl[^,]*?,\s*|^\s*In Chapter \d+,\s*")


class NameLexicon:
    """Which capitalised words are names in the books, and the two-word name each one is most often part of."""

    def __init__(self, texts: list[str]):
        corpus = "\n".join(texts)
        self.capital = Counter(re.findall(rf"\b{_NAME}\b", corpus))
        self.mid = Counter(re.findall(rf"(?<=[a-zåäöé,] )({_NAME})\b", corpus))
        self.lower = Counter(re.findall(r"\b[a-zåäöéü]+\b", corpus))
        names: dict[str, Counter] = defaultdict(Counter)
        for first, last in re.findall(rf"\b({_NAME}) ({_NAME})\b", corpus):
            names[first][last] += 1
            names[last][first] += 1
        self.partner = {word: other.most_common(1)[0][0] for word, other in names.items()
                        if other.most_common(1)[0][1] >= 20 and other.most_common(1)[0][1] >= 0.5 * sum(other.values())}

    def is_name(self, word: str) -> bool:
        # Capitalised mid-sentence more often than written in lower case, or not in the books at all (invented).
        unseen = not self.capital[word] and not self.lower[word.lower()]
        return unseen or (self.mid[word] >= 3 and self.lower[word.lower()] < self.capital[word])

    def names(self, text: str) -> list[str]:
        return list(dict.fromkeys(word for word in re.findall(rf"\b{_NAME}\b", text) if self.is_name(word)))


def foreign_names(summary: str, excerpt: str, lexicon: NameLexicon) -> list[str]:
    """Names in the summary that the excerpt does not contain."""
    present = set(re.findall(rf"\b{_NAME}\b", excerpt))
    return [name for name in lexicon.names(summary) if name not in present]


def repair_summary(summary: str, excerpt: str, lexicon: NameLexicon) -> tuple[str, list[str]]:
    """Write names as the excerpt does; returns the summary and the names that could not be traced to the excerpt."""
    present = set(re.findall(rf"\b{_NAME}\b", excerpt))
    text = _META.sub("In the excerpt, ", summary, count=1)

    def two_words(match: re.Match) -> str:
        first, last = match[1], match[2]
        if lexicon.is_name(first) and lexicon.is_name(last):
            if last in present and first not in present:
                return last
            if first in present and last not in present:
                return first
        return match[0]

    text = re.sub(rf"\b({_NAME}) ({_NAME})\b", two_words, text)
    for name in foreign_names(text, excerpt, lexicon):
        # A bare first name the excerpt writes as the other half of that name ("Lisbeth" -> "Salander"), or a misspelt
        # name of the excerpt ("Wadensjö" -> "Wadensjöö").
        close = difflib.get_close_matches(name, [word for word in present if lexicon.is_name(word)], n=1, cutoff=0.8)
        fix = lexicon.partner.get(name) if lexicon.partner.get(name) in present else (close[0] if close else None)
        if fix:
            text = re.sub(rf"\b{name}\b", fix, text)
    text = re.sub(rf"\b({_NAME}) \1\b", r"\1", text)
    return text, foreign_names(text, excerpt, lexicon)


def _summarise(points: list[Any], config: ResolvedPipelineConfig, names: list[str] | None = None) -> str:
    body = "\n".join(point.payload["text"] for point in points)
    listed = f"Names used in the excerpt (use only these): {', '.join(names) or 'none'}\n\n" if names is not None else ""
    response = requests.post(os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat", json={
        "model": config.generation_model.name, "think": False, "stream": False,
        "messages": [{"role": "system", "content": PROMPT_TEMPLATES["scene_summary_system"]},
                     {"role": "user", "content": f"Book: {points[0].payload['book']}\n\n{listed}EXCERPT:\n{body}"}],
        "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 220}}, timeout=(10, 600))
    response.raise_for_status()
    text = response.json().get("message", {}).get("content", "").strip()
    if not text:
        raise RuntimeError("scene summary came back empty")
    return text


def checked_summary(points: list[Any], config: ResolvedPipelineConfig, lexicon: NameLexicon, summary: str | None = None,
                    retries: int = 2) -> tuple[str, list[str]]:
    """Summarise (or take ``summary``), repair its names, and write it again with the excerpt's names listed while a
    name cannot be traced to the excerpt. Returns the best summary and its untraced names."""
    excerpt = "\n".join(point.payload["text"] for point in points)
    best = repair_summary(summary if summary is not None else _summarise(points, config), excerpt, lexicon)
    for _ in range(retries):
        if not best[1]:
            break
        again = repair_summary(_summarise(points, config, lexicon.names(excerpt)), excerpt, lexicon)
        if len(again[1]) < len(best[1]):
            best = again
    return best


def build_scene_index(collection: str, config: ResolvedPipelineConfig, qdrant: QdrantClient, encoder: Any) -> dict[str, Any]:
    """Summarise every window (reusing cached summaries) and index the summaries. Slow on first build: one LLM call
    per window."""
    name = scene_collection(collection, config)
    passages = passages_in_order(qdrant, collection)
    windows = scene_windows(passages, config.scene_window, config.scene_stride)
    cache = _read_cache()
    lexicon: NameLexicon | None = None
    summaries = []
    with _cache_path().open("a", encoding="utf-8") as out:
        for points in windows:
            members = [str(point.id) for point in points]
            key = _summary_key(members, config)
            if key not in cache:
                lexicon = lexicon or NameLexicon([point.payload["text"] for point in passages])
                summary, untraced = checked_summary(points, config, lexicon)
                cache[key] = {"key": key, "members": members, "summary": summary, "checked": True, "untraced": untraced}
                out.write(json.dumps(cache[key]) + "\n")
                out.flush()
            summaries.append((members, cache[key]["summary"]))
    if qdrant.collection_exists(name) and qdrant.count(collection_name=name, exact=True).count == len(windows):
        indexed, offset = {}, None
        while True:
            batch, offset = qdrant.scroll(collection_name=name, limit=2000, offset=offset, with_payload=True)
            indexed.update({tuple(point.payload["members"]): point.payload["summary"] for point in batch})
            if offset is None:
                break
        if all(indexed.get(tuple(members)) == summary for members, summary in summaries):
            return {"collection": name, "scenes_indexed": len(windows), "already_indexed": True}
    vectors = encoder.encode([summary for _, summary in summaries], batch_size=64, show_progress_bar=False, normalize_embeddings=True).tolist()
    if qdrant.collection_exists(name):
        qdrant.delete_collection(name)
    qdrant.create_collection(collection_name=name, vectors_config=models.VectorParams(size=len(vectors[0]), distance=models.Distance.COSINE))
    points = [models.PointStruct(id=str(uuid.UUID(_summary_key(members, config)[:32])), vector=vector, payload={"members": members, "summary": summary})
              for (members, summary), vector in zip(summaries, vectors)]
    for start in range(0, len(points), 128):
        qdrant.upsert(collection_name=name, points=points[start:start + 128], wait=True)
    return {"collection": name, "scenes_indexed": len(points), "already_indexed": False}


def _read_cache() -> dict[str, dict[str, Any]]:
    """The cached summaries, later lines overriding earlier ones."""
    path = _cache_path()
    rows: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            rows[row["key"]] = row
    return rows


def repair_cache(collection: str, config: ResolvedPipelineConfig, qdrant: QdrantClient) -> dict[str, int]:
    """Check and repair the names of every cached summary of this index that has not been checked yet."""
    passages = passages_in_order(qdrant, collection)
    lexicon = NameLexicon([point.payload["text"] for point in passages])
    cache = _read_cache()
    stats = Counter()
    with _cache_path().open("a", encoding="utf-8") as out:
        for points in scene_windows(passages, config.scene_window, config.scene_stride):
            key = _summary_key([str(point.id) for point in points], config)
            row = cache.get(key)
            if row is None or row.get("checked"):
                continue
            summary, untraced = checked_summary(points, config, lexicon, row["summary"])
            stats["checked"] += 1
            stats["changed"] += summary != row["summary"]
            stats["untraced"] += bool(untraced)
            out.write(json.dumps(row | {"summary": summary, "checked": True, "untraced": untraced}) + "\n")
            out.flush()
    return dict(stats)


if __name__ == "__main__":
    try:
        from .indexer import build_index, index_identity
        from .resolved_config import resolve_pipeline_model_identities
    except ImportError:
        from indexer import build_index, index_identity
        from resolved_config import resolve_pipeline_model_identities
    parser = argparse.ArgumentParser(description="Check and repair names in cached scene summaries, then rebuild the scene index")
    parser.add_argument("--config", type=Path, help="JSON resolved pipeline config")
    args = parser.parse_args()
    run_config = resolve_pipeline_model_identities(ResolvedPipelineConfig.from_mapping(json.loads(args.config.read_text()) if args.config else {}))
    client = QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"), timeout=30)
    print(repair_cache(index_identity(run_config)[0], run_config, client))
    print(build_index(run_config, client))
