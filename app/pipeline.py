"""Reusable Millennium RAG answer pipeline shared by HTTP and experiments."""
from __future__ import annotations

import math
import os
import re
import time
from collections import Counter, defaultdict
from functools import lru_cache
from typing import Any

import requests
from qdrant_client import QdrantClient
from sentence_transformers import CrossEncoder, SentenceTransformer

from qdrant_client import models

try:
    from .resolved_config import ResolvedPipelineConfig
    from .observability import observation as _observe, update as _update
    from .prompt_templates import PROMPT_HASHES, PROMPT_TEMPLATES
    from .scenes import scene_collection
except ImportError:
    from resolved_config import ResolvedPipelineConfig
    from observability import observation as _observe, update as _update
    from prompt_templates import PROMPT_HASHES, PROMPT_TEMPLATES
    from scenes import scene_collection


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


_WORD = r"[^\W\d_]+"


@lru_cache(maxsize=8)
def _word_counts(collection: str) -> tuple[Counter, Counter]:
    """How often each word occurs in the indexed passages (case-folded), and how often it is written in lower case."""
    words: Counter = Counter()
    lower: Counter = Counter()
    offset = None
    while True:
        points, offset = qdrant_client().scroll(collection_name=collection, limit=1000, offset=offset, with_payload=["text"])
        for point in points:
            for word in re.findall(_WORD, (point.payload or {}).get("text", "")):
                words[word.casefold()] += 1
                lower[word] += word.islower()
        if offset is None:
            break
    return words, lower


def _english_share(question: str, collection: str) -> float:
    """Share of the question's words, names left out, that the (English) books use at least twice.

    Names (words the books write capitalised more often than not) are the same in every language, so they say nothing
    about the question's language; a word the books never use counts against English.
    """
    words, lower = _word_counts(collection)
    common = [word.casefold() for word in re.findall(_WORD, question)]
    common = [word for word in common if lower[word] and lower[word] >= words[word] - lower[word] or not words[word]]
    return sum(lower[word] >= 2 for word in common) / len(common) if common else 1.0


def _translate(question: str, config: ResolvedPipelineConfig, prompt_bundle: dict[str, Any] | None = None) -> str | None:
    """The question in English when it is asked in another language, otherwise None.

    Names are kept as written, except translated forms of the novels' own names, which become the English edition's.
    """
    with _observe("query translation", input=question) as obs:
        messages = (prompt_bundle["rag-query-translation"]["client"].compile(question=question) if prompt_bundle else [
            {"role": "system", "content": PROMPT_TEMPLATES["query_translation_system"]}, {"role": "user", "content": question}])
        reply = _ollama(messages, config.generation_model.name, config.generation.output_budgets, config.generation.temperature, config.generation.context_length,
                        prompt=prompt_bundle["rag-query-translation"]["client"] if prompt_bundle else None, name="English translation generation")
        fields = {key.strip().upper(): value.strip().strip('"') for key, _, value in (line.partition(":") for line in reply.splitlines())}
        # Asked to judge the language first, the model leaves English questions alone; their wording is never replaced.
        english = fields.get("ENGLISH", "")
        translated = (None if fields.get("LANGUAGE", "english").casefold().strip(" .") == "english" or english.casefold() == question.strip().casefold()
                      else english or None)
        _update(obs, output=translated)
    return translated


def _transform(question: str, config: ResolvedPipelineConfig, prompt_bundle: dict[str, Any] | None = None) -> tuple[str | None, list[str], str | None]:
    mode = config.retrieval_mode
    hypothetical = None
    corrected = None
    alternatives: list[str] = []
    # hyde=false keeps every other step of the mode and only drops the hypothetical document.
    if config.hyde and mode in {"hyde", "hyde_query_expansion", "full"}:
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


