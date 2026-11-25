"""Shared retrieval and query-transformation tools for the v2.16 agent."""
from __future__ import annotations

import contextvars
import json
import math
import os
import re
from types import SimpleNamespace
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any

import requests
from qdrant_client import QdrantClient
from sentence_transformers import CrossEncoder, SentenceTransformer

from qdrant_client import models

from app.corpus_profiles import load_profile, profile_prompt
from app.pipelines.config import ResolvedPipelineConfig
from app.observability import observation as _observe, update as _update
from app.cache.intermediate import cache_value as _cache_value
from app.prompt_templates import PROMPT_TEMPLATES
from app.indexing.scenes import scene_collection


def qdrant_client() -> QdrantClient:
    return QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"), timeout=30)


@lru_cache(maxsize=4)
def _embedder(name: str, revision: str | None = None) -> SentenceTransformer:
    return SentenceTransformer(name, device="cpu", revision=revision)


@lru_cache(maxsize=4)
def _reranker(name: str, revision: str | None = None) -> Any:
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


def _encode_query(text: str, model: str, revision: str | None = None) -> list[float]:
    return _cache_value("embedding", "query", {"text": text, "model": model, "revision": revision,
                         "normalize": True}, input={"text": text, "model": model, "revision": revision},
                        compute=lambda: _embedder(model, revision).encode(
                            text, normalize_embeddings=True, show_progress_bar=False).tolist())


def _query_points_cached(qdrant: QdrantClient, collection: str, vector: list[float], limit: int,
                         query_text: str) -> list[Any]:
    def fetch() -> list[dict[str, Any]]:
        points = qdrant.query_points(collection_name=collection, query=vector, limit=limit,
                                     with_payload=True).points
        return [{"id": str(point.id), "payload": dict(point.payload or {}),
                 "score": float(point.score)} for point in points]

    records = _cache_value("search", "dense", {"collection": collection, "vector": vector, "limit": limit},
                           input={"collection": collection, "query": query_text, "limit": limit},
                           compute=fetch)
    return [SimpleNamespace(id=row["id"], payload=row["payload"], score=row["score"]) for row in records]


def _ollama(messages: list[dict[str, str]], model: str, budgets: tuple[int, ...],
            temperature: float = 0, context_length: int = 8192, *,
            name: str = "answer generation") -> str:
    """Non-streaming local generation for query transformations and scene selection."""
    base = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    keep_alive: str | int = os.getenv("OLLAMA_KEEP_ALIVE", "-1")
    if keep_alive.lstrip("-").isdigit():
        keep_alive = int(keep_alive)
    last_error: Exception | None = None
    with _observe(name, as_type="generation", input=messages, model=model) as obs:
        for budget in budgets:
            try:
                response = requests.post(f"{base}/api/chat", json={
                    "model": model, "keep_alive": keep_alive, "messages": messages,
                    "think": False, "stream": False,
                    "options": {"temperature": temperature, "num_ctx": context_length, "num_predict": budget},
                }, timeout=(10, 900), stream=False)
                response.raise_for_status()
                data = response.json()
                message = data.get("message", {})
                text, thinking = message.get("content", "").strip(), message.get("thinking")
                if text:
                    _update(obs, output=text,
                            usage_details={"input": data.get("prompt_eval_count"), "output": data.get("eval_count")},
                            **({"metadata": {"thinking": thinking}} if thinking else {}))
                    return text
            except requests.RequestException as exc:
                last_error = exc
                break
        raise RuntimeError(f"Ollama request failed or returned empty content: {last_error or 'empty response'}")


