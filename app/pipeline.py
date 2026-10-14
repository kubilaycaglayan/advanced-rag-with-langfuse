"""Reusable Millennium RAG answer pipeline shared by HTTP and experiments."""
from __future__ import annotations

import os
import re
import time
from functools import lru_cache
from typing import Any

import requests
from qdrant_client import QdrantClient
from sentence_transformers import CrossEncoder, SentenceTransformer

try:
    from .resolved_config import ResolvedPipelineConfig
    from .observability import observation as _observe, update as _update
    from .prompt_templates import PROMPT_HASHES, PROMPT_TEMPLATES
except ImportError:
    from resolved_config import ResolvedPipelineConfig
    from observability import observation as _observe, update as _update
    from prompt_templates import PROMPT_HASHES, PROMPT_TEMPLATES


def qdrant_client() -> QdrantClient:
    return QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"), timeout=30)


@lru_cache(maxsize=4)
def _embedder(name: str, revision: str | None = None) -> SentenceTransformer:
    return SentenceTransformer(name, device="cpu", revision=revision)


@lru_cache(maxsize=4)
def _reranker(name: str, revision: str | None = None) -> CrossEncoder:
    return CrossEncoder(name, device="cpu", revision=revision)


def _ollama(messages: list[dict[str, str]], model: str, budgets: tuple[int, ...], temperature: float = 0, context_length: int = 8192, *, prompt: Any = None, name: str = "answer generation") -> str:
    base = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    keep_alive: str | int = os.getenv("OLLAMA_KEEP_ALIVE", "-1")
    if keep_alive.lstrip("-").isdigit():
        keep_alive = int(keep_alive)
    last_error: Exception | None = None
    with _observe(name, as_type="generation", input=messages, model=model, prompt=prompt) as obs:
        for budget in budgets:
            try:
                response = requests.post(f"{base}/api/chat", json={
                    "model": model, "keep_alive": keep_alive, "messages": messages,
                    "think": False, "stream": False,
                    "options": {"temperature": temperature, "num_ctx": context_length, "num_predict": budget},
                }, timeout=(10, 900))
                response.raise_for_status()
                data = response.json()
                text = data.get("message", {}).get("content", "").strip()
                if text:
                    _update(obs, output=text, usage_details={"input": data.get("prompt_eval_count"), "output": data.get("eval_count")})
                    return text
            except requests.RequestException as exc:
                last_error = exc
                break
        raise RuntimeError(f"Ollama request failed or returned empty content: {last_error or 'empty response'}")


def _transform(question: str, config: ResolvedPipelineConfig, prompt_bundle: dict[str, Any] | None = None) -> tuple[str | None, list[str], str | None]:
    mode = config.retrieval_mode
    hypothetical = None
    corrected = None
    alternatives: list[str] = []
    if mode in {"hyde", "hyde_query_expansion", "full"}:
        with _observe("HyDE transformation", input=question) as obs:
            messages = (prompt_bundle["rag-hyde"]["client"].compile(question=question) if prompt_bundle else [
                {"role": "system", "content": PROMPT_TEMPLATES["hyde_system"]}, {"role": "user", "content": question}])
            hypothetical = _ollama(messages, config.generation_model.name, config.generation.output_budgets, config.generation.temperature, config.generation.context_length,
                                   prompt=prompt_bundle["rag-hyde"]["client"] if prompt_bundle else None, name="hypothetical document generation")
            _update(obs, output=hypothetical)
    if mode in {"query_expansion", "hyde_query_expansion", "full"}:
        with _observe("query expansion", input=question) as obs:
            # Prompts may reference {{expansion_count}}; templates without it ignore the value.
            messages = (prompt_bundle["rag-query-expansion"]["client"].compile(question=question, expansion_count=str(config.expansion_count)) if prompt_bundle else [
                {"role": "system", "content": PROMPT_TEMPLATES["query_expansion_system"].replace("{{expansion_count}}", str(config.expansion_count))},
                {"role": "user", "content": question}])
            raw = _ollama(messages, config.generation_model.name, config.generation.output_budgets, config.generation.temperature, config.generation.context_length,
                          prompt=prompt_bundle["rag-query-expansion"]["client"] if prompt_bundle else None, name="literary query generation")
            _update(obs, output=raw)
        alternatives = list(dict.fromkeys(line.strip().lstrip("-•0123456789. )") for line in raw.splitlines() if line.strip()))
        alternatives = [q for q in alternatives if q and q.casefold() != question.casefold()][:config.expansion_count]
        if len(alternatives) != config.expansion_count:
            raise ValueError(f"query expansion must return {config.expansion_count} distinct alternative queries")
    if mode == "full":
        with _observe("grammar correction", input=question) as obs:
            messages = (prompt_bundle["rag-grammar-correction"]["client"].compile(question=question) if prompt_bundle else [
                {"role": "system", "content": PROMPT_TEMPLATES["grammar_system"]}, {"role": "user", "content": question}])
            corrected = _ollama(messages, config.generation_model.name, config.generation.output_budgets,
                                config.generation.temperature, config.generation.context_length,
                                prompt=prompt_bundle["rag-grammar-correction"]["client"] if prompt_bundle else None, name="grammar corrected query generation")
            _update(obs, output=corrected)
    return hypothetical, alternatives, corrected


