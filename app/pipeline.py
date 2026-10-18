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
    from .entities import entity_cards_path, entity_events_path
    from .scenes import context_collection, scene_collection
except ImportError:
    from resolved_config import ResolvedPipelineConfig
    from observability import observation as _observe, update as _update
    from prompt_templates import PROMPT_HASHES, PROMPT_TEMPLATES
    from entities import entity_cards_path, entity_events_path
    from scenes import context_collection, scene_collection


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


def _rare_question_words(question: str, collection: str, share: float) -> set[str]:
    """The question's content words, names aside, that occur in fewer than ``share`` of the passages."""
    rows, _, _, frequency = _keyword_index(collection)
    names = {word for name in re.findall(rf"(?<!^)\b{_NAME_WORD}", question.strip()) for word in _keywords(name)}
    return {word for word in _keywords(question) if len(word) > 1 and word not in names and 0 < frequency[word] < share * len(rows)}


def _sentence_holds(text: str, words: set[str]) -> bool:
    return any(words <= set(_keywords(sentence)) for sentence in re.split(r"(?<=[.!?”])\s+", text))


# Other names of a person, from the entity cards /index builds (app/entities.py).
_OTHER_NAME = re.compile(r"identity|alias|nickname|handle\b|pseudonym|name on|nameplate|cover name|false name|other name|code ?name", re.I)
_ANCHOR_SKIP = frozenset("what who how when where why which did does is was according for in the a".split())
_TITLES = frozenset("mr mr. mrs mrs. ms ms. miss dr dr. herr fru fröken fräulein frau madame monsieur sir lady".split())


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


def _is_other_name(edge: dict[str, Any]) -> bool:
    """An edge from a name the person goes by: a proper name whose mentions were typed as one (alias, handle, …)."""
    name = edge["text"].split(" — ")[0]
    return (all(word[:1].isupper() or not word[:1].isalpha() for word in name.split())
            and any(_OTHER_NAME.search(kind) for kind in edge.get("types", [])))