def _transform(question: str, config: ResolvedPipelineConfig) -> tuple[str | None, list[str], str | None]:
    mode = config.retrieval_mode

    def transform_cache_key(operation: str) -> dict[str, Any]:
        return {"query": question, "model": config.generation_model.name,
                "model_revision": config.generation_model.revision,
                "temperature": config.generation.temperature,
                "context_length": config.generation.context_length,
                "output_budgets": list(config.generation.output_budgets), "operation": operation}

    def hyde() -> str:
        with _observe("HyDE transformation", input=question) as obs:
            messages = [
                {"role": "system", "content": profile_prompt("hyde_system", PROMPT_TEMPLATES["hyde_system"])}, {"role": "user", "content": question}]
            hypothetical = _cache_value("query", "hyde", transform_cache_key("hyde"),
                input={"query": question, "operation": "hyde"},
                compute=lambda: _ollama(messages, config.generation_model.name, config.generation.output_budgets,
                    config.generation.temperature, config.generation.context_length,
                    name="hypothetical document generation"))
            _update(obs, output=hypothetical)
        return hypothetical

    def expansion() -> list[str]:
        with _observe("query expansion", input=question) as obs:
            # Prompts may reference {{expansion_count}}; templates without it ignore the value.
            messages = [
                {"role": "system", "content": profile_prompt("query_expansion_system", PROMPT_TEMPLATES["query_expansion_system"]).replace("{{expansion_count}}", str(config.expansion_count))},
                {"role": "user", "content": question}]
            raw = _cache_value("query", "expansion", transform_cache_key("expansion"),
                input={"query": question, "operation": "expansion"},
                compute=lambda: _ollama(messages, config.generation_model.name, config.generation.output_budgets,
                    config.generation.temperature, config.generation.context_length,
                    name="literary query generation"))
            _update(obs, output=raw)
        alternatives = list(dict.fromkeys(line.strip().lstrip("-•0123456789. )") for line in raw.splitlines() if line.strip()))
        alternatives = [q for q in alternatives if q and q.casefold() != question.casefold()][:config.expansion_count]
        if len(alternatives) != config.expansion_count:
            raise ValueError(f"query expansion must return {config.expansion_count} distinct alternative queries")
        return alternatives

    def grammar() -> str:
        with _observe("grammar correction", input=question) as obs:
            messages = [
                {"role": "system", "content": profile_prompt("grammar_system", PROMPT_TEMPLATES["grammar_system"])}, {"role": "user", "content": question}]
            corrected = _cache_value("query", "grammar", transform_cache_key("grammar"),
                input={"query": question, "operation": "grammar"},
                compute=lambda: _ollama(messages, config.generation_model.name, config.generation.output_budgets,
                    config.generation.temperature, config.generation.context_length,
                    name="grammar corrected query generation"))
            _update(obs, output=corrected)
        return corrected

    # hyde=false keeps every other step of the mode and only drops the hypothetical document.
    steps = {"hypothetical": hyde if config.hyde and mode in {"hyde", "hyde_query_expansion", "full"} else None,
             "alternatives": expansion if mode in {"query_expansion", "hyde_query_expansion", "full"} else None,
             "corrected": grammar if mode == "full" else None}
    steps = {key: step for key, step in steps.items() if step}
    if config.parallel_transformations and len(steps) > 1:
        # The rewrites are independent requests; Ollama answers them together when OLLAMA_NUM_PARALLEL allows it.
        # Each runs in a copy of this context, so its Langfuse spans stay under the current trace.
        with ThreadPoolExecutor(max_workers=len(steps)) as pool:
            futures = {key: pool.submit(contextvars.copy_context().run, step) for key, step in steps.items()}
            done = {key: future.result() for key, future in futures.items()}
    else:
        done = {key: step() for key, step in steps.items()}
    return done.get("hypothetical"), done.get("alternatives", []), done.get("corrected")


def _name_word_pattern() -> str:
    return load_profile().name_word_pattern


@lru_cache(maxsize=8)
def _name_pairs(collection: str) -> tuple[dict[str, tuple[str, int, int]], Counter]:
    """Map each capitalized word to its most frequent two-word name in the indexed passages.

    Returns ({word: (full name, count of that name, count of all names containing the word)}, word counts).
    """
    by_word: dict[str, Counter] = defaultdict(Counter)
    words: Counter = Counter()
    offset = None
    while True:
        points, offset = qdrant_client().scroll(collection_name=collection, limit=1000, offset=offset, with_payload=["text"])
        for point in points:
            text = (point.payload or {}).get("text", "")
            words.update(re.findall(rf"\b{_name_word_pattern()}\b", text))
            for first, last in re.findall(rf"\b({_name_word_pattern()}) ({_name_word_pattern()})\b", text):
                by_word[first][f"{first} {last}"] += 1
                by_word[last][f"{first} {last}"] += 1
        if offset is None:
            break
    return {word: (*names.most_common(1)[0], sum(names.values())) for word, names in by_word.items()}, words


_KEYWORD_STOPWORDS = frozenset("a an the of to in on and or is was were be been are did does do how what who whom why when where which "
                               "that this with for by at from as her his she he it its their they them".split())


def _keywords(text: str) -> list[str]:
    """Content words, lowercased, with a plural -s dropped so "compromises" also matches "compromise"."""
    return [word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")) else word
            for word in re.findall(r"\w+", text.lower()) if word not in _KEYWORD_STOPWORDS]


