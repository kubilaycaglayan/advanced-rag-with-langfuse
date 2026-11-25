"""agent / tools / search responsibilities."""
from __future__ import annotations

from app.agent.protocol import _int
from app.agent.state import AgentState
from app.context.citations import _passage
from app.indexing.scenes import scene_collection
from app.retrieval.entities import name_hints
from app.models.retrieval import encode_query
from app.retrieval.search import keyword_search
from app.retrieval.search import query_points_cached
from app.models.retrieval import reranker
from app.retrieval.queries import transform_query
from app.retrieval.search import qdrant_client
from typing import Any


def _semantic_rows(state: "AgentState", query: str, k: int) -> list[dict[str, Any]]:
    """Dense search plus cross-encoder rerank; rows carry the full passage id."""
    config = state.config
    vector = encode_query(query, config.embedding_model.name, config.embedding_model.revision)
    points = query_points_cached(qdrant_client(), state.collection, vector,
                                  max(30, k * 5), query)
    rows = [dict(point.payload or {}) | {"id": str(point.id)} for point in points]
    if not rows:
        return []
    scores = reranker(config.reranker_model.name, config.reranker_model.revision).predict(
        [(query, row["text"]) for row in rows], show_progress_bar=False)
    for row, score in zip(rows, scores):
        row["score"] = float(score)
    return sorted(rows, key=lambda row: row["score"], reverse=True)[:k]


def _scene_points(state: "AgentState", query: str, k: int) -> tuple[list[tuple[Any, float]], str]:
    """Scene search: points and rerank scores, or an error string when the scene index is missing."""
    config = state.config
    name = scene_collection(state.collection, config)
    qdrant = qdrant_client()
    if not qdrant.collection_exists(name):
        return [], "the scene index is not built for this collection"
    vector = encode_query(query, config.embedding_model.name, config.embedding_model.revision)
    points = query_points_cached(qdrant, name, vector,
                                  max(state.settings.scene_candidate_count, k * 4), query)
    if not points:
        return [], ""
    scores = reranker(config.reranker_model.name, config.reranker_model.revision).predict(
        [(query, point.payload["summary"]) for point in points], show_progress_bar=False)
    ranked = sorted(zip(points, (float(score) for score in scores)), key=lambda pair: pair[1], reverse=True)
    return ranked[:k], ""


def _tool_semantic_search(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    k = _int(args, "k", 5, 1, 10)
    rows = _semantic_rows(state, query, k)
    if not rows:
        return {"query": query, "hits": []}
    state.remember(rows, query=query)
    return {"query": query, "hits": [_passage(row, state.settings.snippet_chars) for row in rows],
            "name_hints": name_hints(state.collection, query)}


def _tool_keyword_search(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    k = _int(args, "k", 5, 1, 10)
    rows = keyword_search(query, state.collection, k)
    if not rows:
        return {"query": query, "hits": [], "note": "no passage shares a content word with this query"}
    for row in rows:
        row["score"] = row["keyword_score"]
    state.remember(rows, query=query)
    return {"query": query, "hits": [_passage(row, state.settings.snippet_chars) for row in rows],
            "name_hints": name_hints(state.collection, query)}


def _tool_expand_query(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or state.question).strip()
    hypothetical, alternatives, corrected = transform_query(query, state.config)
    return {"query": query, "hypothetical_document": hypothetical, "alternative_phrasings": alternatives,
            "grammar_corrected": corrected,
            "note": "search these phrasings with semantic_search; they are not evidence"}
