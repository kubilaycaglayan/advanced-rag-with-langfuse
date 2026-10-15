"""Reusable Millennium RAG answer pipeline shared by HTTP and experiments."""
from __future__ import annotations

import os
import re
import time
from collections import Counter, defaultdict
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


def _ollama(messages: list[dict[str, str]], model: str, budgets: tuple[int, ...], temperature: float = 0, context_length: int = 8192, *, prompt: Any = None, name: str = "answer generation",
            think: bool = False) -> str:
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
                    "think": think, "stream": False,
                    "options": {"temperature": temperature, "num_ctx": context_length, "num_predict": budget},
                }, timeout=(10, 900))
                response.raise_for_status()
                data = response.json()
                text = data.get("message", {}).get("content", "").strip()
                if text:
                    thinking = data.get("message", {}).get("thinking")
                    _update(obs, output=text, usage_details={"input": data.get("prompt_eval_count"), "output": data.get("eval_count")},
                            **({"metadata": {"thinking": thinking}} if thinking else {}))
                    return text
            except requests.RequestException as exc:
                last_error = exc
                break
        if think and last_error is None:
            # Reasoning can fill the context window before any answer is written; answer directly instead.
            return _ollama(messages, model, budgets[-1:], temperature, context_length, prompt=prompt, name=name)
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


_NAME_WORD = r"[A-ZÅÄÖ][a-zåäöéü]+"


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
            words.update(re.findall(rf"\b{_NAME_WORD}\b", text))
            for first, last in re.findall(rf"\b({_NAME_WORD}) ({_NAME_WORD})\b", text):
                by_word[first][f"{first} {last}"] += 1
                by_word[last][f"{first} {last}"] += 1
        if offset is None:
            break
    return {word: (*names.most_common(1)[0], sum(names.values())) for word, names in by_word.items()}, words