def _rrf(rankings: list[list[Any]], limit: int, k: int) -> list[dict[str, Any]]:
    fused: dict[str, dict[str, Any]] = {}
    for ranking in rankings:
        for rank, point in enumerate(ranking, 1):
            key = str(point.id)
            row = fused.setdefault(key, dict(point.payload or {}) | {"id": key, "rrf_score": 0.0, "retrieval_ranks": []})
            row["rrf_score"] += 1 / (k + rank)
            row["retrieval_ranks"].append(rank)
    return sorted(fused.values(), key=lambda row: row["rrf_score"], reverse=True)[:limit]


def _format_evidence(rows: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"[E{i}] Book: {row.get('book')} | Chapter: {row.get('chapter') or 'unavailable'} | Paragraph: {row.get('paragraph', 'unavailable')} | Page: {row.get('page') or 'unavailable'}\nPassage: {row['text']}"
        for i, row in enumerate(rows, 1)
    )


def run_pipeline(question: str, config: ResolvedPipelineConfig | None = None, *, collection: str | None = None,
                 prompt_bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run retrieve, rerank and answer. Reference answers are never accepted here."""
    config = config or ResolvedPipelineConfig()
    if not question.strip():
        raise ValueError("question must not be blank")
    if not collection:
        raise ValueError("an explicitly validated index collection is required")
    started = time.perf_counter()
    timings: dict[str, float] = {}
    qdrant = qdrant_client()
    if not qdrant.collection_exists(collection):
        raise RuntimeError(f"index collection {collection!r} does not exist")

    stage = time.perf_counter()
    hypothetical, alternatives, corrected = _transform(question, config, prompt_bundle)
    timings["transformation_seconds"] = round(time.perf_counter() - stage, 4)
    queries = [question] + ([hypothetical] if hypothetical else []) + alternatives + ([corrected] if corrected else [])
    rankings = []
    stage = time.perf_counter()
    vector_search_timings: list[float] = []
    with _observe("candidate retrieval", input={"question": question, "queries": queries}) as obs:
        query_names = ["original question"] + (["hypothetical document"] if hypothetical else []) + [f"literary alternative {i}" for i in range(1, len(alternatives) + 1)] + (["grammar corrected question"] if corrected else [])
        for query, query_name in zip(queries, query_names):
            search_started = time.perf_counter()
            with _observe(f"search: {query_name}", as_type="retriever", input=query) as search_obs:
                with _observe("query embedding", as_type="embedding", input=query, model=config.embedding_model.name) as embedding_obs:
                    vector = _embedder(config.embedding_model.name, config.embedding_model.revision).encode(query, normalize_embeddings=True).tolist()
                    _update(embedding_obs, output={"dimensions": len(vector)})
                points = qdrant.query_points(collection_name=collection, query=vector, limit=config.candidate_count, with_payload=True).points
                rankings.append(points)
                _update(search_obs, output={"hits": [{"id": str(point.id), "score": float(point.score), "payload": dict(point.payload or {})} for point in points]})
            vector_search_timings.append(round(time.perf_counter() - search_started, 4))
        if config.retrieval_mode == "baseline":
            candidates = [dict(p.payload or {}) | {"id": str(p.id), "similarity": float(p.score)} for p in rankings[0]]
        else:
            with _observe("RRF candidate merge", input={"ranking_count": len(rankings), "rrf_constant": config.rrf_constant}) as merge_obs:
                candidates = _rrf(rankings, config.candidate_count, config.rrf_constant)
                _update(merge_obs, output=candidates)
        _update(obs, output={"candidate_count": len(candidates), "candidates": candidates})
    timings["retrieval_seconds"] = round(time.perf_counter() - stage, 4)
    timings["vector_search_seconds"] = vector_search_timings

    if not candidates:
        return {"question": question, "mode": config.retrieval_mode, "generated_queries": queries,
                "hypothetical_answer": hypothetical, "query_alternatives": alternatives, "grammar_corrected_query": corrected,
                "answer": "I could not find supporting passages.", "citations": [], "baseline": [],
                "candidates": [], "reranked": [], "evidence": "", "latency_seconds": round(time.perf_counter()-started, 2),
                "generation_model": config.generation_model.name, "timings": timings}
    stage = time.perf_counter()
    pairs = [(question, row["text"]) for row in candidates]
    with _observe("cross encoder reranking", input={"pairs": pairs}, model=config.reranker_model.name) as rerank_obs:
        scores = _reranker(config.reranker_model.name, config.reranker_model.revision).predict(pairs, show_progress_bar=False)
        _update(rerank_obs, output=[{"id": row["id"], "score": float(score)} for row, score in zip(candidates, scores)])
    timings["reranking_seconds"] = round(time.perf_counter() - stage, 4)
    for row, score in zip(candidates, scores):
        row["rerank_score"] = float(score)
    reranked = sorted(candidates, key=lambda row: row["rerank_score"], reverse=True)[:config.top_k]
    baseline = sorted(candidates, key=lambda row: row.get("similarity", 0), reverse=True)[:config.top_k] if "similarity" in candidates[0] else []
    stage = time.perf_counter()
    with _observe("evidence formatting", input=reranked) as obs:
        evidence = _format_evidence(reranked)
        _update(obs, output=evidence)
    timings["evidence_formatting_seconds"] = round(time.perf_counter() - stage, 4)
    messages = (prompt_bundle["rag-answer"]["client"].compile(question=question, evidence=evidence) if prompt_bundle else [
        {"role": "system", "content": PROMPT_TEMPLATES["answer_system"]},
        {"role": "user", "content": f"Question: {question}\n\nEvidence passages:\n{evidence}"}])
    stage = time.perf_counter()
    answer = _ollama(messages,
                     config.generation_model.name, config.generation.output_budgets, config.generation.temperature, config.generation.context_length,
                     prompt=prompt_bundle["rag-answer"]["client"] if prompt_bundle else None)
    timings["generation_seconds"] = round(time.perf_counter() - stage, 4)
    citations = list(dict.fromkeys(re.findall(r"\[E\d+\]", answer)))
    stage = time.perf_counter()
    with _observe("citation extraction", input=answer) as obs:
        _update(obs, output=citations)
    timings["citation_extraction_seconds"] = round(time.perf_counter() - stage, 4)
    return {"question": question, "mode": config.retrieval_mode, "generated_queries": queries,
            "hypothetical_answer": hypothetical, "query_alternatives": alternatives, "grammar_corrected_query": corrected, "answer": answer,
            "citations": citations, "baseline": baseline, "candidates": candidates, "reranked": reranked,
            "evidence": evidence, "generation_model": config.generation_model.name,
            "latency_seconds": round(time.perf_counter()-started, 2), "timings": timings}