@lru_cache(maxsize=4)
def _keyword_index(collection: str) -> tuple[list[dict[str, Any]], list[Counter], list[int], Counter]:
    """All passages of the collection with their keyword counts, lengths and document frequencies (built once)."""
    rows: list[dict[str, Any]] = []
    offset = None
    while True:
        points, offset = qdrant_client().scroll(collection_name=collection, limit=1000, offset=offset, with_payload=True)
        rows += [dict(point.payload or {}) | {"id": str(point.id)} for point in points]
        if offset is None:
            break
    words = [_keywords(row.get("text", "")) for row in rows]
    return rows, [Counter(row_words) for row_words in words], [len(row_words) for row_words in words], Counter(word for row_words in words for word in set(row_words))


# Other names of a person, from the entity cards /index builds (app/entities.py).
_ANCHOR_SKIP = frozenset("what who how when where why which did does is was according for in the a".split())


@lru_cache(maxsize=1)
def _entity_cards(path: str) -> dict[str, Any]:
    import json
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data["mentions"] = {card["key"]: card["mentions"] for card in data["cards"]}
    return data


def _entity_anchors(question: str, data: dict[str, Any]) -> set[str]:
    """Entities the question names: a full name, or one word of the most-mentioned entity that contains it."""
    found = set()
    for name in re.findall(r"[A-ZÅÄÖ][\wåäöé]+(?:\s[A-ZÅÄÖ][\wåäöé]+)*", question):
        # A capitalised question word is not part of the name after it ("How Gottfried died?", "Did Salander ...").
        words = name.split()
        while len(words) > 1 and words[0].casefold() in _ANCHOR_SKIP:
            words.pop(0)
        key = re.sub(r"[’']s$", "", " ".join(words)).casefold()
        if key in _ANCHOR_SKIP:
            continue
        key = data["alias"].get(key, key)
        matches = [key] if key in data["mentions"] else [other for other in data["mentions"] if key in other.split()]
        if matches:
            found.add(max(matches, key=data["mentions"].get))
    return found


# Entity matrix: rows are entities, columns kinds of link (the edge's type: nickname, vehicle, tattoo, ...), cells edges.
# "in the book(s)" and similar only scope the question; the words below say nothing about which rows or cells.


def _keyword_search(query: str, collection: str, limit: int, k1: float = 1.2, b: float = 0.75) -> list[dict[str, Any]]:
    """The passages that best match the query's words by BM25, best first (exact words, which dense search can miss)."""
    def search() -> list[dict[str, Any]]:
        rows, counts, lengths, frequency = _keyword_index(collection)
        total, average = len(rows), sum(lengths) / max(len(rows), 1)
        weights = {word: math.log(1 + (total - frequency[word] + 0.5) / (frequency[word] + 0.5))
                   for word in set(_keywords(query)) if frequency[word]}
        scores = [(sum(weight * count[word] * (k1 + 1) /
                       (count[word] + k1 * (1 - b + b * length / average))
                       for word, weight in weights.items() if word in count), index)
                  for index, (count, length) in enumerate(zip(counts, lengths))]
        return [dict(rows[index]) | {"keyword_score": score}
                for score, index in sorted(scores, reverse=True)[:limit] if score > 0]

    return _cache_value("search", "keyword", {"query": query, "collection": collection,
                         "limit": limit, "k1": k1, "b": b},
                        input={"query": query, "collection": collection, "limit": limit}, compute=search)


def _complete_names(question: str, collection: str, min_count: int = 20, min_share: float = 0.5, min_other_ratio: float = 3.0) -> str:
    """Expand a bare name the books rarely use for that character to the full name (Mikael -> Mikael Blomkvist).

    A word is completed only when one two-word name dominates its pairings and the books use the
    other half of that name at least ``min_other_ratio`` times as often as the word itself.
    """
    def complete() -> str:
        pairs, words = _name_pairs(collection)
        completed = question
        for word in dict.fromkeys(re.findall(rf"\b{_name_word_pattern()}\b", question)):
            if word not in pairs:
                continue
            full, count, total = pairs[word]
            other = " ".join(part for part in full.split() if part != word)
            if (count < min_count or count / total < min_share or other in question
                    or words[other] < min_other_ratio * words[word]):
                continue
            completed = re.sub(rf"\b{word}\b", full, completed, count=1)
        return completed

    return _cache_value("query", "name_completion", {
        "query": question, "collection": collection, "min_count": min_count,
        "min_share": min_share, "min_other_ratio": min_other_ratio,
    }, input={"query": question, "operation": "name_completion"}, compute=complete)