def _entity_name_hits(question: str, config: ResolvedPipelineConfig, collection: str, qdrant: QdrantClient,
                      evidence: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    """When the question's best match among the links into a person it names is another name of that person (a false
    identity, nickname, handle, name on a door), the passages stating that person's other names: the matched one
    first, then the most often stated. Questions about a set of names ("her fake identity") are answered by several
    passages that never use the question's words and say "she", which only the merged links connect. Nothing is added
    when the evidence already names the best match: retrieval found it, and more names would only crowd the answer."""
    path = entity_cards_path(collection, config)
    if not config.entity_names or not path.exists():
        return []
    data = _entity_cards(str(path))
    anchors = _entity_anchors(question, data)
    linked = [edge for edge in data["edges"] if edge["to"] in anchors]
    if not linked:
        return []
    reranker = _reranker(config.reranker_model.name, config.reranker_model.revision)
    ranked = sorted(zip((float(score) for score in reranker.predict([(question, edge["text"]) for edge in linked], show_progress_bar=False)), linked),
                    key=lambda pair: -pair[0])
    floor = config.low_confidence_score if config.low_confidence_score is not None else -math.inf
    if ranked[0][0] < floor or not _is_other_name(ranked[0][1]):
        return []
    if any(name.lower() in row["text"].lower() for name in ranked[0][1]["names"] for row in evidence):
        return []
    present = {row["id"] for row in evidence}
    # Someone linked to the person as a person in a way that is not a name ("friend of", "contact of") is another
    # person, not one of their names, even where a window calls them a nickname.
    others = {edge["from"] for edge in linked if edge.get("types", [""])[0] == "person"
              and not re.search(r"name|identity|alias|nickname|handle|persona|pseudonym", edge["relation"], re.I)}
    own = {word for anchor in anchors for word in anchor.split()}
    group: dict[str, list[dict[str, Any]]] = {}
    for _, edge in ranked:
        if _is_other_name(edge) and edge["from"] not in others and not set(edge["from"].split()) <= own | _TITLES:  # "Fröken Salander" is her own name
            group.setdefault(edge["from"], []).append(edge)
    first = ranked[0][1]["from"]
    rows = []
    # Besides the best match, a name must be linked to the person in at least two windows: one window's guess is noise.
    group = {entity: edges for entity, edges in group.items() if entity == first or sum(edge["count"] for edge in edges) >= 2}
    for entity, edges in sorted(group.items(), key=lambda item: (item[0] != first, -sum(edge["count"] for edge in item[1])))[:limit]:
        names = {name.lower() for edge in edges for name in edge["names"]}
        points = [point for point in qdrant.retrieve(collection, ids=sorted({m for edge in edges for m in edge["members"]}), with_payload=True)
                  if str(point.id) not in present and any(name in point.payload["text"].lower() for name in names)]
        if not points:
            continue
        statement = edges[0]["text"].split(":")[0]
        score, point = max(zip(reranker.predict([(statement, point.payload["text"]) for point in points], show_progress_bar=False), points),
                           key=lambda pair: pair[0])
        rows.append(dict(point.payload or {}) | {"id": str(point.id), "entity_hit": True, "entity": entity, "entity_score": float(score),
                                                 "entity_link": statement})
    if rows:
        for row, score in zip(rows, reranker.predict([(question, row["text"]) for row in rows], show_progress_bar=False)):
            row["rerank_score"] = float(score)
    return rows


# Entity matrix: rows are entities, columns kinds of link (the edge's type: nickname, vehicle, tattoo, ...), cells edges.
# "in the book(s)" and similar only scope the question; the words below say nothing about which rows or cells.
_SCOPE = re.compile(r"\b(?:in|of|from|throughout|across)\s+(?:the\s+|this\s+|these\s+|all\s+(?:the\s+)?)?(?:books?|novels?|stor(?:y|ies)|trilogy|series)\b", re.I)
_MATRIX_SKIP = frozenset("any there used use uses have has had get got".split())


@lru_cache(maxsize=2)
def _entity_columns(path: str, model: str, revision: str | None) -> tuple[list[str], Any]:
    labels = sorted({kind for edge in _entity_cards(path)["edges"] for kind in edge.get("types", []) if kind})
    return labels, _embedder(model, revision).encode(labels, normalize_embeddings=True, show_progress_bar=False)


def _entity_family(key: str, cards: dict[str, Any]) -> set[str]:
    """The entity's full name (the most mentioned multi-word name containing all its words) and every entity named by
    words of it: Blomkvist, Mikael and Mikael Blomkvist are one person split by the merge."""
    words = set(key.split())
    longer = [other for other in cards if len(other.split()) > 1 and words <= set(other.split())]
    full = max(longer, key=lambda other: cards[other]["mentions"]) if longer else key
    return {other for other in cards if set(other.split()) <= set(full.split())} | {key}


def _entity_matrix_hits(question: str, config: ResolvedPipelineConfig, collection: str, qdrant: QdrantClient,
                        evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Passages for the cells of the entity matrix the question asks about, from any end.

    The question's words pick the columns (a phrase as close as ``entity_matrix_similarity`` to a kind of link:
    "nicknames" → nickname, "car" → vehicle, "fake identity" → false identity). Entities it names restrict the cells to
    those with that entity (or another name of it) at either end; the words left over ("police officers", "dragon")
    are scored against every fact of each end; with neither, the cells most often stated come first. Each of the best
    cells, one per name, adds the passage that states it with a ``Link:`` line, since such passages often say "she".
    Nothing is added when the evidence already names the best cell, or when no cell is a confident match."""
    path = entity_cards_path(collection, config)
    if not path.exists():
        return []
    data = _entity_cards(str(path))
    cards = {card["key"]: card for card in data["cards"]}
    asked = _SCOPE.sub(" ", question)
    content = [word for word in re.findall(r"[A-Za-zÅÄÖåäöé][\w-]*", asked)
               if word.lower() not in _KEYWORD_STOPWORDS and word.lower() not in _MATRIX_SKIP]
    phrases = sorted(set(content) | {f"{first} {second}" for first, second in zip(content, content[1:])})
    if not phrases:
        return []
    labels, label_vectors = _entity_columns(str(path), config.embedding_model.name, config.embedding_model.revision)
    embedder = _embedder(config.embedding_model.name, config.embedding_model.revision)
    similarity = embedder.encode(phrases, normalize_embeddings=True, show_progress_bar=False) @ label_vectors.T
    best = float(similarity.max())
    columns, used, column_phrase = set(), set(), ""
    for column, label in enumerate(labels):
        # Near ties are kept ("book" and "book series"); a weaker match is another word of the question.
        if similarity[:, column].max() >= max(config.entity_matrix_similarity, best - 0.05):
            columns.add(label)
            phrase = phrases[int(similarity[:, column].argmax())]
            used |= set(phrase.split())
            column_phrase = column_phrase or phrase
    if not columns:
        return []
    anchors = _entity_anchors(question, data)
    named = set().union(*(_entity_family(anchor, cards) for anchor in anchors)) if anchors else set()
    anchor_words = {word for anchor in anchors for word in anchor.split()}
    residual = " ".join(word for word in content if word not in used and not word[:1].isupper()
                        and re.sub(r"[’']s$", "", word).lower() not in anchor_words)
    families: dict[str, set[str]] = {}

    def family(key: str) -> set[str]:
        if key not in families:
            families[key] = _entity_family(key, cards) if key in cards else {key}
        return families[key]

    def full_name(key: str) -> str:
        return max(family(key), key=lambda other: (len(other.split()), cards.get(other, {}).get("mentions", 0)))

    def misread(edge: dict[str, Any]) -> bool:
        """Not a link between two entities: a cell from part of the other end's own name (Curt → Curt Andersson,
        Fröken Salander); a one-word name that is part of another person's full name (Andersson → Curt Andersson as a
        "nickname" of Bublanski); or one window's claim about someone the books otherwise treat as a person of their
        own (Dragan Armansky as a "nickname" of Bublanski)."""
        first, second = set(edge["from"].split()), set(edge["to"].split())
        if first <= second | _TITLES or second <= first | _TITLES or edge["from"] in family(edge["to"]):
            return True
        owner = full_name(edge["from"])
        person = lambda key: cards.get(key, {}).get("types", [""])[:1] == ["person"]
        if edge["count"] < 2 and person(edge["from"]) and cards[edge["from"]]["mentions"] >= 20:
            return True
        return (len(first) == 1 and len(owner.split()) > 1 and person(owner)
                and not set(owner.split()) & set(full_name(edge["to"]).split()))

    cells = [edge for edge in data["edges"] if columns & set(edge.get("types", []))
             and (not named or edge["from"] in named or edge["to"] in named)]
    cells = [edge for edge in cells if not misread(edge)]
    if not cells:
        return []
    reranker = _reranker(config.reranker_model.name, config.reranker_model.revision)
    floor = config.low_confidence_score if config.low_confidence_score is not None else -math.inf
    if named:
        scores = [float(score) for score in reranker.predict([(question, edge["text"].split(":")[0]) for edge in cells], show_progress_bar=False)]
    elif residual:
        # The left-over words describe one end ("police officers" a person, "dragon" the tattoo itself), alone or
        # together with the column's word ("dragon tattoo"); each end is scored by its facts that best match either.
        queries = list(dict.fromkeys([residual, f"{residual} {column_phrase}"]))
        query_vectors = embedder.encode(queries, normalize_embeddings=True, show_progress_bar=False)
        vectors = data.setdefault("fact_vectors", {})
        near: dict[str, tuple[float, list[tuple[str, str]]]] = {}
        for key in {key for edge in cells for key in (edge["from"], edge["to"])}:
            best_similarity, pairs = -1.0, []
            for other in family(key) & set(cards):
                if other not in vectors:
                    facts = cards[other].get("facts", [])
                    vectors[other] = (facts, embedder.encode(facts, normalize_embeddings=True, show_progress_bar=False, batch_size=128) if facts else None)
                facts, matrix = vectors[other]
                if facts:
                    for query, vector in zip(queries, query_vectors):
                        closeness = matrix @ vector
                        best_similarity = max(best_similarity, float(closeness.max()))
                        pairs += [(query, facts[index]) for index in closeness.argsort()[::-1][:8]]
            near[key] = (best_similarity, pairs)
        # Only the ends whose facts come closest are scored by the cross-encoder; the rest cannot match.
        ends = dict.fromkeys(near, -math.inf)
        for key in sorted(near, key=lambda key: -near[key][0])[:20]:
            if near[key][1]:
                ends[key] = float(max(reranker.predict(near[key][1], show_progress_bar=False, batch_size=128)))
        scores = [max(ends[edge["from"]], ends[edge["to"]]) for edge in cells]
    else:
        # The whole column: a cell stated in two windows is a fact of the books, one window's may be a misreading.
        scores = [float(edge["count"]) for edge in cells]
        floor = 2.0
    # Cells stated in two or more windows first: one window's link may be a misreading.
    ranked = sorted(zip(scores, cells), key=lambda pair: (pair[1]["count"] < 2, -pair[0], -pair[1]["count"]))
    if max(scores) < floor:
        return []
    ranked = [pair for pair in ranked if pair[0] >= floor]
    flat = lambda text: " ".join(text.split()).casefold()
    # Retrieval already found the answer when the evidence names the best cell or, for a question about a named
    # entity ("What car does Blomkvist drive?"), any confident cell of it.
    if any(flat(name) in flat(row["text"]) for _, edge in (ranked if named else ranked[:1]) for name in edge["names"] for row in evidence):
        return []
    present = {row["id"] for row in evidence}
    rows, seen = [], set()
    for score, edge in ranked:
        if len(rows) >= config.entity_matrix_max_hits:
            break
        if edge["from"] in seen:
            continue
        seen.add(edge["from"])
        names = {name.lower() for name in edge["names"]}
        points = [point for point in qdrant.retrieve(collection, ids=edge["members"], with_payload=True)
                  if str(point.id) not in present and any(name in point.payload["text"].lower() for name in names)]
        if not points:
            continue
        statement = edge["text"].split(":")[0]
        _, point = max(zip(reranker.predict([(statement, point.payload["text"]) for point in points], show_progress_bar=False), points),
                       key=lambda pair: pair[0])
        present.add(str(point.id))
        rows.append(dict(point.payload or {}) | {"id": str(point.id), "entity_hit": True, "entity": edge["from"], "entity_score": score,
                                                 "entity_link": statement})
    if rows:
        for row, score in zip(rows, reranker.predict([(question, row["text"]) for row in rows], show_progress_bar=False)):
            row["rerank_score"] = float(score)
    return rows


def _entity_key(name: str, data: dict[str, Any]) -> str | None:
    """The entity card a name refers to: its own, its alias, or the most mentioned card containing the name's words."""
    key = re.sub(r"[’']s$", "", name.strip()).casefold()
    key = data["alias"].get(key, key)
    if key in data["mentions"]:
        return key
    words = set(key.split())
    matches = [other for other in data["mentions"] if words and words <= set(other.split())]
    return max(matches, key=data["mentions"].get) if matches else None


