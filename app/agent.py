"""Agentic question answering over the retrieval instruments the pipeline already has.

This is the experiment behind ``docs/experiments/2026-10-19-agentic-rag.md``: instead of running the fixed
sequence (rewrites -> dense search -> RRF -> rerank -> wide/keyword/scene/entity paths -> answer), a local model
chooses which instrument to use, reads what it finds, and writes the answer from the passages it gathered.

The tools wrap existing code, they do not reimplement it:

* ``semantic_search``  dense search over the passage index + the cross-encoder (pipeline's core retrieval)
* ``keyword_search``   BM25 over the same passages (pipeline's ``_keyword_search``)
* ``expand_query``     HyDE, alternative phrasings and grammar correction (pipeline's ``_transform``)
* ``search_scenes``    the scene-summary index (``scenes.scene_collection``)
* ``entity_card``      entity cards: a person's other names, facts and links (``entities.entity_cards_path``)
* ``find_names``       the books' name vocabulary, for misspellings and bare first names
* ``read_passage``     a passage plus its neighbours (reading context, not an index)
* ``read_chapter``     consecutive passages of a chapter, for browsing a narrative
* ``submit_answer``    ends the loop

Every tool returns compact JSON with 8-character passage ids; ``submit_answer`` takes the ids the answer relies on
and the collected passages are labelled ``[E1]``... in that order.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable

import requests

try:
    from .entities import entity_cards_path
    from .observability import observation, update as update_observation
    from .pipeline import (_embedder, _entity_cards, _keyword_index, _keyword_search, _name_pairs, _passage_position,
                           _reranker, _transform, qdrant_client)
    from .resolved_config import ResolvedPipelineConfig
    from .scenes import scene_collection
except ImportError:  # running from app/ inside the container
    from entities import entity_cards_path
    from observability import observation, update as update_observation
    from pipeline import (_embedder, _entity_cards, _keyword_index, _keyword_search, _name_pairs, _passage_position,
                          _reranker, _transform, qdrant_client)
    from resolved_config import ResolvedPipelineConfig
    from scenes import scene_collection


SYSTEM_PROMPT = """You answer questions about Stieg Larsson's Millennium trilogy using a search index of the three books: The Girl with the Dragon Tattoo, The Girl Who Played with Fire and The Girl Who Kicked the Hornet's Nest.

Work in small steps and use the tools. Do not answer from memory or outside knowledge: every claim must come from passages you retrieved.
- Start with a search. Search results flag names the books do not use ("name_hints"); follow those spellings.
- Before answering, make sure the passage you rely on states the answer, not just the topic.
- If a search returns little, change it: expand_query for other phrasings, keyword_search for exact words.
- search_scenes searches summaries of six-passage windows. It is the fastest way to find a conversation, a decision or how something came about, because the summary names who was there and what they did even when the passages alone are ambiguous.
- When a hit looks relevant, read_passage with its neighbours; a single line often means something different in context.
- Keep the passages that actually support the answer.

When you can answer, call submit_answer with:
- answer: a concise answer (2-4 sentences) that uses only what the passages state.
- passage_ids: the 8-character ids of the passages you relied on, most important first.
Cite each factual sentence with the ids in square brackets, exactly as the tools returned them, for example: Salander used an enamel cigarette case to dig herself out [c51aa2b1].
If the books do not contain the answer, call submit_answer saying so, with no ids.