def _prompted(system: str, user: str, config: ResolvedPipelineConfig, name: str) -> str:
    """One generation-model request using the active corpus's local template."""
    messages = [{"role": "system", "content": profile_prompt(system, PROMPT_TEMPLATES[system])},
                {"role": "user", "content": user}]
    return _ollama(messages, config.generation_model.name, config.generation.output_budgets,
                   config.generation.temperature, config.generation.context_length, name=name)


def _passage_position(payload: dict[str, Any]) -> tuple:
    return payload.get("book", ""), payload.get("section", ""), payload.get("paragraph", 0), payload.get("part", 0)


def _moment_scene_hits(question: str, config: ResolvedPipelineConfig, collection: str, qdrant: QdrantClient,
                       evidence: list[dict[str, Any]], present: set[str]
                       ) -> tuple[list[dict[str, Any]], str]:
    """Passages of the scene that shows the moment the question asks about ("... when they first met in her house"),
    chosen by the generation model among the scenes whose summaries best match that moment. Returns them and the moment.

    A detail asked about at a moment (what someone wore, said or held) is often in a passage that names neither the
    people nor the moment, and the whole question matches the moment's scene poorly because it also describes the
    detail. So the moment is written out on its own and searched for, and the model reads the summaries found, in
    reading order, to choose (the cross-encoder cannot tell which of several similar scenes is the first one). The
    chosen window and the window that continues it are added, so a detail just past the window's end is kept. Nothing
    is added when the question names no moment, no summary shows it, or the evidence already holds a passage of it.
    """
    with _observe("moment description", input=question) as obs:
        reply = _prompted("scene_moment_system", question, config, "moment description")
        # The reply also states the detail asked for (DETAIL: ...); asking for it separately keeps it out of the moment.
        moment = next((line.partition(":")[2].strip().strip('"') for line in reply.splitlines()
                       if line.strip().upper().startswith("MOMENT:")), "")
        if moment.casefold().rstrip(".") == "none":
            moment = ""
        # Summaries name people the way the books do, so a bare first name is completed as in retrieval.
        if moment and config.name_completion:
            moment = _complete_names(moment, collection)
        _update(obs, output=moment or None)
    if not moment:
        return [], moment
    name = scene_collection(collection, config)
    vector = _encode_query(moment, config.embedding_model.name, config.embedding_model.revision)
    found = _query_points_cached(qdrant, name, vector, config.scene_search_hits, moment)
    if not found:
        return [], moment
    first = {str(point.id): dict(point.payload or {}) for point in qdrant.retrieve(
        collection_name=collection, ids=[scene.payload["members"][0] for scene in found], with_payload=True)}
    found.sort(key=lambda scene: _passage_position(first[scene.payload["members"][0]]))
    listing = "\n\n".join(f"[{n}] {first[scene.payload['members'][0]].get('book')}, {first[scene.payload['members'][0]].get('chapter') or 'chapter unknown'}: "
                          f"{scene.payload['summary']}" for n, scene in enumerate(found, 1))
    with _observe("moment scene choice", input={"moment": moment, "scenes": listing}) as obs:
        reply = _prompted("scene_select_system", f"Moment: {moment}\n\nScenes:\n{listing}", config,
                          "moment scene choice")
        number = re.fullmatch(r"\W*(\d+)\W*", reply)
        chosen = found[int(number[1]) - 1] if number and 1 <= int(number[1]) <= len(found) else None
        _update(obs, output=chosen.payload["summary"] if chosen else None)
    if chosen is None:
        return [], moment
    # The windows holding the chosen window's last passage are that window and the one that continues it.
    following, _ = qdrant.scroll(collection_name=name, limit=100, with_payload=True, scroll_filter=models.Filter(
        must=[models.FieldCondition(key="members", match=models.MatchAny(any=[chosen.payload["members"][-1]]))]))
    span = list(dict.fromkeys([*chosen.payload["members"], *(member for scene in following for member in scene.payload["members"])]))
    if set(span) & {row["id"] for row in evidence}:
        return [], moment
    rows = sorted((dict(point.payload or {}) | {"id": str(point.id), "scene_hit": True, "moment_hit": True, "moment": moment,
                                                "scene_summary": chosen.payload["summary"]}
                   for point in qdrant.retrieve(collection_name=collection, ids=[member for member in span if member not in present], with_payload=True)),
                  key=_passage_position)
    for row, score in zip(rows, _reranker(config.reranker_model.name, config.reranker_model.revision).predict(
            [(question, row["text"]) for row in rows], show_progress_bar=False)):
        row["rerank_score"] = float(score)
    return rows, moment