@lru_cache(maxsize=2)
def _entity_graph(path: str, events_path: str, collection: str) -> tuple[dict[Any, int], list[str], list[dict[str, Any]], Any]:
    """The entity cards and events as one graph. Nodes are passages, entities and events; an entity is joined to each
    passage of the windows that mention it and to the entities its links point to (weighted by the windows stating the
    link), an event to the people it is between and to the passages of its window, and each passage to the next one
    of its EPUB section. Returns the node index, the passage ids (the first nodes), the events (keyed ("event", i)) and
    the column-normalised transition matrix that Personalized PageRank walks."""
    import json
    import numpy as np
    import scipy.sparse as sparse
    data = _entity_cards(path)
    with open(events_path, encoding="utf-8") as handle:
        events = json.load(handle)
    passages = [row["id"] for row in _keyword_index(collection)[0]]
    index: dict[Any, int] = {pid: i for i, pid in enumerate(passages)}
    for card in data["cards"]:
        index.setdefault(card["key"], len(index))
    for number in range(len(events)):
        index[("event", number)] = len(index)
    rows, columns, weights = [], [], []

    def join(first: int, second: int, weight: float) -> None:
        rows.extend((first, second))
        columns.extend((second, first))
        weights.extend((weight, weight))

    for card in data["cards"]:
        for member in card["members"]:
            if member in index:
                join(index[card["key"]], index[member], 1.0)
    for edge in data["edges"]:
        if edge["from"] in index and edge["to"] in index:
            join(index[edge["from"]], index[edge["to"]], float(edge["count"]))
    for number, event in enumerate(events):
        node = index[("event", number)]
        for member in event["members"]:
            if member in index:
                join(node, index[member], 1.0)
        for name in event["people"]:
            key = _entity_key(name, data)
            if key:
                join(node, index[key], 1.0)
    for pid, before in _previous_passages(collection).items():
        join(index[before["id"]], index[pid], 1.0)
    adjacency = sparse.csr_matrix((weights, (rows, columns)), shape=(len(index), len(index)))
    degree = np.asarray(adjacency.sum(axis=1)).ravel()
    degree[degree == 0] = 1
    return index, passages, events, (sparse.diags(1 / degree) @ adjacency).T.tocsr()


