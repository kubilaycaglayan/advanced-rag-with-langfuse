"""retrieval / search responsibilities."""
from __future__ import annotations

from app.retrieval.types import Passage

from app.cache.intermediate import cache_value as _cache_value
from app.corpus_profiles import load_profile
from collections import Counter
from collections import defaultdict
from functools import lru_cache
from qdrant_client import QdrantClient
from types import SimpleNamespace
from typing import Any
import json
import math
import os
import re


def qdrant_client() -> QdrantClient:
    return QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"), timeout=30)


def query_points_cached(qdrant: QdrantClient, collection: str, vector: list[float], limit: int,
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


def _name_word_pattern() -> str:
    return load_profile().name_word_pattern


@lru_cache(maxsize=8)
def name_pairs(collection: str) -> tuple[dict[str, tuple[str, int, int]], Counter]:
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


def keywords(text: str) -> list[str]:
    """Content words, lowercased, with a plural -s dropped so "compromises" also matches "compromise"."""
    return [word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")) else word
            for word in re.findall(r"\w+", text.lower()) if word not in _KEYWORD_STOPWORDS]


@lru_cache(maxsize=4)
def keyword_index(collection: str) -> tuple[list[dict[str, Any]], list[Counter], list[int], Counter]:
    """All passages of the collection with their keyword counts, lengths and document frequencies (built once)."""
    rows: list[dict[str, Any]] = []
    offset = None
    while True:
        points, offset = qdrant_client().scroll(collection_name=collection, limit=1000, offset=offset, with_payload=True)
        rows += [dict(point.payload or {}) | {"id": str(point.id)} for point in points]
        if offset is None:
            break
    words = [keywords(row.get("text", "")) for row in rows]
    return rows, [Counter(row_words) for row_words in words], [len(row_words) for row_words in words], Counter(word for row_words in words for word in set(row_words))


_ANCHOR_SKIP = frozenset("what who how when where why which did does is was according for in the a".split())


@lru_cache(maxsize=1)
def entity_cards(path: str) -> dict[str, Any]:
    import json
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data["mentions"] = {card["key"]: card["mentions"] for card in data["cards"]}
    return data


def entity_anchors(question: str, data: dict[str, Any]) -> set[str]:
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


def keyword_search(query: str, collection: str, limit: int, k1: float = 1.2, b: float = 0.75) -> list[Passage]:
    """The passages that best match the query's words by BM25, best first (exact words, which dense search can miss)."""
    def search() -> list[dict[str, Any]]:
        rows, counts, lengths, frequency = keyword_index(collection)
        total, average = len(rows), sum(lengths) / max(len(rows), 1)
        weights = {word: math.log(1 + (total - frequency[word] + 0.5) / (frequency[word] + 0.5))
                   for word in set(keywords(query)) if frequency[word]}
        scores = [(sum(weight * count[word] * (k1 + 1) /
                       (count[word] + k1 * (1 - b + b * length / average))
                       for word, weight in weights.items() if word in count), index)
                  for index, (count, length) in enumerate(zip(counts, lengths))]
        return [dict(rows[index]) | {"keyword_score": score}
                for score, index in sorted(scores, reverse=True)[:limit] if score > 0]

    return _cache_value("search", "keyword", {"query": query, "collection": collection,
                         "limit": limit, "k1": k1, "b": b},
                        input={"query": query, "collection": collection, "limit": limit}, compute=search)


def complete_names(question: str, collection: str, min_count: int = 20, min_share: float = 0.5, min_other_ratio: float = 3.0) -> str:
    """Expand a bare name the books rarely use for that character to the full name (Mikael -> Mikael Blomkvist).

    A word is completed only when one two-word name dominates its pairings and the books use the
    other half of that name at least ``min_other_ratio`` times as often as the word itself.
    """
    def complete() -> str:
        pairs, words = name_pairs(collection)
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


def passage_position(payload: dict[str, Any]) -> tuple:
    return payload.get("book", ""), payload.get("section", ""), payload.get("paragraph", 0), payload.get("part", 0)