@lru_cache(maxsize=4)
def _previous_passages(collection: str) -> dict[str, dict[str, Any]]:
    """The passage before each passage in its EPUB section, by id."""
    sections: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for row in _keyword_index(collection)[0]:
        sections[(row.get("book_file"), row.get("section"))].append(row)
    previous: dict[str, dict[str, Any]] = {}
    for rows in sections.values():
        rows.sort(key=lambda row: (row.get("paragraph", 0), row.get("part", 0)))
        previous.update((row["id"], before) for before, row in zip(rows, rows[1:]))
    return previous


def _with_previous_passage(row: dict[str, Any], collection: str) -> dict[str, Any]:
    """The passage joined with the one before it, so words it matched come with what they refer back to."""
    before = _previous_passages(collection).get(row["id"])
    if not before:
        return row
    return row | {"paragraph": before.get("paragraph"), "part": before.get("part"), "page": before.get("page") or row.get("page"),
                  "text": f"{before['text']}\n{row['text']}", "joined_previous": before["id"]}


def _keyword_search(query: str, collection: str, limit: int, k1: float = 1.2, b: float = 0.75) -> list[dict[str, Any]]:
    """The passages that best match the query's words by BM25, best first (exact words, which dense search can miss)."""
    rows, counts, lengths, frequency = _keyword_index(collection)
    total, average = len(rows), sum(lengths) / max(len(rows), 1)
    weights = {word: math.log(1 + (total - frequency[word] + 0.5) / (frequency[word] + 0.5)) for word in set(_keywords(query)) if frequency[word]}
    scores = [(sum(weight * count[word] * (k1 + 1) / (count[word] + k1 * (1 - b + b * length / average)) for word, weight in weights.items() if word in count), index)
              for index, (count, length) in enumerate(zip(counts, lengths))]
    return [dict(rows[index]) | {"keyword_score": score} for score, index in sorted(scores, reverse=True)[:limit] if score > 0]


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


def _scene_hits(question: str, config: ResolvedPipelineConfig, collection: str, qdrant: QdrantClient,
                evidence: list[dict[str, Any]], present: set[str]) -> list[dict[str, Any]]:
    """Passages of the scene whose summary best matches the question, when it beats every scene the evidence already
    comes from by more than scene_margin and is a confident match.

    Summaries and passages are not scored on the same scale (a summary names everyone and states what happens), so
    the bar is set by the scenes that hold the current evidence, not by the passages themselves.
    """
    name = scene_collection(collection, config)
    vector = _embedder(config.embedding_model.name, config.embedding_model.revision).encode(question, normalize_embeddings=True).tolist()
    found = qdrant.query_points(collection_name=name, query=vector, limit=config.scene_search_hits, with_payload=True).points
    covering, _ = qdrant.scroll(collection_name=name, limit=1000, with_payload=True, scroll_filter=models.Filter(
        must=[models.FieldCondition(key="members", match=models.MatchAny(any=[row["id"] for row in evidence]))]))
    scenes = list({str(point.id): point for point in [*found, *covering]}.values())
    scores = {str(point.id): float(score) for point, score in zip(scenes, _reranker(config.reranker_model.name, config.reranker_model.revision).predict(
        [(question, point.payload["summary"]) for point in scenes], show_progress_bar=False))}
    best = max(found, key=lambda point: scores[str(point.id)])
    covered = max((scores[str(point.id)] for point in covering), default=-math.inf)
    floor = config.low_confidence_score if config.low_confidence_score is not None else -math.inf
    if scores[str(best.id)] <= max(covered + config.scene_margin, floor):
        return []
    members = [member for member in best.payload["members"] if member not in present]
    rows = [dict(point.payload or {}) | {"id": str(point.id), "scene_hit": True, "scene_summary": best.payload["summary"],
                                          "scene_score": scores[str(best.id)]}
            for point in qdrant.retrieve(collection_name=collection, ids=members, with_payload=True)]
    rows.sort(key=lambda row: members.index(row["id"]))
    for row, score in zip(rows, _reranker(config.reranker_model.name, config.reranker_model.revision).predict(
            [(question, row["text"]) for row in rows], show_progress_bar=False)):
        row["rerank_score"] = float(score)
    return rows