A passage that is only about the topic is not evidence: it must state the answer, and you should read its neighbours before deciding.
You have a limited number of tool calls (about 16). Do not repeat a search that returned the same passages. Prefer four to eight calls over one long one."""

FORCED_ANSWER_PROMPT = "You have reached the step limit. Using only the passages below, call none of the tools and write the final answer now, citing the passage ids in square brackets. If they do not answer the question, say so."


@dataclass(frozen=True)
class AgentSettings:
    model: str = "qwen3:8b"
    max_turns: int = 10
    max_tool_calls: int = 16
    min_tool_calls: int = 3
    timeout_seconds: float = 900.0
    context_length: int = 16384
    num_predict: int = 1200
    think: bool = False
    snippet_chars: int = 300

    def with_model(self, model: str) -> "AgentSettings":
        return AgentSettings(**{**self.__dict__, "model": model})


@dataclass
class AgentState:
    question: str
    collection: str
    config: ResolvedPipelineConfig
    settings: AgentSettings
    started: float
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    tool_calls: int = 0
    turns: int = 0
    nudges: int = 0
    verifications: int = 0
    trace: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})

    def remember(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            short = str(row["id"])[:8]
            if short not in self.evidence:
                self.evidence[short] = row
                self.order.append(short)


def _book_short(book: str | None) -> str:
    if not book:
        return "?"
    if "Dragon" in book:
        return "Dragon Tattoo"
    if "Fire" in book:
        return "Played with Fire"
    if "Hornet" in book:
        return "Hornet's Nest"
    return book


def _row_index(collection: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    rows = _keyword_index(collection)[0]
    return {row["id"]: row for row in rows}, rows


def _resolve_id(collection: str, wanted: str) -> tuple[dict[str, Any] | None, str]:
    """Resolve a full or 8-character id; return (row, error)."""
    wanted = (wanted or "").strip().strip("[]")
    by_id, _ = _row_index(collection)
    if wanted in by_id:
        return by_id[wanted], ""
    matches = [row for key, row in by_id.items() if key.startswith(wanted)] if len(wanted) >= 6 else []
    if len(matches) == 1:
        return matches[0], ""
    if len(matches) > 1:
        return None, f"id {wanted!r} is ambiguous ({len(matches)} passages)"
    return None, f"no passage with id {wanted!r}"


def _name_hints(collection: str, text: str) -> dict[str, list[str]]:
    """Book spellings for capitalised words in a query that the books do not use, or use under another full name."""
    _, words = _name_pairs(collection)
    hints: dict[str, list[str]] = {}
    for token in dict.fromkeys(re.findall(r"\b[A-ZÅÄÖ][\wåäöé-]{2,}\b", text or "")):
        if words.get(token, 0) >= 20:
            continue
        close = difflib.get_close_matches(token, list(words), n=2, cutoff=0.6)
        if close:
            hints[token] = [f"{name} ({words[name]} mentions)" for name in close]
    return hints


def _passage(row: dict[str, Any], chars: int) -> dict[str, Any]:
    text = (row.get("text") or "").replace("\n", " ")
    return {"id": str(row["id"])[:8], "book": _book_short(row.get("book")), "chapter": row.get("chapter"),
            "paragraph": row.get("paragraph"),
            "score": round(float(row["score"]), 3) if row.get("score") is not None else None,
            "text": text[:chars] + ("…" if len(text) > chars else "")}


def _clip(payload: Any, limit: int = 5000) -> str:
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _int(args: dict[str, Any], key: str, default: int, low: int = 1, high: int = 12) -> int:
    try:
        value = int(args.get(key, default))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


# --- tools ---------------------------------------------------------------------------------------------------------

def _tool_semantic_search(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    k = _int(args, "k", 5, 1, 10)
    config = state.config
    qdrant = qdrant_client()
    vector = _embedder(config.embedding_model.name, config.embedding_model.revision).encode(
        query, normalize_embeddings=True, show_progress_bar=False).tolist()
    points = qdrant.query_points(collection_name=state.collection, query=vector, limit=max(30, k * 5), with_payload=True).points
    rows = [dict(point.payload or {}) | {"id": str(point.id)} for point in points]
    if not rows:
        return {"query": query, "hits": []}
    scores = _reranker(config.reranker_model.name, config.reranker_model.revision).predict(
        [(query, row["text"]) for row in rows], show_progress_bar=False)
    for row, score in zip(rows, scores):
        row["score"] = float(score)
    rows.sort(key=lambda row: row["score"], reverse=True)
    rows = rows[:k]
    state.remember(rows)
    return {"query": query, "hits": [_passage(row, state.settings.snippet_chars) for row in rows],
            "name_hints": _name_hints(state.collection, query)}


def _tool_keyword_search(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    k = _int(args, "k", 5, 1, 10)
    rows = _keyword_search(query, state.collection, k)
    if not rows:
        return {"query": query, "hits": [], "note": "no passage shares a content word with this query"}
    for row in rows:
        row["score"] = row["keyword_score"]
    state.remember(rows)
    return {"query": query, "hits": [_passage(row, state.settings.snippet_chars) for row in rows],
            "name_hints": _name_hints(state.collection, query)}


def _tool_expand_query(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or state.question).strip()
    hypothetical, alternatives, corrected = _transform(query, state.config, None)
    return {"query": query, "hypothetical_document": hypothetical, "alternative_phrasings": alternatives,
            "grammar_corrected": corrected,
            "note": "search these phrasings with semantic_search; they are not evidence"}


def _tool_scene_search(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    k = _int(args, "k", 2, 1, 5)
    config = state.config
    name = scene_collection(state.collection, config)
    qdrant = qdrant_client()
    if not qdrant.collection_exists(name):
        return {"error": "the scene index is not built for this collection"}
    vector = _embedder(config.embedding_model.name, config.embedding_model.revision).encode(
        query, normalize_embeddings=True, show_progress_bar=False).tolist()
    points = qdrant.query_points(collection_name=name, query=vector, limit=max(6, k * 2), with_payload=True).points
    if not points:
        return {"query": query, "scenes": []}
    scores = _reranker(config.reranker_model.name, config.reranker_model.revision).predict(
        [(query, point.payload["summary"]) for point in points], show_progress_bar=False)
    ranked = sorted(zip(points, (float(score) for score in scores)), key=lambda pair: pair[1], reverse=True)[:k]
    by_id, _ = _row_index(state.collection)
    scenes = []
    for point, score in ranked:
        members = []
        for member in (point.payload.get("members") or [])[:4]:
            row = by_id.get(member)
            if row:
                members.append({"id": member[:8], "chapter": row.get("chapter"), "paragraph": row.get("paragraph"),
                                "text": (row.get("text") or "")[:110]})
                state.remember([row | {"id": member}])
        scenes.append({"score": round(score, 3), "summary": point.payload.get("summary"), "passages": members})
    return {"query": query, "scenes": scenes}


def _resolve_entity(data: dict[str, Any], name: str) -> str | None:
    cards = {card["key"]: card for card in data["cards"]}
    key = re.sub(r"[’']s$", "", str(name or "").strip().casefold())
    key = data.get("alias", {}).get(key, key)
    if key in cards:
        return key
    words = set(key.split())
    candidates = [other for other in cards if words and words <= set(other.split())]
    if candidates:
        return max(candidates, key=lambda other: cards[other]["mentions"])
    candidates = [other for other in cards if key and key in other]
    if candidates:
        return max(candidates, key=lambda other: cards[other]["mentions"])
    return None


def _tool_entity_card(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name") or "").strip()
    if not name:
        return {"error": "name is required"}
    path = entity_cards_path(state.collection, state.config)
    if not path.exists():
        return {"error": "entity cards are not built for this collection"}
    data = _entity_cards(str(path))
    key = _resolve_entity(data, name)
    if key is None:
        close = difflib.get_close_matches(name.casefold(), [card["key"] for card in data["cards"]], n=4, cutoff=0.6)
        return {"error": f"no entity card for {name!r}", "close_names": close}
    card = next(card for card in data["cards"] if card["key"] == key)
    by_id, _ = _row_index(state.collection)
    rows = [by_id[member] | {"id": member} for member in card.get("members", [])[:6] if member in by_id]
    state.remember(rows)
    links = []
    for edge in data.get("edges", []):
        if key not in (edge.get("from"), edge.get("to")):
            continue
        other = edge.get("to") if edge.get("from") == key else edge.get("from")
        if not other or other == key:
            continue
        links.append({"other_name": other, "relation": edge.get("relation"), "fact": (edge.get("text") or "")[:220],
                      "passage_ids": [str(member)[:8] for member in edge.get("members", [])[:3]]})
    links.sort(key=lambda link: link["relation"] or "")
    return {"name": key, "mentions": card.get("mentions"), "facts": card.get("facts", [])[:8],
            "links": links[:10], "passage_ids": [str(row["id"])[:8] for row in rows[:6]],
            "note": "passage_ids are the passages the card was extracted from"}


def _tool_find_names(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name") or "").strip()
    if not name:
        return {"error": "name is required"}
    pairs, words = _name_pairs(state.collection)
    close = difflib.get_close_matches(name, list(words), n=6, cutoff=0.55)
    matches = []
    for word in close:
        full, count, total = pairs.get(word, (word, 0, 0))
        matches.append({"book_spelling": word, "full_name": full, "mentions": words[word],
                        "as_full_name": count, "same": word.casefold() == name.casefold()})
    return {"name": name, "matches": matches,
            "note": "the books spell names this way; search with a full_name or book_spelling"}


def _tool_read_passage(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    wanted = str(args.get("id") or "")
    row, error = _resolve_id(state.collection, wanted)
    if row is None:
        return {"error": error}
    before = _int(args, "before", 1, 0, 3)
    after = _int(args, "after", 1, 0, 3)
    _, rows = _row_index(state.collection)
    section = [item for item in rows if item.get("book_file") == row.get("book_file") and item.get("section") == row.get("section")]
    section.sort(key=_passage_position)
    position = next((index for index, item in enumerate(section) if item["id"] == row["id"]), None)
    window = section[max(0, (position or 0) - before): (position or 0) + after + 1] if position is not None else [row]
    state.remember(window)
    return {"passage": _passage(row, 1600),
            "neighbours": [_passage(item, 500) for item in window if item["id"] != row["id"]]}


def _tool_read_chapter(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    book = str(args.get("book") or "").strip()
    chapter = str(args.get("chapter") or "").strip()
    if not book or not chapter:
        return {"error": "book and chapter are required"}
    offset = _int(args, "offset", 0, 0, 200)
    limit = _int(args, "limit", 8, 1, 12)
    _, rows = _row_index(state.collection)
    books = sorted({row.get("book") or "" for row in rows})
    matched_books = [title for title in books if book.casefold() in title.casefold()]
    if len(matched_books) != 1:
        return {"error": f"book {book!r} matched {len(matched_books)} books", "books": books}
    title = matched_books[0]
    in_book = [row for row in rows if row.get("book") == title]
    chapters = sorted({row.get("chapter") or "" for row in in_book})
    if re.fullmatch(r"\d+", chapter):
        matched = [name for name in chapters if re.match(rf"CHAPTER\s+{chapter}\b", name, re.I)]
    else:
        matched = [name for name in chapters if chapter.casefold() in name.casefold()]
    if len(matched) != 1:
        return {"error": f"chapter {chapter!r} matched {len(matched)} chapters", "chapters": chapters}
    chapter_name = matched[0]
    paragraphs = sorted((row for row in in_book if row.get("chapter") == chapter_name), key=_passage_position)
    window = paragraphs[offset: offset + limit]
    state.remember(window)
    return {"book": title, "chapter": chapter_name, "total_paragraphs": len(paragraphs), "offset": offset,
            "passages": [_passage(row, 500) for row in window],
            "note": "call again with a larger offset to continue"}


def _tool_submit_answer(state: AgentState, args: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    answer = str(args.get("answer") or "").strip()
    if not answer:
        return {"error": "answer is required"}, False
    raw_ids = args.get("passage_ids") or []
    if isinstance(raw_ids, str):
        raw_ids = re.split(r"[\s,]+", raw_ids)
    ids: list[str] = []
    unknown: list[str] = []
    for wanted in raw_ids:
        text = str(wanted).strip().strip("[]")
        if not text:
            continue
        short = text[:8].casefold()
        if short in state.evidence:
            if short not in ids:
                ids.append(short)
        else:
            unknown.append(text)
    if not state.evidence and not ids:
        return {"error": "no evidence yet: search the books before answering"}, False
    if state.tool_calls < state.settings.min_tool_calls:
        return {"error": f"investigate more before answering: at least {state.settings.min_tool_calls} tool calls "
                         f"(you made {state.tool_calls}); a passage that is only on topic is not evidence"}, False
    if unknown:
        return {"error": f"unknown passage ids: {unknown}. Use the 8-character ids the tools returned."}, False
    labels = {short: f"[E{position}]" for position, short in enumerate(ids, 1)}
    cited = re.findall(r"\[([0-9a-fA-F]{8})\]", answer)

    def replace(match: re.Match[str]) -> str:
        short = match.group(1).casefold()
        return labels.get(short, match.group(0))

    rewritten = re.sub(r"\[([0-9a-fA-F]{8})\]", replace, answer)
    return {"answer": rewritten, "raw_answer": answer, "passage_ids": ids,
            "cited_ids": list(dict.fromkeys(item.casefold() for item in cited)),
            "uncited": bool(ids) and not any(item.casefold() in ids for item in cited)}, True


# --- loop ----------------------------------------------------------------------------------------------------------

def _tool_specs() -> list[dict[str, Any]]:
    def spec(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {"type": "function", "function": {"name": name, "description": description,
                                                 "parameters": {"type": "object", "properties": properties,
                                                                "required": required}}}

    query = {"type": "string", "description": "words to search for"}
    count = {"type": "integer", "description": "how many results (default 5, max 10)"}
    return [
        spec("semantic_search", "Dense search over the books' passages; returns the best matches after cross-encoder reranking.",
             {"query": query, "k": count}, ["query"]),
        spec("keyword_search", "BM25 search for the exact content words in a query. Best for a quoted phrase, a nickname or a rare term.",
             {"query": query, "k": count}, ["query"]),
        spec("expand_query", "Ask the books' language model for a hypothetical answer passage, three alternative phrasings and a grammar correction. Search the results with semantic_search.",
             {"query": {"type": "string", "description": "question to expand (default: the user's question)"}}, []),
        spec("search_scenes", "Search summaries of six-passage windows. Use it to find a conversation or an explanation spread over several passages, or dialogue that never names the people. Returns the summary and its passage ids.",
             {"query": query, "k": {"type": "integer", "description": "how many scenes (default 2, max 5)"}}, ["query"]),
        spec("entity_card", "A person's entity card: how the books spell the name, facts about them, and their links to other names and things (aliases, nicknames, belongings).",
             {"name": {"type": "string", "description": "person or thing name"}}, ["name"]),
        spec("find_names", "Suggest how the books spell a name, including close misspellings and full names for a first name.",
             {"name": {"type": "string", "description": "name as written in the question"}}, ["name"]),
        spec("read_passage", "Read one passage in full, with the passages before and after it.",
             {"id": {"type": "string", "description": "8-character passage id"},
              "before": {"type": "integer", "description": "passages before (0-3, default 1)"},
              "after": {"type": "integer", "description": "passages after (0-3, default 1)"}}, ["id"]),
        spec("read_chapter", "Browse a chapter: consecutive passages in reading order, by book and chapter number or name.",
             {"book": {"type": "string", "description": "Dragon Tattoo, Played with Fire or Hornet's Nest"},
              "chapter": {"type": "string", "description": "chapter number, e.g. 17"},
              "offset": {"type": "integer", "description": "first paragraph (default 0)"},
              "limit": {"type": "integer", "description": "paragraphs to return (default 8, max 12)"}}, ["book", "chapter"]),
        spec("submit_answer", "Finish: give the final answer and the passages it relies on.",
             {"answer": {"type": "string", "description": "the answer, citing passage ids in square brackets"},
              "passage_ids": {"type": "array", "items": {"type": "string"},
                              "description": "8-character ids of the passages the answer relies on, most important first"}},
             ["answer"]),
    ]


def _compact(messages: list[dict[str, Any]], keep: int = 6, budget: int = 22000) -> None:
    """Drop the body of older tool results when the conversation grows; their ids stay for read_passage."""
    tool_indexes = [index for index, message in enumerate(messages) if message.get("role") == "tool"]
    total = sum(len(message.get("content") or "") for message in messages)
    if total <= budget:
        return
    for index in tool_indexes[:-keep]:
        content = messages[index].get("content") or ""
        ids = list(dict.fromkeys(re.findall(r'"id": "([0-9a-f]{8})"', content)))
        messages[index] = {"role": "tool", "content": json.dumps(
            {"compacted": True, "ids": ids[:8], "note": "earlier result compacted to save context; read_passage can reopen an id"})}


def _ollama_chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, settings: AgentSettings) -> dict[str, Any]:
    base = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    payload: dict[str, Any] = {"model": settings.model, "messages": messages, "stream": False,
                               "think": settings.think,
                               "options": {"temperature": 0, "num_ctx": settings.context_length,
                                           "num_predict": settings.num_predict}}
    if tools:
        payload["tools"] = tools
        _compact(messages)
    response = requests.post(base + "/api/chat", json=payload, timeout=(10, 600))
    response.raise_for_status()
    return response.json()


def _parse_text_tool(content: str) -> tuple[str, dict[str, Any]] | None:
    """A tool call printed as JSON when the model does not use native tool calls."""
    if not content:
        return None
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    for candidate in (text, *re.findall(r"\{.*\}", text, re.S)):
        try:
            value = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and isinstance(value.get("tool"), str):
            arguments = value.get("arguments", value.get("args", {}))
            return value["tool"], arguments if isinstance(arguments, dict) else {}
        if isinstance(value, dict) and isinstance(value.get("name"), str) and ("arguments" in value or "args" in value):
            arguments = value.get("arguments", value.get("args", {}))
            return value["name"], arguments if isinstance(arguments, dict) else {}
    return None


def _run_tool(state: AgentState, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    tools = {
        "semantic_search": _tool_semantic_search,
        "keyword_search": _tool_keyword_search,
        "expand_query": _tool_expand_query,
        "search_scenes": _tool_scene_search,
        "entity_card": _tool_entity_card,
        "find_names": _tool_find_names,
        "read_passage": _tool_read_passage,
        "read_chapter": _tool_read_chapter,
    }
    if name == "submit_answer":
        return _tool_submit_answer(state, args)
    if name not in tools:
        return {"error": f"unknown tool {name!r}", "tools": sorted([*tools, "submit_answer"])}, False
    return tools[name](state, args), False


def _verify_submission(state: AgentState, answer: str, ids: list[str]) -> tuple[bool, str]:
    """Ask the model whether the cited passages actually state the proposed answer (a topic match is not support)."""
    blocks = []
    by_section: dict[tuple, list[dict[str, Any]]] = {}
    _, rows = _row_index(state.collection)
    for row in rows:
        by_section.setdefault((row.get("book_file"), row.get("section")), []).append(row)
    for position, short in enumerate(ids, 1):
        row = state.evidence.get(short)
        if not row:
            continue
        section = sorted(by_section.get((row.get("book_file"), row.get("section")), [row]), key=_passage_position)
        index = next((number for number, item in enumerate(section) if item["id"] == row["id"]), None)
        context = section[max(0, (index or 0) - 1): (index or 0) + 2] if index is not None else [row]
        blocks.append(f"[E{position}] id={short} | {row.get('book')} | {row.get('chapter')}\n" + "\n".join(
            f"paragraph {item.get('paragraph')}: {(item.get('text') or '')[:700]}" for item in context))
    prompt = (f"Question: {state.question}\n\nProposed answer: {answer}\n\nPassages:\n" + "\n\n".join(blocks)
              + "\n\nDoes at least one passage state the main answer to the question, even if worded differently? "
                "A passage that only mentions the topic, or states the opposite, is not support. A passage that only says "
                "'he' or 'she', or that could be about another person, is not support either: the passage must name or "
                "unambiguously identify the person the question asks about. Additional background the passages do not "
                "mention is not a failure. Reply with JSON only: "
                '{"supported": true or false, "reason": "one sentence"}')
    try:
        reply = _ollama_chat([{"role": "system", "content": "You check whether evidence supports an answer."},
                              {"role": "user", "content": prompt}], None, state.settings)
        content = ((reply.get("message") or {}).get("content") or "").strip()
        state.usage["prompt_tokens"] += int(reply.get("prompt_eval_count") or 0)
        state.usage["completion_tokens"] += int(reply.get("eval_count") or 0)
        match = re.search(r"\{.*\}", content, re.S)
        verdict = json.loads(match.group(0)) if match else {}
        return bool(verdict.get("supported", True)), str(verdict.get("reason") or "")
    except (ValueError, TypeError, KeyError, AttributeError):
        return True, "verifier reply could not be parsed"
    except Exception as exc:  # verification must not end the run
        return True, f"verifier failed: {type(exc).__name__}"


def _evidence_digest(state: AgentState, limit: int = 14) -> str:
    rows = [state.evidence[short] for short in state.order[:limit]]
    blocks = []
    for position, row in enumerate(rows, 1):
        blocks.append(f"[{row['id'][:8]}] {row.get('book')} | {row.get('chapter')} | paragraph {row.get('paragraph')}\n"
                      f"{(row.get('text') or '')[:400]}")
    return "\n\n".join(blocks)


def _forced_answer(state: AgentState, messages: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = f"{FORCED_ANSWER_PROMPT}\n\nQuestion: {state.question}\n\nPassages found:\n{_evidence_digest(state)}"
    reply = _ollama_chat([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}], None, state.settings)
    message = reply.get("message") or {}
    content = (message.get("content") or "").strip()
    state.usage["prompt_tokens"] += int(reply.get("prompt_eval_count") or 0)
    state.usage["completion_tokens"] += int(reply.get("eval_count") or 0)
    ids = [short.casefold() for short in re.findall(r"\[([0-9a-fA-F]{8})\]", content) if short.casefold() in state.evidence]
    return _final(state, content, list(dict.fromkeys(short.casefold() for short in ids)), stopped="budget")


def _final(state: AgentState, answer: str, ids: list[str], *, stopped: str, raw_answer: str | None = None) -> dict[str, Any]:
    labels = {short: f"[E{position}]" for position, short in enumerate(ids, 1)}
    rewritten = re.sub(r"\[([0-9a-fA-F]{8})\]", lambda match: labels.get(match.group(1).casefold(), match.group(0)), answer)
    cited = [match.group(1) for match in re.finditer(r"\[(E\d+)\]", rewritten)]
    return {"question": state.question, "answer": rewritten, "raw_answer": raw_answer if raw_answer is not None else answer,
            "passage_ids": ids, "citations": list(dict.fromkeys(cited)),
            "evidence": [state.evidence[short] | {"agent_label": f"E{position}"} for position, short in enumerate(ids, 1)],
            "collected_passages": len(state.evidence), "turns": state.turns, "tool_calls": state.tool_calls,
            "trace": state.trace, "model": state.settings.model, "usage": state.usage,
            "latency_seconds": round(time.perf_counter() - state.started, 2), "stopped": stopped}


def run_agent(question: str, collection: str, config: ResolvedPipelineConfig | None = None, *,
              settings: AgentSettings | None = None, on_event: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Answer ``question`` with the model choosing among the tools; returns the answer, its evidence and the trace."""
    if not question.strip():
        raise ValueError("question must not be blank")
    config = config or ResolvedPipelineConfig()
    settings = settings or AgentSettings(model=config.generation_model.name)
    state = AgentState(question=question, collection=collection, config=config, settings=settings,
                       started=time.perf_counter())
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT},
                                      {"role": "user", "content": question}]
    tool_specs = _tool_specs()

    def emit(event: dict[str, Any]) -> None:
        if on_event:
            on_event(event)

    with observation("agent run", input={"question": question, "model": settings.model}) as root:
        for turn in range(1, settings.max_turns + 1):
            state.turns = turn
            if time.perf_counter() - state.started > settings.timeout_seconds:
                emit({"type": "timeout"})
                result = _forced_answer(state, messages)
                update_observation(root, output=result)
                return result
            started = time.perf_counter()
            with observation(f"agent turn {turn}", as_type="generation", input=messages[-2:], model=settings.model) as turn_obs:
                reply = _ollama_chat(messages, tool_specs, settings)
                message = reply.get("message") or {}
                update_observation(turn_obs, output={"content": (message.get("content") or "")[:2000],
                                                     "tool_calls": message.get("tool_calls")})
            state.usage["prompt_tokens"] += int(reply.get("prompt_eval_count") or 0)
            state.usage["completion_tokens"] += int(reply.get("eval_count") or 0)
            content = (message.get("content") or "").strip()
            calls = list(message.get("tool_calls") or [])
            if not calls:
                parsed = _parse_text_tool(content)
                if parsed:
                    calls = [{"function": {"name": parsed[0], "arguments": parsed[1]}}]
            emit({"type": "turn", "turn": turn, "seconds": round(time.perf_counter() - started, 2),
                  "content": content[:1000], "tool_calls": [call.get("function", {}).get("name") for call in calls]})
            if not calls:
                # A final answer without submit_answer is accepted only when it cites collected passage ids.
                ids = [short.casefold() for short in re.findall(r"\[([0-9a-fA-F]{8})\]", content)
                       if short.casefold() in state.evidence]
                ids = list(dict.fromkeys(ids))
                if ids and state.verifications < 2:
                    state.verifications += 1
                    supported, reason = _verify_submission(state, content, ids)
                    emit({"type": "verify", "supported": supported, "reason": reason})
                    if not supported:
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "tool", "content": _clip({
                            "error": "the answer is not supported by the cited passages", "reason": reason,
                            "note": "search again: find a passage that names the person and states the answer, then submit"})})
                        continue
                if not ids and state.nudges < 2:
                    state.nudges += 1
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": (
                        "You did not call a tool. If you have enough evidence, call submit_answer with the answer and the "
                        "8-character passage_ids it relies on; otherwise continue searching.")})
                    emit({"type": "nudge", "turn": turn})
                    continue
                result = _final(state, content, ids, stopped="content")
                update_observation(root, output=result)
                return result
            messages.append({"role": "assistant", "content": content,
                             "tool_calls": [{"id": call.get("id"), "function": {"name": call.get("function", {}).get("name"),
                                                                               "arguments": call.get("function", {}).get("arguments", {})}}
                                            for call in calls]})
            for call in calls:
                function = call.get("function") or {}
                name = str(function.get("name") or "")
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = {}
                if not isinstance(arguments, dict):
                    arguments = {}
                state.tool_calls += 1
                started = time.perf_counter()
                with observation(f"tool: {name}", as_type="tool", input=arguments) as tool_obs:
                    try:
                        payload, stop = _run_tool(state, name, arguments)
                    except Exception as exc:  # a tool failure is an observation the agent can recover from
                        payload, stop = {"error": f"{type(exc).__name__}: {exc}"}, False
                    update_observation(tool_obs, output=payload)
                seconds = round(time.perf_counter() - started, 2)
                state.trace.append({"tool": name, "arguments": arguments, "seconds": seconds,
                                    "error": payload.get("error") if isinstance(payload, dict) else None,
                                    "result_ids": [hit.get("id") for hit in (payload.get("hits") or [])] if isinstance(payload, dict) else []})
                emit({"type": "tool", "name": name, "arguments": arguments, "seconds": seconds,
                      "error": payload.get("error") if isinstance(payload, dict) else None})
                if stop:
                    if state.verifications < 2 and payload["passage_ids"]:
                        state.verifications += 1
                        supported, reason = _verify_submission(state, payload["raw_answer"], payload["passage_ids"])
                        emit({"type": "verify", "supported": supported, "reason": reason})
                        if not supported:
                            messages.append({"role": "tool", "content": _clip({
                                "error": "the answer is not supported by the cited passages",
                                "reason": reason,
                                "note": "search again: find a passage that states the answer, then submit a corrected answer"})})
                            continue
                    result = _final(state, payload["answer"], payload["passage_ids"], stopped="submit",
                                    raw_answer=payload.get("raw_answer"))
                    result["submitted"] = payload
                    update_observation(root, output=result)
                    return result
                messages.append({"role": "tool", "content": _clip(payload)})
                if state.tool_calls >= settings.max_tool_calls:
                    emit({"type": "tool_budget"})
                    result = _forced_answer(state, messages)
                    update_observation(root, output=result)
                    return result
        emit({"type": "turn_budget"})
        result = _forced_answer(state, messages)
        update_observation(root, output=result)
        return result