def _complete_names(question: str, collection: str, min_count: int = 20, min_share: float = 0.5, min_other_ratio: float = 3.0) -> str:
    """Expand a bare name the books rarely use for that character to the full name (Mikael -> Mikael Blomkvist).

    A word is completed only when one two-word name dominates its pairings and the books use the
    other half of that name at least ``min_other_ratio`` times as often as the word itself.
    """
    pairs, words = _name_pairs(collection)
    completed = question
    for word in dict.fromkeys(re.findall(rf"\b{_NAME_WORD}\b", question)):
        if word not in pairs:
            continue
        full, count, total = pairs[word]
        other = " ".join(part for part in full.split() if part != word)
        if (count < min_count or count / total < min_share or other in question
                or words[other] < min_other_ratio * words[word]):
            continue
        completed = re.sub(rf"\b{word}\b", full, completed, count=1)
    return completed


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
    query_names = ["original question"] + (["hypothetical document"] if hypothetical else []) + [f"literary alternative {i}" for i in range(1, len(alternatives) + 1)] + (["grammar corrected question"] if corrected else [])
    named = question
    if config.name_completion:
        with _observe("name completion", input=question) as obs:
            named = _complete_names(question, collection)
            _update(obs, output=named)
        if named != question:
            # Only retrieval uses the completed wording; the answer model sees the question as asked.
            queries.append(named)
            query_names.append("name completed question")
    rankings = []
    stage = time.perf_counter()
    vector_search_timings: list[float] = []
    with _observe("candidate retrieval", input={"question": question, "queries": queries}) as obs:
        for query, query_name in zip(queries, query_names):
            search_started = time.perf_counter()
            with _observe(f"search: {query_name}", as_type="retriever", input=query) as search_obs:
                with _observe("query embedding", as_type="embedding", input=query, model=config.embedding_model.name) as embedding_obs:
                    vector = _embedder(config.embedding_model.name, config.embedding_model.revision).encode(query, normalize_embeddings=True).tolist()
                    _update(embedding_obs, output={"dimensions": len(vector)})
                points = qdrant.query_points(collection_name=collection, query=vector, limit=max(config.candidate_count, config.wide_candidate_count), with_payload=True).points
                rankings.append(points)
                _update(search_obs, output={"hits": [{"id": str(point.id), "score": float(point.score), "payload": dict(point.payload or {})} for point in points]})
            vector_search_timings.append(round(time.perf_counter() - search_started, 4))
        wide: list[dict[str, Any]] = []
        if config.retrieval_mode == "baseline":
            candidates = [dict(p.payload or {}) | {"id": str(p.id), "similarity": float(p.score)} for p in rankings[0][:config.candidate_count]]
        else:
            # The name-completed search does not compete in fusion: its hits join the wider pool, so the
            # fused candidates and the usual evidence stay exactly as they were.
            named_hits = rankings.pop() if named != question else []
            with _observe("RRF candidate merge", input={"ranking_count": len(rankings), "rrf_constant": config.rrf_constant}) as merge_obs:
                candidates = _rrf([ranking[:config.candidate_count] for ranking in rankings], config.candidate_count, config.rrf_constant)
                fused_ids = {row["id"] for row in candidates}
                # The wider pool only competes after reranking: its passages are admitted if they beat every fused candidate.
                wide = [row | {"wide_hit": True} for row in _rrf(rankings, config.wide_candidate_count, config.rrf_constant)
                        if row["id"] not in fused_ids] if config.wide_candidate_count > config.candidate_count else []
                pooled = fused_ids | {row["id"] for row in wide}
                wide += [dict(point.payload or {}) | {"id": str(point.id), "rrf_score": 0.0, "retrieval_ranks": [rank], "wide_hit": True, "name_completion_hit": True}
                         for rank, point in enumerate(named_hits, 1) if str(point.id) not in pooled]
                _update(merge_obs, output=candidates)
        _update(obs, output={"candidate_count": len(candidates), "candidates": candidates, "wide_candidate_count": len(wide)})
    timings["retrieval_seconds"] = round(time.perf_counter() - stage, 4)
    timings["vector_search_seconds"] = vector_search_timings

    if not candidates:
        return {"question": question, "mode": config.retrieval_mode, "generated_queries": queries,
                "hypothetical_answer": hypothetical, "query_alternatives": alternatives, "grammar_corrected_query": corrected,
                "answer": "I could not find supporting passages.", "citations": [], "baseline": [],
                "candidates": [], "reranked": [], "evidence": "", "latency_seconds": round(time.perf_counter()-started, 2),
                "generation_model": config.generation_model.name, "timings": timings}
    stage = time.perf_counter()
    # Fused candidates are scored against the question as asked. When a bare name was completed, the wider pool is
    # scored against the completed wording (the cross-encoder cannot tell that "Mikael" is the "Blomkvist" of the
    # passages), and the fused candidates are scored against it too, only to set the bar wider passages must clear.
    wide_question = named if named != question else question
    pairs = ([(question, row["text"]) for row in candidates] + [(wide_question, row["text"]) for row in wide]
             + ([(named, row["text"]) for row in candidates] if named != question and wide else []))
    with _observe("cross encoder reranking", input={"pairs": pairs}, model=config.reranker_model.name) as rerank_obs:
        scores = [float(score) for score in _reranker(config.reranker_model.name, config.reranker_model.revision).predict(pairs, show_progress_bar=False)]
        _update(rerank_obs, output=[{"id": row["id"], "score": score} for row, score in zip(candidates + wide, scores)])
    timings["reranking_seconds"] = round(time.perf_counter() - stage, 4)
    for row, score in zip(candidates + wide, scores):
        row["rerank_score"] = score
    best_fused = max(row["rerank_score"] for row in candidates)
    # When the fused candidates hold no near-certain match, up to wide_max_hits wider-pool passages are added in front
    # of the evidence if they beat every fused candidate (under both wordings) and are confident matches; the usual
    # evidence stays as it is.
    wide_floor = max([best_fused, *scores[len(candidates) + len(wide):]]
                     + ([config.low_confidence_score] if config.low_confidence_score is not None else []))
    wide_open = config.wide_trigger_score is None or best_fused < config.wide_trigger_score
    wide_hits = sorted((row for row in wide if wide_open and row["rerank_score"] > wide_floor),
                       key=lambda row: row["rerank_score"], reverse=True)[:config.wide_max_hits]
    # When no passage clearly answers the question, give the answer model more evidence and let it reason.
    low_confidence = config.low_confidence_score is not None and best_fused < config.low_confidence_score
    top_k = max(config.top_k, config.low_confidence_top_k) if low_confidence else config.top_k
    reranked = wide_hits + sorted(candidates, key=lambda row: row["rerank_score"], reverse=True)[:top_k]
    candidates += wide_hits
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
                     prompt=prompt_bundle["rag-answer"]["client"] if prompt_bundle else None, think=config.answer_thinking or low_confidence)
    timings["generation_seconds"] = round(time.perf_counter() - stage, 4)
    citations = list(dict.fromkeys(re.findall(r"\[E\d+\]", answer)))
    stage = time.perf_counter()
    with _observe("citation extraction", input=answer) as obs:
        _update(obs, output=citations)
    timings["citation_extraction_seconds"] = round(time.perf_counter() - stage, 4)
    return {"question": question, "mode": config.retrieval_mode, "generated_queries": queries,
            "hypothetical_answer": hypothetical, "query_alternatives": alternatives, "grammar_corrected_query": corrected,
            "name_completed_question": named, "low_confidence": low_confidence, "answer": answer,
            "citations": citations, "baseline": baseline, "candidates": candidates, "reranked": reranked,
            "evidence": evidence, "generation_model": config.generation_model.name,
            "latency_seconds": round(time.perf_counter()-started, 2), "timings": timings}