def _prompted(prompt_bundle: dict[str, Any] | None, asset: str, system: str, user: str, config: ResolvedPipelineConfig, name: str,
              **variables: str) -> str:
    """One generation-model request with a Langfuse prompt (``asset``), or the local template when there is no bundle."""
    client = prompt_bundle[asset]["client"] if prompt_bundle else None
    messages = client.compile(**variables) if client else [{"role": "system", "content": PROMPT_TEMPLATES[system]}, {"role": "user", "content": user}]
    return _ollama(messages, config.generation_model.name, config.generation.output_budgets, config.generation.temperature,
                   config.generation.context_length, prompt=client, name=name)


def _passage_position(payload: dict[str, Any]) -> tuple:
    return payload.get("book", ""), payload.get("section", ""), payload.get("paragraph", 0), payload.get("part", 0)


def _moment_scene_hits(question: str, config: ResolvedPipelineConfig, collection: str, qdrant: QdrantClient,
                       evidence: list[dict[str, Any]], present: set[str], prompt_bundle: dict[str, Any] | None = None
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
        reply = _prompted(prompt_bundle, "rag-scene-moment", "scene_moment_system", question, config, "moment description", question=question)
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
    vector = _embedder(config.embedding_model.name, config.embedding_model.revision).encode(moment, normalize_embeddings=True).tolist()
    found = qdrant.query_points(collection_name=name, query=vector, limit=config.scene_search_hits, with_payload=True).points
    if not found:
        return [], moment
    first = {str(point.id): dict(point.payload or {}) for point in qdrant.retrieve(
        collection_name=collection, ids=[scene.payload["members"][0] for scene in found], with_payload=True)}
    found.sort(key=lambda scene: _passage_position(first[scene.payload["members"][0]]))
    listing = "\n\n".join(f"[{n}] {first[scene.payload['members'][0]].get('book')}, {first[scene.payload['members'][0]].get('chapter') or 'chapter unknown'}: "
                          f"{scene.payload['summary']}" for n, scene in enumerate(found, 1))
    with _observe("moment scene choice", input={"moment": moment, "scenes": listing}) as obs:
        reply = _prompted(prompt_bundle, "rag-scene-select", "scene_select_system", f"Moment: {moment}\n\nScenes:\n{listing}", config,
                          "moment scene choice", moment=moment, scenes=listing)
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
    # The search models and the cross-encoder are English, so a question asked in another language is translated and
    # every later step (rewrites, reranking, scene search) uses the translation; it is also searched on its own. The
    # answer model still sees the question as asked, so it answers in that language.
    asked = question
    # A question whose words the books use is plainly English and skips the translation request: that request would
    # leave it unchanged but still shift qwen3:8b's later outputs (its replies depend on the previous request).
    translated = (_translate(question, config, prompt_bundle) if config.query_translation and config.retrieval_mode != "baseline"
                  and (config.english_word_share is None or _english_share(question, collection) < config.english_word_share) else None)
    question = translated or question
    hypothetical, alternatives, corrected = _transform(question, config, prompt_bundle)
    timings["transformation_seconds"] = round(time.perf_counter() - stage, 4)
    queries = [asked] + ([translated] if translated else []) + ([hypothetical] if hypothetical else []) + alternatives + ([corrected] if corrected else [])
    query_names = (["original question"] + (["English translation"] if translated else []) + (["hypothetical document"] if hypothetical else [])
                   + [f"literary alternative {i}" for i in range(1, len(alternatives) + 1)] + (["grammar corrected question"] if corrected else []))
    named = question
    if config.name_completion:
        with _observe("name completion", input=question) as obs:
            named = _complete_names(question, collection)
            _update(obs, output=named)
        if named != question:
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
                # The name-completed search is one query that does not compete in fusion, so it looks deeper.
                limit = max(config.candidate_count, config.wide_candidate_count, config.name_completion_hits if query_name == "name completed question" else 0)
                points = qdrant.query_points(collection_name=collection, query=vector, limit=limit, with_payload=True).points
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
        return {"question": asked, "translated_question": translated, "mode": config.retrieval_mode, "generated_queries": queries,
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
    # A strong fused match can still be off the point (on topic, but not answering); a wider passage that beats every
    # fused candidate by wide_override_margin is admitted even then.
    wide_open = config.wide_trigger_score is None or best_fused < config.wide_trigger_score
    wide_bar = wide_floor if wide_open else (wide_floor + config.wide_override_margin if config.wide_override_margin is not None else math.inf)
    wide_hits = sorted((row | ({} if wide_open else {"wide_override": True}) for row in wide if row["rerank_score"] > wide_bar),
                       key=lambda row: row["rerank_score"], reverse=True)[:config.wide_max_hits]
    # Dense search can miss a passage that shares the question's exact words (a quoted phrase, a rare term) when nothing
    # else about it is similar. Keyword (BM25) hits are reranked like the rest, and they are considered only when one of
    # them beats every fused candidate by keyword_margin: dense search then missed by that much something the question
    # names, rather than leaving a near-tie that would only reshuffle the evidence. The keyword hits that beat every
    # fused candidate (up to keyword_max_hits; other places the same words occur) are then added in front of the evidence.
    keyword_hits: list[dict[str, Any]] = []
    if config.keyword_hits and config.keyword_margin is not None and config.retrieval_mode != "baseline":
        stage = time.perf_counter()
        with _observe("keyword search", input=question) as obs:
            pooled = {row["id"] for row in candidates + wide}
            keyword = [row | {"keyword_hit": True} for row in _keyword_search(question, collection, config.keyword_hits) if row["id"] not in pooled]
            if keyword:
                for row, score in zip(keyword, _reranker(config.reranker_model.name, config.reranker_model.revision).predict(
                        [(question, row["text"]) for row in keyword], show_progress_bar=False)):
                    row["rerank_score"] = float(score)
            if keyword and max(row["rerank_score"] for row in keyword) > best_fused + config.keyword_margin:
                # A matched line ("No compromises.") often refers back to what was just said, so each admitted passage
                # is joined with the passage before it (the score stays the one the passage earned on its own), and
                # they are given in reading order, as scene passages are, so repeated lines read as one story.
                keyword_hits = sorted((_with_previous_passage(row, collection) for row in sorted(
                    (row for row in keyword if row["rerank_score"] > best_fused), key=lambda row: row["rerank_score"], reverse=True)[:config.keyword_max_hits]),
                    key=_passage_position)
            _update(obs, output={"searched": len(keyword), "admitted": [{"id": row["id"], "score": row["rerank_score"]} for row in keyword_hits]})
        timings["keyword_search_seconds"] = round(time.perf_counter() - stage, 4)
    # When no passage clearly answers the question, give the answer model more evidence and let it reason.
    low_confidence = config.low_confidence_score is not None and best_fused < config.low_confidence_score
    top_k = max(config.top_k, config.low_confidence_top_k) if low_confidence else config.top_k
    reranked = wide_hits + keyword_hits + sorted(candidates, key=lambda row: row["rerank_score"], reverse=True)[:top_k]
    candidates += wide_hits + keyword_hits
    # A scene whose passages the question cannot match one by one (dialogue that never names the people involved) can
    # still match its summary; its passages go after the usual evidence, which stays as it is. Like the wider-pool
    # override, this is for confident evidence that may be off the point: weak evidence already gets the low-confidence
    # path (more passages and reasoning), and a whole scene on top of that crowds the answer.
    scene_hits: list[dict[str, Any]] = []
    if config.scene_margin is not None and config.retrieval_mode != "baseline" and not low_confidence:
        stage = time.perf_counter()
        with _observe("scene search", input=question) as obs:
            scene_hits = _scene_hits(question, config, collection, qdrant, reranked[:config.top_k], {row["id"] for row in reranked})
            _update(obs, output={"summary": scene_hits[0]["scene_summary"], "score": scene_hits[0]["scene_score"],
                                 "passages": [row["id"] for row in scene_hits]} if scene_hits else None)
        # A question about a detail at one moment ("what did she wear when they first met") matches neither the moment's
        # scene nor the detail's passage as a whole; when the summary search above finds nothing, the moment is searched
        # for on its own (two more generation requests; it needs the scene index, so it is off when scene_margin is null).
        if config.scene_moment and not scene_hits:
            with _observe("moment scene search", input=question) as obs:
                scene_hits, moment = _moment_scene_hits(question, config, collection, qdrant, reranked[:config.top_k],
                                                        {row["id"] for row in reranked}, prompt_bundle)
                _update(obs, output={"moment": moment, "passages": [row["id"] for row in scene_hits]})
        timings["scene_search_seconds"] = round(time.perf_counter() - stage, 4)
        reranked += scene_hits
        candidates += scene_hits
    baseline = sorted(candidates, key=lambda row: row.get("similarity", 0), reverse=True)[:config.top_k] if "similarity" in candidates[0] else []
    stage = time.perf_counter()
    with _observe("evidence formatting", input=reranked) as obs:
        evidence = _format_evidence(reranked)
        if scene_hits and config.scene_thinking:
            # Scene passages are dialogue that rarely names who speaks; read as loose snippets, the answer model picks a
            # few. Saying they are one continuous scene, and letting it reason, makes it go through all of them
            # (opt-in: on QA.csv it made answers more complete but did not raise correctness, and costs ~50 s each).
            first = len(reranked) - len(scene_hits) + 1
            evidence += f"\n\n[E{first}]–[E{len(reranked)}] are consecutive passages of one scene, in reading order."
        _update(obs, output=evidence)
    timings["evidence_formatting_seconds"] = round(time.perf_counter() - stage, 4)
    # When the evidence holds passages that only the completed-name search found, the answer model sees the completed
    # question: those passages use the other half of the name, and given only the bare name the model may not connect
    # them to the person asked about. Otherwise it sees the question as asked.
    # Passages admitted over a confident fused match won on the completed wording, so the model sees it too.
    answer_question = named if any(row.get("name_completion_hit") or row.get("wide_override") for row in reranked) else question
    if translated:
        answer_question = asked if answer_question == translated else f"{asked} ({answer_question})"
    messages = (prompt_bundle["rag-answer"]["client"].compile(question=answer_question, evidence=evidence) if prompt_bundle else [
        {"role": "system", "content": PROMPT_TEMPLATES["answer_system"]},
        {"role": "user", "content": f"Question: {answer_question}\n\nEvidence passages:\n{evidence}"}])
    stage = time.perf_counter()
    answer = _ollama(messages,
                     config.generation_model.name, config.generation.output_budgets, config.generation.temperature, config.generation.context_length,
                     prompt=prompt_bundle["rag-answer"]["client"] if prompt_bundle else None, think=config.answer_thinking or low_confidence or bool(scene_hits and config.scene_thinking))
    timings["generation_seconds"] = round(time.perf_counter() - stage, 4)
    citations = list(dict.fromkeys(re.findall(r"\[E\d+\]", answer)))
    stage = time.perf_counter()
    with _observe("citation extraction", input=answer) as obs:
        _update(obs, output=citations)
    timings["citation_extraction_seconds"] = round(time.perf_counter() - stage, 4)
    return {"question": asked, "translated_question": translated, "mode": config.retrieval_mode, "generated_queries": queries,
            "hypothetical_answer": hypothetical, "query_alternatives": alternatives, "grammar_corrected_query": corrected,
            "name_completed_question": named, "low_confidence": low_confidence, "answer": answer,
            "citations": citations, "baseline": baseline, "candidates": candidates, "reranked": reranked,
            "evidence": evidence, "generation_model": config.generation_model.name,
            "latency_seconds": round(time.perf_counter()-started, 2), "timings": timings}