def _entity_graph_events(question: str, config: ResolvedPipelineConfig, collection: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every event, ranked by Personalized PageRank from the entities the question names (each weighted by 1/sqrt of its
    passages, so the main characters do not spread over every book) and from the evidence: the events the graph ties
    most closely to both come first."""
    import numpy as np
    path, events_path = entity_cards_path(collection, config), entity_events_path(collection, config)
    if not path.exists() or not events_path.exists():
        return []
    data = _entity_cards(str(path))
    index, passages, events, walk = _entity_graph(str(path), str(events_path), collection)
    members = {card["key"]: len(card["members"]) for card in data["cards"]}
    seed = np.zeros(walk.shape[0])
    for anchor in _entity_anchors(question, data):
        seed[index[anchor]] += 1 / math.sqrt(max(1, members[anchor]))
    for row in evidence:
        if row["id"] in index:
            seed[index[row["id"]]] += 0.1
    if not seed.any():
        return []
    seed /= seed.sum()
    rank = seed.copy()
    for _ in range(30):
        rank = (1 - config.entity_graph_damping) * seed + config.entity_graph_damping * (walk @ rank)
    first = len(passages) + len(data["cards"])
    return [events[i] for i in np.argsort(-rank[first:])]


def _entity_graph_hits(question: str, config: ResolvedPipelineConfig, collection: str, qdrant: QdrantClient,
                       evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Passages stating the events the entity graph ties to the question, after the usual evidence.

    A passage that calls the person "my father" or "him" shares no words with the question, and the cross-encoder
    scores it far below passages that do; the events read from its window with the text before it name the people
    ("Harriet Vanger killed Gottfried Vanger by holding him under the water with an oar"). The best
    ``entity_graph_pool`` events by graph rank are scored against the question, and up to ``entity_graph_max_hits``
    that score at least ``low_confidence_score`` and are stated by a passage not already in the evidence add that
    passage with the event as its ``Link:`` line."""
    present = {row["id"] for row in evidence}
    pool = [event for event in _entity_graph_events(question, config, collection, evidence)
            if not set(event["members"]) <= present][:config.entity_graph_pool]
    if not pool or not config.entity_graph_max_hits:
        return []
    reranker = _reranker(config.reranker_model.name, config.reranker_model.revision)
    floor = config.low_confidence_score if config.low_confidence_score is not None else -math.inf
    scored = sorted(((float(score), event) for score, event in zip(reranker.predict([(question, event["fact"]) for event in pool], show_progress_bar=False), pool)
                     if score >= floor), key=lambda pair: -pair[0])
    rows: list[dict[str, Any]] = []
    for score, event in scored:
        if len(rows) >= config.entity_graph_max_hits:
            break
        points = [point for point in qdrant.retrieve(collection, ids=event["members"], with_payload=True) if str(point.id) not in present]
        if not points:
            continue
        _, point = max(zip(reranker.predict([(event["fact"], point.payload["text"]) for point in points], show_progress_bar=False), points),
                       key=lambda pair: pair[0])
        present.add(str(point.id))
        rows.append(dict(point.payload or {}) | {"id": str(point.id), "entity_graph_hit": True, "entity_score": score, "entity_link": event["fact"]})
    if rows:
        for row, score in zip(rows, reranker.predict([(question, row["text"]) for row in rows], show_progress_bar=False)):
            row["rerank_score"] = float(score)
    return rows


def _entity_graph_facts(question: str, config: ResolvedPipelineConfig, collection: str, qdrant: QdrantClient,
                        evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ``entity_graph_facts`` events the question matches best among the ``entity_graph_pool`` the graph ties
    most closely to it, each as one short evidence line placed at the passage that states it.

    The answer to "How did Gottfried really die?" is an event the cross-encoder ranks below the official story it
    contradicts ("Gottfried died in a banal way after getting drunk"), so no score rule picks it; given the events
    themselves, a few sentences each, the answer model can weigh them as it weighs passages."""
    pool = _entity_graph_events(question, config, collection, evidence)[:config.entity_graph_pool]
    if not pool:
        return []
    reranker = _reranker(config.reranker_model.name, config.reranker_model.revision)
    scored = sorted(zip((float(score) for score in reranker.predict([(question, event["fact"]) for event in pool], show_progress_bar=False)), pool),
                    key=lambda pair: -pair[0])
    best: dict[str, tuple[float, dict[str, Any]]] = {}
    for score, event in scored:
        best.setdefault(event["fact"].casefold(), (score, event))
    chosen = sorted(best.values(), key=lambda pair: -pair[0])[:config.entity_graph_facts]
    points = {str(point.id): point for point in qdrant.retrieve(collection, ids=sorted({m for _, event in chosen for m in event["members"]}), with_payload=True)}
    rows = []
    for score, event in chosen:
        window = [points[m] for m in event["members"] if m in points]
        if not window:
            continue
        _, point = max(zip(reranker.predict([(event["fact"], point.payload["text"]) for point in window], show_progress_bar=False), window),
                       key=lambda pair: pair[0])
        rows.append(dict(point.payload or {}) | {"id": f"event:{point.id}:{len(rows)}", "passage_id": str(point.id), "text": event["fact"],
                                                 "graph_fact": True, "rerank_score": score})
    return rows


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


def _context_hits(question: str, config: ResolvedPipelineConfig, collection: str, qdrant: QdrantClient, vectors: list[list[float]],
                  candidates: list[dict[str, Any]], present: set[str]) -> list[dict[str, Any]]:
    """Passages found with their scene's summary in front, which the fused candidates and the usual evidence lack,
    when they rank among the scene_context_rank best of all of them reranked that way and are confident matches.

    The summary says who is there and what happens, so a passage that names neither (a line of dialogue, the line a
    chapter ends on) can match a question that describes the moment. Every row is reranked with its summary in front,
    the fused candidates too, so a scene that matches lifts its passages on one scale.
    """
    name = context_collection(collection, config)
    found = _rrf([qdrant.query_points(collection_name=name, query=vector, limit=config.candidate_count, with_payload=True).points
                  for vector in vectors], config.candidate_count, config.rrf_constant)
    fused = {row["id"] for row in candidates}
    contexts = {str(point.id): (point.payload or {}).get("context")
                for point in qdrant.retrieve(collection_name=name, ids=list(fused), with_payload=["context"])}
    rows = [row | {"context": contexts.get(row["id"])} for row in candidates] + [row for row in found if row["id"] not in fused]
    scores = _reranker(config.reranker_model.name, config.reranker_model.revision).predict(
        [(question, f"{row['context']}\n{row['text']}" if row.get("context") else row["text"]) for row in rows], show_progress_bar=False)
    best = sorted(zip(rows, (float(score) for score in scores)), key=lambda pair: pair[1], reverse=True)[:config.scene_context_rank]
    floor = config.low_confidence_score if config.low_confidence_score is not None else -math.inf
    return [row | {"scene_context_hit": True, "rerank_score": score, "context_score": score}
            for row, score in best if row["id"] not in present and score > floor][:config.scene_context_max_hits]


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
        f"[E{i}] Book: {row.get('book')} | Chapter: {row.get('chapter') or 'unavailable'} | Paragraph: {row.get('paragraph', 'unavailable')} | Page: {row.get('page') or 'unavailable'}\n"
        # A passage found through the entity index says "she"; the link it was found by says who and how.
        + (f"Link: {row['entity_link']}\n" if row.get("entity_link") else "")
        # An event the entity graph found is one sentence about the passage at this place, not the passage itself.
        + (f"Event: {row['text']}" if row.get("graph_fact") else f"Passage: {row['text']}")
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
    vectors: list[list[float]] = []
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
                vectors.append(vector)
                _update(search_obs, output={"hits": [{"id": str(point.id), "score": float(point.score), "payload": dict(point.payload or {})} for point in points]})
            vector_search_timings.append(round(time.perf_counter() - search_started, 4))
        wide: list[dict[str, Any]] = []
        if config.retrieval_mode == "baseline":
            candidates = [dict(p.payload or {}) | {"id": str(p.id), "similarity": float(p.score)} for p in rankings[0][:config.candidate_count]]
        else:
            # The name-completed search does not compete in fusion: its hits join the wider pool, so the
            # fused candidates and the usual evidence stay exactly as they were.
            named_hits = rankings.pop() if named != question else []
            if named != question:
                vectors.pop()
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
    # A sentence that holds every rare word of the question (two or more, names aside: the passage may say "she") nearly
    # quotes it, however the passage around it scores, so such keyword hits (keyword_rare_share) are added as well.
    keyword_hits: list[dict[str, Any]] = []
    if config.keyword_hits and (config.keyword_margin is not None or config.keyword_rare_share is not None) and config.retrieval_mode != "baseline":
        stage = time.perf_counter()
        with _observe("keyword search", input=question) as obs:
            pooled = {row["id"] for row in candidates + wide}
            keyword = [row | {"keyword_hit": True} for row in _keyword_search(question, collection, config.keyword_hits) if row["id"] not in pooled]
            if keyword:
                for row, score in zip(keyword, _reranker(config.reranker_model.name, config.reranker_model.revision).predict(
                        [(question, row["text"]) for row in keyword], show_progress_bar=False)):
                    row["rerank_score"] = float(score)
            admitted: list[dict[str, Any]] = []
            if keyword and config.keyword_margin is not None and max(row["rerank_score"] for row in keyword) > best_fused + config.keyword_margin:
                admitted = sorted((row for row in keyword if row["rerank_score"] > best_fused), key=lambda row: row["rerank_score"], reverse=True)
            rare = _rare_question_words(question, collection, config.keyword_rare_share) if config.keyword_rare_share is not None else set()
            if len(rare) >= 2:
                admitted += [row | {"rare_words_hit": True} for row in keyword if row not in admitted and _sentence_holds(row["text"], rare)]
            # A matched line ("No compromises.") often refers back to what was just said, so each admitted passage
            # is joined with the passage before it (the score stays the one the passage earned on its own), and
            # they are given in reading order, as scene passages are, so repeated lines read as one story.
            keyword_hits = sorted((row if row.get("rare_words_hit") else _with_previous_passage(row, collection) for row in admitted[:config.keyword_max_hits]),
                                  key=_passage_position)
            _update(obs, output={"searched": len(keyword), "admitted": [{"id": row["id"], "score": row["rerank_score"]} for row in keyword_hits]})
        timings["keyword_search_seconds"] = round(time.perf_counter() - stage, 4)
    # A passage that names neither the people nor the moment can still be found with its scene's summary in front of
    # it; such passages are added after the usual evidence when they rank among the best with summaries in front.
    # The later paths do not see them, so everything else (the evidence's order, which scene the scene path adds)
    # stays exactly as it is: in front, they shifted what the answer model leaned on and which scene was added.
    context_hits: list[dict[str, Any]] = []
    # It needs the scene index, so it is off when scene_margin is null.
    if config.scene_context and config.scene_margin is not None and config.retrieval_mode != "baseline":
        stage = time.perf_counter()
        with _observe("scene context search", input=question) as obs:
            top = sorted(candidates, key=lambda row: row["rerank_score"], reverse=True)[:config.top_k]
            context_hits = _context_hits(question, config, collection, qdrant, vectors, candidates,
                                         {row["id"] for row in wide_hits + keyword_hits + top})
            _update(obs, output=[{"id": row["id"], "score": row["rerank_score"], "context": row.get("context")} for row in context_hits])
        timings["scene_context_seconds"] = round(time.perf_counter() - stage, 4)
    # When no passage clearly answers the question, give the answer model more evidence and let it reason.
    low_confidence = config.low_confidence_score is not None and best_fused < config.low_confidence_score
    top_k = max(config.top_k, config.low_confidence_top_k) if low_confidence else config.top_k
    entity_hits: list[dict[str, Any]] = []
    if config.entity_names and config.retrieval_mode != "baseline":
        stage = time.perf_counter()
        with _observe("entity names", input=question) as obs:
            entity_hits = _entity_name_hits(question, config, collection, qdrant,
                                            wide_hits + keyword_hits + sorted(candidates, key=lambda row: row["rerank_score"], reverse=True)[:top_k])
            _update(obs, output=[{"id": row["id"], "entity": row["entity"], "score": row["rerank_score"]} for row in entity_hits])
        timings["entity_names_seconds"] = round(time.perf_counter() - stage, 4)
    # The other names of a person the question names are entity_names' case; the matrix answers the rest.
    if config.entity_matrix and config.retrieval_mode != "baseline" and not entity_hits:
        stage = time.perf_counter()
        with _observe("entity matrix", input=question) as obs:
            entity_hits = _entity_matrix_hits(question, config, collection, qdrant,
                                              wide_hits + keyword_hits + sorted(candidates, key=lambda row: row["rerank_score"], reverse=True)[:top_k])
            _update(obs, output=[{"id": row["id"], "entity": row["entity"], "link": row["entity_link"], "score": row["entity_score"]}
                                 for row in entity_hits])
        timings["entity_matrix_seconds"] = round(time.perf_counter() - stage, 4)
    reranked = wide_hits + keyword_hits + entity_hits + sorted(candidates, key=lambda row: row["rerank_score"], reverse=True)[:top_k]
    # Passages stating the events the entity graph ties to the question's people and its evidence go after the usual
    # evidence, which stays as it is.
    if config.entity_graph and config.retrieval_mode != "baseline":
        stage = time.perf_counter()
        with _observe("entity graph", input=question) as obs:
            graph_hits = _entity_graph_hits(question, config, collection, qdrant, reranked)
            # The events themselves, one line each, when the answer model should weigh them (entity_graph_facts).
            graph_facts = _entity_graph_facts(question, config, collection, qdrant, reranked) if config.entity_graph_facts else []
            _update(obs, output={"passages": [{"id": row["id"], "link": row["entity_link"], "score": row["entity_score"]} for row in graph_hits],
                                 "events": [{"passage": row["passage_id"], "event": row["text"], "score": row["rerank_score"]} for row in graph_facts]})
        timings["entity_graph_seconds"] = round(time.perf_counter() - stage, 4)
        reranked += graph_hits + graph_facts
        candidates += graph_hits
    context_hits = [row for row in context_hits if row["id"] not in {row["id"] for row in reranked}]
    candidates += wide_hits + keyword_hits + entity_hits
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
        scene_hits = [row for row in scene_hits if row["id"] not in {row["id"] for row in context_hits}]
        candidates += scene_hits
    # Scene context hits go after the usual evidence and before the scene passages, which stay last as one scene.
    candidates += [row for row in context_hits if row["id"] not in {row["id"] for row in candidates}]
    reranked += context_hits + scene_hits
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
