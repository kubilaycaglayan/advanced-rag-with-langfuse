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
    from .entities import _cache_path as entity_cache_path, entity_cards_path
    from .evaluation import is_explicit_abstention
    from .observability import observation, update as update_observation
    from .pipeline import (_embedder, _entity_cards, _keyword_index, _keyword_search, _entity_anchors, _keywords, _moment_scene_hits,
                           _name_pairs, _passage_position, _reranker, _transform, qdrant_client)
    from .resolved_config import ResolvedPipelineConfig
    from .scenes import scene_collection
except ImportError:  # running from app/ inside the container
    from entities import _cache_path as entity_cache_path, entity_cards_path
    from evaluation import is_explicit_abstention
    from observability import observation, update as update_observation
    from pipeline import (_embedder, _entity_cards, _keyword_index, _keyword_search, _entity_anchors, _keywords, _moment_scene_hits,
                          _name_pairs, _passage_position, _reranker, _transform, qdrant_client)
    from resolved_config import ResolvedPipelineConfig
    from scenes import scene_collection


SYSTEM_PROMPT = """You answer questions about Stieg Larsson's Millennium trilogy using a search index of the three books: The Girl with the Dragon Tattoo, The Girl Who Played with Fire and The Girl Who Kicked the Hornet's Nest.

Work in small steps and use the tools. Do not answer from memory or outside knowledge: every claim must come from passages you retrieved.
- Start with a search. Search results flag names the books do not use ("name_hints"); follow those spellings. If find_names gives a likely person, the question is about that person: do not answer that the character does not exist.
- Before answering, make sure the passage you rely on states the answer, not just the topic.
- If a search returns little, change it: expand_query for other phrasings, keyword_search for exact words.
- search_scenes searches summaries of six-passage windows. It is the fastest way to find a conversation, a decision or how something came about, because the summary names who was there and what they did even when the passages alone are ambiguous. Pass `people` when the question names two people. Each scene has a scene_id; when its four snippets do not contain the detail, call read_scene (or search_scenes with full=true) to read every member passage in order.
- For a question about a detail at one moment ("what did she say when she saw him in the kitchen", "what was she wearing when they met"), call scene_moment: it writes the situation out and returns the scene that shows it, which is often the only place the detail appears. Read the scene list it returns too: the chosen scene can be the memory of the event while the dialogue is in another scene whose summary names it.
- Before concluding that a detail is not in the books, search the words it would appear with in the passage: keyword_search for the distinctive nouns and verbs ("loosened the gun", "kitchen bench", a remembered phrase), not only the question's phrasing. A scene summary is not evidence; the passage is.
- find_connections tells you what the cards say links two people: how they met, what one did for the other, documents or names between them. Use it for "how did X know Y" or "what connects X and Y" before concluding that the books do not say.
- When a hit looks relevant, read_passage with its neighbours; a single line often means something different in context. A scene summary is a paraphrase, not evidence: answer in the words of the passage (the summary's "pinned him to the floor" may be "nailed his feet to the floor" in the passage).
- Keep the passages that actually support the answer.

When you can answer, call submit_answer with:
- answer: a concise answer (2-4 sentences) that uses only what the passages state. Answer the question directly: state the fact first, then at most one supporting sentence. If the question asks for a list, give the list, one line per item. Do not include notes, reasoning, book-metadata doubts or a transcript of your search in the answer.
- passage_ids: the 8-character ids of the passages you relied on, most important first.
Cite each factual sentence with the ids in square brackets, exactly as the tools returned them, for example: Salander used an enamel cigarette case to dig herself out [c51aa2b1].
Use names exactly as the passages write them: if a passage says only "Göransson" or "Niedermann", do not add a first name from memory.
Give one answer, not alternative answers for different readings of the question. If the place has another name in the passages (a factory can be a brickworks), say so in the same answer and keep going with the event those passages describe.
For a broad question (a summary, a list, a "top 10", or why someone did something), do not abstain because the books never use the question's word: answer from the passages you found, naming the events or people. A short structured summary is a good answer. If the question asks why, give the reason the passages show even when no sentence says "because".
If the books do not contain the answer, call submit_answer saying so, with no ids.

A passage that is only about the topic is not evidence: it must state the answer, and you should read its neighbours before deciding.
Before submit_answer, check the question's parts one by one (who, what, where, when, why, how many) and make sure a passage states each. If one part is missing, search for it instead of answering partially. Some questions assume an event that the books contradict (that someone is dead, that something was never found): check the premise and correct it.
When the books first describe a death, a crime or a disappearance one way, look for the later passage that reveals what really happened (who was there, who did it); answer with the true account, and with the official one only as contrast. For a death or a crime, always ask who else was present and call true_account with that person: it searches for the other person doing the event ("Harriet drowned her father"), which is a different scene from the official account.
A "what happened at a place" question is a sequence, not one find: cover arrival, discovery, confrontation and outcome. After the first hit, open the scene or search again with the person who was confronted there; do not stop at the first body or clue.
Questions of the form "how did X know/learn about Y", "how did X and Y meet" or "what connects X and Y" are answered by the event that first brought them together: a document one wrote about the other, a person who introduced them, a meeting. If the passages show X reading or receiving something Y wrote, or someone telling X about Y, that is the answer even if the words "learned" or "knew" never appear. State it plainly instead of saying the books do not say.
You have a limited number of tool calls (about 16). Do not repeat a search that returned the same passages. Prefer four to eight calls over one long one."""

FORCED_ANSWER_PROMPT = "You have reached the step limit. Using only the passages below, call none of the tools and write the final answer now, citing the passage ids in square brackets. If they do not answer the question, say so."


@dataclass(frozen=True)
class AgentSettings:
    model: str = "qwen3:8b"
    max_turns: int = 10
    max_tool_calls: int = 16
    min_tool_calls: int = 4
    timeout_seconds: float = 900.0
    context_length: int = 16384
    num_predict: int = 1600
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
    asked: str = ""
    name_notes: list[dict[str, str]] = field(default_factory=list)
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    tool_calls: int = 0
    turns: int = 0
    nudges: int = 0
    verifications: int = 0
    resolved_names: set[str] = field(default_factory=set)
    coverage_checks: int = 0
    focus: list[str] = field(default_factory=list)
    speech_hint: dict[str, str] | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})

    def remember(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            short = str(row["id"])[:8]
            if short not in self.evidence:
                self.evidence[short] = row
                self.order.append(short)

    def focus_on(self, rows: list[dict[str, Any]]) -> None:
        """Passages a tool read on purpose: these stay in front of the answer and the forced-answer digest."""
        for row in rows:
            short = str(row["id"])[:8]
            if short not in self.focus:
                self.focus.append(short)


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


def _scene_member(row: dict[str, Any], chars: int) -> dict[str, Any]:
    """One passage of a scene: reading order and ids, without the ranking fields search results carry."""
    text = (row.get("text") or "").replace("\n", " ")
    return {"id": str(row["id"])[:8], "book": _book_short(row.get("book")), "chapter": row.get("chapter"),
            "paragraph": row.get("paragraph"), "text": text[:chars] + ("…" if len(text) > chars else "")}


def _scene_member_rows(collection: str, members: list[str]) -> list[dict[str, Any]]:
    """The scene's passages in reading order (a window is stored in order, but never trust storage order)."""
    by_id, _ = _row_index(collection)
    rows = [by_id[member] | {"id": member} for member in members if member in by_id]
    return sorted(rows, key=_passage_position)


def _scene_payload(state: "AgentState", point: Any, score: float, *, full: bool) -> dict[str, Any]:
    """A scene as the agent sees it: compact by default, every member at full length when asked.

    The compact form keeps the first four 110-character snippets (the old payload) and adds the scene id and all
    member ids, so the agent can open the scene instead of guessing. The full form caps at six members of 500
    characters, the size of one scene window and the per-call token budget.
    """
    members = [str(member) for member in (point.payload.get("members") or [])]
    rows = _scene_member_rows(state.collection, members)
    state.remember(rows)
    if full:
        state.focus_on(rows)
    shown = rows[:6] if full else rows[:4]
    return {"scene_id": str(point.id)[:8], "score": round(score, 3), "summary": point.payload.get("summary"),
            "passage_ids": [member[:8] for member in members[:6]],
            "passages": [_scene_member(row, 500 if full else 110) for row in shown],
            "more_passages": max(0, len(rows) - len(shown)) if full else 0}


def _semantic_rows(state: "AgentState", query: str, k: int) -> list[dict[str, Any]]:
    """Dense search plus cross-encoder rerank; rows carry the full passage id."""
    config = state.config
    vector = _embedder(config.embedding_model.name, config.embedding_model.revision).encode(
        query, normalize_embeddings=True, show_progress_bar=False).tolist()
    points = qdrant_client().query_points(collection_name=state.collection, query=vector,
                                          limit=max(30, k * 5), with_payload=True).points
    rows = [dict(point.payload or {}) | {"id": str(point.id)} for point in points]
    if not rows:
        return []
    scores = _reranker(config.reranker_model.name, config.reranker_model.revision).predict(
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
    vector = _embedder(config.embedding_model.name, config.embedding_model.revision).encode(
        query, normalize_embeddings=True, show_progress_bar=False).tolist()
    points = qdrant.query_points(collection_name=name, query=vector, limit=max(20, k * 4), with_payload=True).points
    if not points:
        return [], ""
    scores = _reranker(config.reranker_model.name, config.reranker_model.revision).predict(
        [(query, point.payload["summary"]) for point in points], show_progress_bar=False)
    ranked = sorted(zip(points, (float(score) for score in scores)), key=lambda pair: pair[1], reverse=True)
    return ranked[:k], ""


def _scene_lookup(collection: str, config: ResolvedPipelineConfig, wanted: str) -> tuple[Any | None, str]:
    """Resolve a scene id (full or 8-character prefix) against the scene index."""
    wanted = (wanted or "").strip().strip("[]")
    if len(wanted) < 6:
        return None, f"scene id {wanted!r} is too short"
    name = scene_collection(collection, config)
    qdrant = qdrant_client()
    if not qdrant.collection_exists(name):
        return None, "the scene index is not built for this collection"
    matches, offset = [], None
    while True:
        batch, offset = qdrant.scroll(collection_name=name, limit=1000, offset=offset, with_payload=True)
        matches += [point for point in batch if str(point.id).startswith(wanted)]
        if offset is None or len(matches) > 1:
            break
    if len(matches) == 1:
        return matches[0], ""
    if len(matches) > 1:
        return None, f"scene id {wanted!r} is ambiguous ({len(matches)} scenes)"
    return None, f"no scene with id {wanted!r}"


def _clip(payload: Any, limit: int = 9000) -> str:
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
    rows = _semantic_rows(state, query, k)
    if not rows:
        return {"query": query, "hits": []}
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
    people = args.get("people") or []
    if isinstance(people, str):
        people = [people]
    names = [_person_full_name(state.collection, str(person).strip()) for person in people if str(person).strip()]
    if names:
        query = " ".join([*names, query]).strip()
    if not query:
        return {"error": "query or people is required"}
    k = _int(args, "k", 2, 1, 5)
    full = bool(args.get("full"))
    ranked, error = _scene_points(state, query, k)
    if error:
        return {"error": error}
    if not ranked:
        return {"query": query, "scenes": []}
    scenes = [_scene_payload(state, point, score, full=full) for point, score in ranked]
    return {"query": query, "people": names, "scenes": scenes,
            "note": "pass a scene_id to read_scene for every member passage in reading order"}


def _tool_read_scene(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    wanted = str(args.get("scene_id") or args.get("id") or "")
    point, error = _scene_lookup(state.collection, state.config, wanted)
    if point is None:
        return {"error": error}
    rows = _scene_member_rows(state.collection, [str(member) for member in (point.payload.get("members") or [])])
    state.remember(rows)
    state.focus_on(rows)
    return {"scene_id": str(point.id)[:8], "summary": point.payload.get("summary"),
            "passages": [_scene_member(row, 500) for row in rows[:6]],
            "more_passages": max(0, len(rows) - 6),
            "note": "these passages are evidence; cite the ones the answer relies on"}


def _alias_variants(state: AgentState, moment: str) -> list[str]:
    """The moment with a person's nickname in place of their name ('Mikael Blomkvist' -> 'Kalle Fucking Blomkvist').

    Dialogue and interior monologue use the nickname even when the question uses the legal name; the scene summary
    follows the passage, so the nickname is often the word that finds the scene.
    """
    path = entity_cards_path(state.collection, state.config)
    if not path.exists():
        return []
    data = _entity_cards(str(path))
    cards = {card["key"]: card for card in data.get("cards", [])}
    alias = data.get("alias", {})
    variants = []
    for key in sorted(_entity_anchors(moment, data), key=lambda name: data.get("mentions", {}).get(name, 0)):
        display = _display_name(key)
        if not re.search(rf"\b{re.escape(display)}\b", moment, re.I):
            continue
        for edge in data.get("edges", []):
            left = alias.get(edge.get("from"), edge.get("from"))
            right = alias.get(edge.get("to"), edge.get("to"))
            if key not in (left, right):
                continue
            if not re.search(r"nickname|name used|false identity|alias|real name|known as", edge.get("relation") or "", re.I):
                continue
            other = right if left == key else left
            if other == key or other not in cards or cards[other].get("mentions", 0) < 3:
                continue
            alias_name = _display_name(other)
            if alias_name.casefold() in moment.casefold():
                continue
            variants.append(re.sub(rf"\b{re.escape(display)}\b", alias_name, moment, flags=re.I))
    return list(dict.fromkeys(variants))[:5]


def _moment_core(moment: str) -> str:
    """The event without the detail clause: scene summaries match 'Salander saw Blomkvist in the kitchen', not the
    question's whole 'when she was severely wounded' tail."""
    core = re.split(r"\b(?:when|while|after|before|because|as soon as)\b", moment, maxsplit=1, flags=re.I)[0]
    core = core.split(" and ")[0]
    core = core.strip(" ,.;:—-")
    return core if len(core.split()) >= 4 else ""


def _tool_scene_moment(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    """The pipeline's moment path: write the situation out, let the model choose the scene, return its passages.

    The scene whose summary matches the moment's words is also listed, and the moment is searched again with its
    detail clause stripped and with a person's nickname: the chosen scene can be the memory of the event while the
    dialogue lives in another one.
    """
    question = str(args.get("question") or state.question).strip()
    if not question:
        return {"error": "question is required"}
    evidence = [row for short in state.order if (row := state.evidence.get(short))]
    present = {str(row["id"]) for row in evidence if row.get("id")}
    rows, moment = _moment_scene_hits(question, state.config, state.collection, qdrant_client(), evidence, present, None)
    scenes: dict[str, tuple[Any, float]] = {}
    if moment:
        core = _moment_core(moment)
        queries = [moment, core, *_alias_variants(state, moment), *_alias_variants(state, core)]
        for query in dict.fromkeys(query for query in queries if query):
            ranked, error = _scene_points(state, query, 3)
            if error:
                return {"error": error}
            for point, score in ranked:
                current = scenes.get(str(point.id))
                if current is None or score > current[1]:
                    scenes[str(point.id)] = (point, score)
    listing = [{"scene_id": str(point.id)[:8], "score": round(score, 3), "summary": point.payload.get("summary"),
                "passage_ids": [str(member)[:8] for member in (point.payload.get("members") or [])[:6]]}
               for point, score in sorted(scenes.values(), key=lambda pair: pair[1], reverse=True)[:6]]
    if not rows:
        return {"question": question, "moment": moment, "passages": [], "scenes": listing,
                "note": "no scene was chosen for the moment itself; read_scene one of the scenes above if its summary "
                        "names the detail"
                        if listing else "no scene showed this moment; search its words with semantic_search or keyword_search"}
    state.remember(rows)
    state.focus_on(rows)
    return {"question": question, "moment": moment, "scene_summary": rows[0].get("scene_summary"),
            "passages": [_passage(row, 500) for row in rows[:8]],
            "more_passages": max(0, len(rows) - 8), "scenes": listing,
            "note": "the chosen scene's passages are in reading order. If a summary above names the detail, read_scene "
                    "it: the detail may be in that scene rather than the chosen one."}


# --- true account: the event behind the official story -----------------------------------------------------------------
#
# When the books first describe a death, a crime or a disappearance, that account is often incomplete (an accident, a
# quarrel, a body found). The later reveal names the person who was there and what they did. The queries below are
# shaped like that reveal ("Harriet drowned her father"), not like the official account ("how Gottfried died"), because
# the scene index and the cross-encoder both match the reveal's words and the full names drown the sentence in noise.

_RELATION_WORDS = re.compile(r"\b(daughter|son|father|mother|sister|brother|wife|husband|spouse|married|child|sibling)\b", re.I)
_DEATH_WORDS = re.compile(r"\b(died?|death|dead|deceased)\b", re.I)
_EVENT_WORDS = re.compile(r"\b(died?|death|dead|killed|murder\w*|drown\w*|shot|strangl\w*|poison\w*|hang\w*|burn\w*|"
                          r"stab\w*|beat\w*|beaten|disappear\w*|suicid\w*|accident\w*|confront\w*|attack\w*|fight\w*|"
                          r"nail gun|factory|brickworks)\b", re.I)
_REVEAL_CUES = re.compile(r"\b(kill\w*|murder\w*|drown\w*|shot|strangl\w*|stab\w*|poison\w*|held (?:him|her) under|"
                          r"push\w*|confess\w*|admit\w*|reveal\w*|attack\w*|fight\w*|nail gun|pinned|pinning)\b", re.I)
_OFFICIAL_CUES = re.compile(r"\b(accident\w*|officially|believed|supposed\w*|rumou?r\w*|assumed|presumed|allegedly|"
                            r"fell|falling|slipped|rowing boat)\b", re.I)
_INVERSE_ROLE = {"daughter": "parent", "son": "parent", "father": "child", "mother": "child",
                 "sister": "sibling", "brother": "sibling", "wife": "spouse", "husband": "spouse",
                 "married": "spouse", "child": "parent", "sibling": "sibling"}
_GENDERED_ROLE = {"parent": ("mother", "father"), "child": ("daughter", "son"), "sibling": ("sister", "brother"),
                  "spouse": ("wife", "husband")}


def _bare_name(name: str) -> str:
    """The first name, which is what a sentence-shaped query uses ('Harriet', 'Salander')."""
    words = [word for word in re.split(r"\s+", (name or "").strip()) if word]
    return words[0] if words else ""


def _pronoun(data: dict[str, Any], key: str) -> str:
    """'her' or 'his' from how the entity's card facts refer to them; sentence-shaped queries need one."""
    card = next((card for card in data.get("cards", []) if card["key"] == key), None)
    text = " ".join(card.get("facts", []) if card else [])
    lowered = text.casefold()
    female = len(re.findall(r"\b(she|her|hers|daughter|mother|sister|wife|girl|woman)\b", lowered))
    male = len(re.findall(r"\b(he|him|his|son|father|brother|husband|boy|man)\b", lowered))
    if female == male:
        # The card facts can be neutral; the edge text around the person is the next best signal.
        text = " ".join(edge.get("text") or "" for edge in data.get("edges", [])
                        if key in (edge.get("from"), edge.get("to")))
        lowered = text.casefold()
        female = len(re.findall(r"\b(she|her|hers|daughter|mother|sister|wife|girl|woman)\b", lowered))
        male = len(re.findall(r"\b(he|him|his|son|father|brother|husband|boy|man)\b", lowered))
    return "her" if female > male else "his"


def _relation_role(data: dict[str, Any], person: str, other: str) -> str:
    """The word the other person would use for ``person`` in a reveal sentence ('father' for Gottfried/Harriet)."""
    if not person or not other or person == other:
        return ""
    alias = data.get("alias", {})
    for edge in data.get("edges", []):
        left = alias.get(edge.get("from"), edge.get("from"))
        right = alias.get(edge.get("to"), edge.get("to"))
        relation = (edge.get("relation") or "").strip().casefold()
        word = next((word for word in _RELATION_WORDS.findall(relation)), "")
        if not word:
            continue
        if left == other and right == person:
            role = _INVERSE_ROLE.get(word.casefold(), "")
        elif left == person and right == other:
            role = word.casefold()
        else:
            continue
        if role in _GENDERED_ROLE:
            female, male = _GENDERED_ROLE[role]
            role = female if _pronoun(data, person) == "her" else male
        return role
    return ""


def _event_verb(state: AgentState, args: dict[str, Any]) -> str:
    """The event words to search with: the tool argument, or the verb in the question, with 'died' widened to 'killed'."""
    event = str(args.get("event") or "").strip()
    if not event:
        matches = _EVENT_WORDS.findall(state.question)
        event = matches[0] if matches else state.question
    if _DEATH_WORDS.search(event) and not re.search(r"drown|shot|strangl|poison|hang|burn|stab|beat|murder|kill", event, re.I):
        return "killed"
    return event


def _candidate_others(state: AgentState, person: str, data: dict[str, Any]) -> list[str]:
    """People the cards tie to this person, the strongest relationship first; used when the caller names none."""
    alias = data.get("alias", {})
    cards = {card["key"]: card for card in data.get("cards", [])}
    if person not in cards:
        return []
    scores: dict[str, int] = {}
    card = cards[person]
    facts = " ".join(card.get("facts", [])).casefold()
    for edge in data.get("edges", []):
        left = alias.get(edge.get("from"), edge.get("from"))
        right = alias.get(edge.get("to"), edge.get("to"))
        if person not in (left, right):
            continue
        other = right if left == person else left
        if other == person or other not in cards or cards[other].get("mentions", 0) < 20:
            continue
        relation = edge.get("relation") or ""
        weight = 3 if _RELATION_WORDS.search(relation) else 1
        scores[other] = scores.get(other, 0) + weight
    for key, other_card in cards.items():
        if key != person and key in facts:
            scores[key] = scores.get(key, 0) + 1
    for anchor in _entity_anchors(state.question, data):
        if anchor != person:
            scores[anchor] = scores.get(anchor, 0) + 2
    ordered = sorted(scores, key=lambda key: (scores[key], cards[key].get("mentions", 0)), reverse=True)
    return ordered[:1]


def _true_scene_rank(scene: tuple[Any, float]) -> tuple[int, bool, float]:
    """Prefer the scene that reveals what happened over the one that repeats the official account.

    Among scenes that both reveal something, the rerank score decides: two scenes can describe the same fight from
    different sides, and the one that matches the question's words is the better read.
    """
    summary = (scene[0].payload.get("summary") or "")
    reveal = bool(_REVEAL_CUES.search(summary))
    official = bool(_OFFICIAL_CUES.search(summary))
    return (1 if reveal and not official else 0), reveal, scene[1]


def _true_account_queries(person: str, other: str, verb: str, role: str, pronoun: str) -> list[str]:
    """Sentence-shaped queries that name the other person doing the event; full names are left out on purpose.

    The books use a first name for one character and a surname for another (Harriet, Salander), so both forms are
    tried, and the surname form comes first because it is the more distinctive for 'Salander Niedermann nail gun'.
    """
    person_parts = [word for word in (person or "").split() if word]
    other_parts = [word for word in (other or "").split() if word]
    if not person_parts or not other_parts:
        return [f"{_bare_name(other)} {verb}".strip()]
    person_first, person_last = person_parts[0], person_parts[-1]
    other_first, other_last = other_parts[0], other_parts[-1]
    queries = []
    if role:
        queries.append(f"{other_first} {verb} {pronoun} {role}")
    if other_last.casefold() != person_last.casefold():
        queries.append(f"{other_last} {person_last} {verb}")
    queries.append(f"{other_first} {verb} {person_first}")
    queries.append(f"{other_first} {person_first} {verb}")
    return list(dict.fromkeys(query.strip() for query in queries if query.strip()))


def _display_name(key: str) -> str:
    """A card key as a name the answer can use ('gottfried vanger' -> 'Gottfried Vanger')."""
    return " ".join(word[:1].upper() + word[1:] for word in (key or "").split())


def _tool_true_account(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    person_name = str(args.get("person") or "").strip()
    if not person_name:
        return {"error": "person is required"}
    event = _event_verb(state, args)
    other_name = str(args.get("other_person") or "").strip()
    data: dict[str, Any] = {}
    path = entity_cards_path(state.collection, state.config)
    if path.exists():
        data = _entity_cards(str(path))
    person_key = _resolve_entity(data, person_name) if data else None
    person = _display_name(person_key) if person_key else person_name
    other_key = ""
    if other_name:
        other_key = (_resolve_entity(data, other_name) or "") if data else ""
        other_key = other_key or other_name
    elif person_key:
        candidates = _candidate_others(state, person_key, data)
        if candidates:
            other_key = candidates[0]
    other = _display_name(other_key) if other_key else ""
    role = _relation_role(data, person_key or person, other_key or other) if other else ""
    queries = (_true_account_queries(person, other, event, role, _pronoun(data, other_key)) if other else [
        f"{_bare_name(person)} {event}".strip()])
    passages: dict[str, dict[str, Any]] = {}
    scenes: dict[str, tuple[Any, float]] = {}
    used = []
    for query in queries:
        rows = _semantic_rows(state, query, 4)
        ranked, error = _scene_points(state, query, 3)
        if error:
            return {"error": error}
        used.append(query)
        for row in rows:
            current = passages.get(str(row["id"]))
            if current is None or float(row.get("score") or 0) > float(current.get("score") or 0):
                passages[str(row["id"])] = row
        for point, score in ranked:
            current = scenes.get(str(point.id))
            if current is None or score > current[1]:
                scenes[str(point.id)] = (point, score)
        # The sentence-shaped query that names the other person is the one that matters; stop when it lands.
        best_passage = max((float(row.get("score") or 0) for row in rows), default=0.0)
        best_scene = max((score for _, score in ranked), default=0.0)
        if used and (best_passage >= 6.0 or best_scene >= 5.0):
            break
    ranked_scenes = sorted(scenes.values(), key=_true_scene_rank, reverse=True)
    if not passages and not ranked_scenes:
        return {"person": person, "event": event, "other_people": [other] if other else [],
                "queries": used,
                "note": "nothing found; name who else was present and call again, or search the event words directly"}
    chosen = ranked_scenes[0][0] if ranked_scenes else None
    chosen_rows = (_scene_member_rows(state.collection, [str(member) for member in (chosen.payload.get("members") or [])])
                   if chosen is not None else [])
    shown_passages = sorted(passages.values(), key=lambda row: float(row.get("score") or 0), reverse=True)[:2]
    state.remember(chosen_rows)
    state.remember(shown_passages)
    state.focus_on(chosen_rows)
    state.focus_on(shown_passages)
    payload: dict[str, Any] = {
        "person": person, "event": event, "other_people": [other] if other else [], "queries": used,
        "passages": [_passage(row, 500) for row in shown_passages],
        "scenes": [{"scene_id": str(point.id)[:8], "score": round(score, 3), "summary": point.payload.get("summary"),
                    "passage_ids": [str(member)[:8] for member in (point.payload.get("members") or [])[:6]]}
                   for point, score in ranked_scenes[:2]],
        "note": ("compare this with the official account: answer with the true account (who did what) and mention the "
                 "official story only as contrast. These passages are evidence; cite the ones the answer relies on.")}
    if chosen is not None:
        payload["true_account_scene"] = {"scene_id": str(chosen.id)[:8], "summary": chosen.payload.get("summary"),
                                         "passages": [_scene_member(row, 500) for row in chosen_rows[:6]],
                                         "more_passages": max(0, len(chosen_rows) - 6)}
    return payload


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


def _name_score(text: str, key: str) -> int:
    """2 when the full name is in the text, 1 when one of its longer words is, 0 otherwise."""
    low = (text or "").casefold()
    if re.search(rf"\b{re.escape(key)}\b", low):
        return 2
    return 1 if any(re.search(rf"\b{re.escape(word)}\b", low) for word in key.split() if len(word) >= 4) else 0


# Verbs and artifacts that state a link between two people; a fact built from one of them is the connection
# ("wrote a report about", "gave it to", "hired"), while "mentioned him to his doctor" is an aside.
_LINK_WORDS = frozenset("""wrote write written gave give given sent send met meet told tell showed show paid pay helped help
saved save hired hire employed employed introduced recommends recommended report letter file document married""".split())


@lru_cache(maxsize=2)
def _fact_sources(path: str) -> dict[str, list[str]]:
    """The window passages behind each extracted fact, from the entity cache (the merged card drops the link)."""
    sources: dict[str, list[str]] = {}
    if not os.path.exists(path):
        return sources
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            members = [str(member) for member in (row.get("members") or [])]
            for entity in (row.get("entities") or []):
                fact = str(entity.get("fact") or "").strip().casefold()
                if fact and members:
                    sources.setdefault(fact, members)
    return sources


def _connection_pairs(data: dict[str, Any], first: str, second: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Facts that name both entities and edges that link them, strongest first."""
    facts: dict[str, dict[str, Any]] = {}
    for card in data["cards"]:
        if card["key"] not in (first, second):
            continue
        for fact in card.get("facts", []):
            score = _name_score(fact, first) + _name_score(fact, second)
            if score >= 2:
                links = len(_LINK_WORDS & set(_keywords(fact)))
                facts[fact] = {"fact": fact, "score": score + 2 * min(links, 2)}
    # Edges whose other end names a link artifact or verb ("Lisbeth Salander's report — written by Salander")
    # state the connection; edges that only happen to touch a person (a clinic she was committed to) drop.
    alias = data.get("alias", {})
    edges: dict[str, dict[str, Any]] = {}
    for edge in data.get("edges", []):
        text = edge.get("text") or ""
        left, right = edge.get("from"), edge.get("to")
        resolved = {alias.get(left, left), alias.get(right, right)}
        direct = resolved == {first, second}
        other = None
        if direct:
            other = ""
        elif first in resolved or second in resolved:
            other = right if alias.get(left, left) in (first, second) else left
        if other is None:
            continue
        score = len(_LINK_WORDS & set(_keywords(other or "")))
        if not direct and score == 0:
            continue
        edges[text or str(edge.get("members"))] = {
            "other_name": other, "relation": edge.get("relation"), "fact": text[:240], "score": score,
            "passage_ids": [str(member)[:8] for member in edge.get("members", [])[:6]],
            "members": [str(member) for member in edge.get("members", [])[:6]],
            "direct": direct}
    return (sorted(facts.values(), key=lambda row: row["score"], reverse=True),
            sorted(edges.values(), key=lambda row: (-row["score"], not row["direct"], row["relation"] or "")))


def _rank_facts(facts: list[str], about: str, limit: int = 8) -> list[str]:
    """Facts most related to ``about``; original order on ties, so an empty about keeps the card order."""
    words = {word for word in _keywords(about or "") if len(word) >= 3}
    scored = [(sum(1 for word in words if word in _keywords(fact)), -index, fact)
              for index, fact in enumerate(facts)]
    return [fact for score, _, fact in sorted(scored, reverse=True)[:limit]]


def _person_full_name(collection: str, name: str) -> str:
    """The books' two-word name when the question uses one word ("Mikael" -> "Mikael Blomkvist")."""
    pairs, words = _name_pairs(collection)
    form = name.strip()
    if form in pairs:
        return pairs[form][0]
    matches = [word for word in words if word.casefold() == form.casefold()]
    for word in matches:
        if word in pairs:
            return pairs[word][0]
    return form


def _tool_find_connections(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    first_name = str(args.get("person_a") or "").strip()
    second_name = str(args.get("person_b") or "").strip()
    if not first_name or not second_name:
        return {"error": "person_a and person_b are required"}
    path = entity_cards_path(state.collection, state.config)
    if not path.exists():
        return {"error": "entity cards are not built for this collection"}
    data = _entity_cards(str(path))
    first, second = _resolve_entity(data, first_name), _resolve_entity(data, second_name)
    if first is None or second is None:
        missing = first_name if first is None else second_name
        close = difflib.get_close_matches(missing.casefold(), [card["key"] for card in data["cards"]], n=4, cutoff=0.6)
        return {"error": f"no entity card for {missing!r}", "close_names": close}
    facts, edges = _connection_pairs(data, first, second)
    sources = _fact_sources(str(entity_cache_path()))
    by_id, _ = _row_index(state.collection)
    shown_facts = [row | {"passage_ids": [member[:8] for member in sources.get(row["fact"].casefold(), []) if member in by_id][:6]}
                   for row in facts[:6]]
    source_ids = [member for row in shown_facts for member in sources.get(row["fact"].casefold(), []) if member in by_id]
    rows = [by_id[member] for member in source_ids]
    rows += [by_id[member] for edge in edges for member in edge.get("members", []) if member in by_id]
    rows = list({row["id"]: row for row in rows}.values())
    state.remember(rows)
    shown = [{key: value for key, value in edge.items() if key != "members"} for edge in edges[:4]]
    return {"person_a": first, "person_b": second, "facts": shown_facts, "edges": shown,
            "passage_ids": [str(row["id"])[:8] for row in rows[:6]],
            "note": "facts carry passage_ids when the source window is known; read_passage opens one, search_scenes with both names finds their scene"}


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
    about = str(args.get("about") or state.question)
    links = []
    for edge in data.get("edges", []):
        if key not in (edge.get("from"), edge.get("to")):
            continue
        other = edge.get("to") if edge.get("from") == key else edge.get("from")
        if not other or other == key:
            continue
        links.append({"other_name": other, "relation": edge.get("relation"), "fact": (edge.get("text") or "")[:220],
                      "passage_ids": [str(member)[:8] for member in edge.get("members", [])[:3]]})
    words = {word for word in _keywords(about) if len(word) >= 3}
    links.sort(key=lambda link: (-sum(1 for word in words if word in _keywords(f"{link['relation']} {link['fact']}")),
                                 link["relation"] or ""))
    return {"name": key, "mentions": card.get("mentions"), "facts": _rank_facts(card.get("facts", []), about),
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
    likely = next((match for match in matches if not match["same"] and match["mentions"] >= 20), None)
    payload = {"name": name, "matches": matches,
               "note": "the books spell names this way; search with a full_name or book_spelling"}
    if likely:
        payload["likely"] = likely["full_name"]
        payload["note"] = (f"{name!r} is not a name the books use; the likely person is {likely['full_name']}. "
                           f"Continue with that name instead of answering that the character does not exist.")
    return payload


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
    state.focus_on(window)
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


_WHAT_HAPPENED = re.compile(r"\bwhat (?:happened|happens|went on|occurred|took place)\b|"
                            r"\bwhat (?:did|does) .{0,60} (?:do|happen)\b|"
                            r"\bdescribe (?:the )?(?:events?|incident|confrontation|attack)\b", re.I)
_STAGE_WORDS = {
    "arrival": frozenset("arrive arrived arrives went go goes drove drive enter enters entered reach reached came come "
                         "travel travelled traveled".split()),
    "discovery": frozenset("find finds found discover discovers discovered discovery body evidence search searched "
                           "examine examined investigate".split()),
    "confrontation": frozenset("confront confronted confronts attack attacked attacks fight fought fights struggle "
                               "struggled shoot shoots shot hit hits kick kicks nailed nails threatened threaten".split()),
    "outcome": frozenset("kill killed kills die died dies death murder murdered arrest arrested capture captured "
                         "escape escaped survive survived convicted sentenced".split()),
}


def _covered_stages(text: str) -> set[str]:
    words = set(re.findall(r"[a-z']+", (text or "").casefold()))
    return {stage for stage, vocabulary in _STAGE_WORDS.items() if words & vocabulary}


def _is_person_key(collection: str, key: str) -> bool:
    """Whether a card key is a character's name rather than a place or thing (the books' name vocabulary decides)."""
    words = _name_pairs(collection)[1]
    known = {word.casefold(): count for word, count in words.items()}
    return any(known.get(word.casefold(), 0) >= 20 for word in key.split())


def _person_neighbours(collection: str, data: dict[str, Any], key: str, limit: int = 4) -> list[str]:
    """People the cards connect to this one by a family or personal relation (a place card's owner leads to them)."""
    alias = data.get("alias", {})
    cards = {card["key"]: card for card in data.get("cards", [])}
    found: dict[str, int] = {}
    for edge in data.get("edges", []):
        left = alias.get(edge.get("from"), edge.get("from"))
        right = alias.get(edge.get("to"), edge.get("to"))
        if key not in (left, right):
            continue
        other = right if left == key else left
        if other == key or other not in cards or not _is_person_key(collection, other):
            continue
        relation = edge.get("relation") or ""
        if not _RELATION_WORDS.search(relation):
            continue
        found[other] = found.get(other, 0) + 1
    ordered = sorted(found, key=lambda name: (found[name], cards[name].get("mentions", 0)), reverse=True)
    return ordered[:limit]


def _coverage_people(state: AgentState, answer: str) -> list[str]:
    """People the current answer and evidence name, including the people in the cards of places it names.

    The factory answer names the brickworks but not Niedermann; the brickworks card's facts name him. People from a
    place's card come first, because they are the ones the answer is missing; the people already named follow.
    """
    path = entity_cards_path(state.collection, state.config)
    if not path.exists():
        return []
    data = _entity_cards(str(path))
    rows = [state.evidence[short] for short in state.order[:10] if short in state.evidence]
    match_text = " ".join([state.question, answer])
    text = " ".join([match_text] + [(row.get("text") or "")[:500] for row in rows])
    names = set(_entity_anchors(text, data))
    lowered = match_text.casefold()
    place_counts: dict[str, int] = {}
    for card in data.get("cards", []):
        key = card.get("key") or ""
        if len(key) < 4 or not re.search(rf"\b{re.escape(key)}\b", lowered):
            continue
        if _is_person_key(state.collection, key):
            continue
        # A place or thing named in the answer: the people its facts name belong to that event. A name that several
        # of those cards mention is the one the answer is about, not an aside from one long card.
        found = _entity_anchors(" ".join(card.get("facts", [])), data)
        names |= found
        for name in found:
            neighbours = _person_neighbours(state.collection, data, name)
            for person in (neighbours or [name]):
                place_counts[person] = place_counts.get(person, 0) + 1
    mentions = data.get("mentions", {})
    ordered = sorted(place_counts, key=lambda name: (place_counts[name], mentions.get(name, 0)), reverse=True)
    ordered += [name for name in sorted(names, key=lambda name: mentions.get(name, 0), reverse=True)
                if name in mentions and name not in ordered]
    return ordered[:3]


def _scene_chapter(state: AgentState, point: Any) -> tuple:
    """The book and section a scene lives in: scenes of one event share them, so a later scene can be found from it."""
    members = point.payload.get("members") or []
    if not members:
        return ()
    by_id, _ = _row_index(state.collection)
    row = by_id.get(str(members[0]))
    if not row:
        return ()
    return row.get("book_file"), row.get("section")


def _coverage_hint(state: AgentState, answer: str) -> dict[str, Any]:
    """What the answer has not covered yet, with the people and later scenes that would cover it."""
    people = _coverage_people(state, answer)
    summary: dict[str, Any] = {}
    if people:
        parts = [name.split() for name in people[:2]]
        if len(parts) == 2 and parts[0] and parts[1] and parts[0][-1].casefold() != parts[1][-1].casefold():
            names = " ".join([parts[0][-1], parts[1][-1]])  # the books use surnames for these two
        else:
            names = " ".join(" ".join(part) for part in parts)
        scenes: dict[str, tuple[Any, float]] = {}
        for query in (f"{names} what happened", f"{names} attack fight weapon", f"{names} weapon floor"):
            ranked, error = _scene_points(state, query, 6)
            if error:
                break
            for point, score in ranked:
                current = scenes.get(str(point.id))
                if current is None or score > current[1]:
                    scenes[str(point.id)] = (point, score)
        if scenes:
            ranked_scenes = sorted(scenes.values(), key=lambda pair: pair[1], reverse=True)[:8]
            # The top scene is the event's own chapter (the arrival at the place). Keep scenes from the same
            # chapter: a different chapter is usually a different event with the same people (Gosseberga vs the
            # brickworks), and mixing them makes the model narrate the wrong one.
            chapter = _scene_chapter(state, ranked_scenes[0][0]) if ranked_scenes else ()
            if chapter:
                same = [pair for pair in ranked_scenes if _scene_chapter(state, pair[0]) == chapter]
                if len(same) >= 2:
                    ranked_scenes = same
            summary["later_scenes"] = [
                {"scene_id": str(point.id)[:8], "score": round(score, 3), "summary": point.payload.get("summary")}
                for point, score in ranked_scenes]
            # One representative passage per later scene, kept in front of the final answer: the summary says what
            # happens, but the answer may only cite passages, so the first passage of each scene becomes evidence.
            scene_rows = []
            for point, _ in ranked_scenes:
                members = [str(member) for member in (point.payload.get("members") or [])][:1]
                scene_rows += _scene_member_rows(state.collection, members)
            state.remember(scene_rows)
            state.focus_on(scene_rows)
            summary["scene_passages"] = [_scene_member(row, 400) for row in scene_rows]
    return {"people_involved": people, **summary}


def _coverage_gap(state: AgentState, answer: str) -> dict[str, Any] | None:
    """A rejection for a what-happened answer that stops after one stage; checked once per run."""
    if not _WHAT_HAPPENED.search(state.question) or state.coverage_checks >= 1:
        return None
    covered = _covered_stages(answer)
    # Discovery and arrival alone are the first hit; a "what happened" answer needs the confrontation itself.
    if len(covered) >= 2 and "confrontation" in covered:
        return None
    state.coverage_checks += 1
    return {"error": "the answer covers only one stage of what happened: "
                     f"{', '.join(sorted(covered)) or 'none'}.",
            "covered_stages": sorted(covered),
            "note": "a what happened answer covers arrival, discovery, confrontation and outcome; open the scene after "
                    "the first hit and search with the people involved before submitting",
            **_coverage_hint(state, answer)}


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
    minimum = 1 if state.speech_hint else state.settings.min_tool_calls
    if state.tool_calls < minimum:
        return {"error": f"investigate more before answering: at least {minimum} tool calls "
                         f"(you made {state.tool_calls}); a passage that is only on topic is not evidence"}, False
    if unknown:
        return {"error": f"unknown passage ids: {unknown}. Use the 8-character ids the tools returned."}, False
    gap = _coverage_gap(state, answer)
    if gap:
        return gap, False
    labels = {short: f"[E{position}]" for position, short in enumerate(ids, 1)}
    cited = re.findall(r"\[([0-9a-fA-F]{8})\]", answer)

    def replace(match: re.Match[str]) -> str:
        short = match.group(1).casefold()
        return labels.get(short, match.group(0))

    rewritten = re.sub(r"\[([0-9a-fA-F]{8})\]", replace, answer)
    return {"answer": rewritten, "raw_answer": answer, "passage_ids": ids,
            "cited_ids": list(dict.fromkeys(item.casefold() for item in cited)),
            "uncited": bool(ids) and not any(item.casefold() in ids for item in cited)}, True


_CONNECTION_CUE = re.compile(r"\b(know|knew|known|learn|learned|learnt|meet|met|meeting|introduc\w*|relationship|related|"
                              r"connect\w*|affair|marry|married|hire|hired|gave|given|tell|told)\b", re.I)


def _normalize_question(state: AgentState) -> tuple[str, list[dict[str, str]]]:
    """Replace a name the books do not use with the closest book name (Mikhail -> Mikael Blomkvist)."""
    pairs, words = _name_pairs(state.collection)
    normalized, notes = state.question, []
    for token in dict.fromkeys(re.findall(r"\b[A-ZÅÄÖ][a-zåäöéü]{2,}\b", state.question)):
        if words.get(token, 0) >= 20:
            continue
        close = difflib.get_close_matches(token, list(words), n=1, cutoff=0.6)
        if close and words[close[0]] >= 20:
            full = pairs.get(close[0], (close[0], 0, 0))[0]
            normalized = re.sub(rf"\b{token}\b", full, normalized, count=1)
            notes.append({"from": token, "to": full})
    return normalized, notes


def _connection_precheck(state: AgentState) -> dict[str, Any] | None:
    """For a question that links two people, put the entity cards' connection facts in front of the model."""
    if not _CONNECTION_CUE.search(state.question):
        return None
    path = entity_cards_path(state.collection, state.config)
    if not path.exists():
        return None
    data = _entity_cards(str(path))
    anchors = _entity_anchors(state.question, data)
    if len(anchors) < 2:
        return None
    mentions = {card["key"]: card.get("mentions", 0) for card in data["cards"]}
    first, second = sorted(anchors, key=lambda key: mentions.get(key, 0), reverse=True)[:2]
    facts, edges = _connection_pairs(data, first, second)
    if not facts:
        return None
    sources = _fact_sources(str(entity_cache_path()))
    by_id, _ = _row_index(state.collection)
    shown = []
    for row in facts[:4]:
        ids = [member for member in sources.get(row["fact"].casefold(), []) if member in by_id][:6]
        shown.append({"fact": row["fact"], "passage_ids": [member[:8] for member in ids]})
        state.remember([by_id[member] for member in ids])
    return {"person_a": first, "person_b": second, "facts": shown,
            "edges": [{key: value for key, value in edge.items() if key != "members"} for edge in edges[:2]]}


def _precheck_message(check: dict[str, Any]) -> str:
    lines = [f"Connection facts from the entity cards about {check['person_a']} and {check['person_b']} "
             f"(not evidence by themselves; read the passages):"]
    for row in check["facts"]:
        lines.append(f"- {row['fact']} {row['passage_ids']}")
    return "\n".join(lines)


# Only a question that asks how someone died (or what happened in a killing) gets the true-account pre-check. A
# question can mention a shooting without being about a death account ("why did she survive being shot?"), and
# pre-loading a death reveal there skews the answer.
_DEATH_QUESTION = re.compile(r"\bhow\b.{0,100}\b(?:died?|death|dead|drown\w*|killed|murder\w*)\b|"
                             r"\bwhat happened to\b.{0,100}\b(?:died?|killed|murder\w*|drown\w*)\b", re.I)


def _true_account_precheck(state: AgentState) -> dict[str, Any] | None:
    """For a death or killing, run the true-account search before the loop: the official account is the first find.

    The model can ask again with a different person, but the reveal must be on the table from the start; otherwise the
    official account wins every rerank and the answer repeats it.
    """
    if not _DEATH_QUESTION.search(state.question):
        return None
    path = entity_cards_path(state.collection, state.config)
    if not path.exists():
        return None
    data = _entity_cards(str(path))
    anchors = _entity_anchors(state.question, data)
    if not anchors:
        return None
    person = max(anchors, key=lambda key: data.get("mentions", {}).get(key, 0))
    payload = _tool_true_account(state, {"person": person, "event": _event_verb(state, {})})
    if payload.get("error") or not (payload.get("passages") or payload.get("true_account_scene")):
        return None
    return payload


def _true_account_message(payload: dict[str, Any]) -> str:
    lines = [f"True-account search for {payload['person']} ({payload['event']})"
             + (f" with {', '.join(payload['other_people'])}" if payload.get("other_people") else "")
             + f": {'; '.join(payload.get('queries') or [])}. Compare these with the official account; if they show who "
               "really did it, answer with the true account and mention the official story only as contrast."]
    seen = set()
    rows = list((payload.get("true_account_scene") or {}).get("passages") or []) + list(payload.get("passages") or [])
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        lines.append(f"[{row['id']}] {row['text']}")
        if len(seen) >= 7:
            break
    return "\n\n".join(lines)


_MOMENT_DETAIL_QUESTION = re.compile(
    r"\bwhat\b.{0,120}\b(?:say|said|says|tell|told|reply|answer|mutter|whisper|shout|"
    r"wear|wore|wearing|notice|noticed|see|saw|hear|heard|hold|held)\b", re.I)
_MOMENT_TIME = re.compile(r"\b(when|while|as|moment|first time|first met)\b", re.I)
_SPEECH_CUES = re.compile(r"\b(say|said|says|tell|told|mutter\w*|whisper\w*|reply|replied|answer\w*|shout\w*)\b", re.I)
_SPEECH_STRONG = re.compile(r"\b(mutter\w*|whisper\w*|murmur\w*|shout\w*|reply|replied|muttered)\b", re.I)
_QUOTE_VERBS = re.compile(r"\b(mutter\w*|whisper\w*|murmur\w*|shout\w*)\b", re.I)


def _is_moment_question(question: str) -> bool:
    return bool(_MOMENT_DETAIL_QUESTION.search(question) and _MOMENT_TIME.search(question))


def _speech_excerpt(text: str) -> str:
    """The sentences around a speech verb, which is where a quoted line sits in a passage of narrative."""
    match = _SPEECH_CUES.search(text or "")
    if not match:
        return ""
    start = max(0, match.start() - 180)
    boundary = text.rfind(". ", 0, match.start())
    if boundary != -1 and match.start() - boundary < 300:
        start = boundary + 2
    end = min(len(text), match.end() + 320)
    return text[start:end].strip()


def _moment_precheck(state: AgentState) -> dict[str, Any] | None:
    """For a detail-at-a-moment question, put the moment's scene and the speech scene in front of the model.

    The model tends to search scene summaries with the question's clinical words and never open the passage that
    holds the line. The pre-check runs the moment path, adds the exact-word passages, and reads the scene whose
    summary names the speech, so the detail is on the table before the first turn.
    """
    if not (_is_moment_question(state.question) and _SPEECH_CUES.search(state.question)):
        # The moment path costs two generation requests. The tool stays available for visual details (what she wore);
        # the pre-check is for speech, where the model otherwise reads the memory of the event instead of the line.
        return None
    payload = _tool_scene_moment(state, {})
    if payload.get("error"):
        # The exact-word passages can still hold the line even when the moment path fails.
        payload = {"question": state.question, "moment": "", "scenes": [], "passages": []}
    keyword_rows = []
    for row in _keyword_search(state.question, state.collection, 5):
        keyword_rows.append(row | {"score": row.get("keyword_score")})
    state.remember(keyword_rows)
    extra_rows: list[dict[str, Any]] = []
    scenes = payload.get("scenes") or []
    if _SPEECH_CUES.search(state.question):
        anchors = set()
        path = entity_cards_path(state.collection, state.config)
        if path.exists():
            anchors = _entity_anchors(state.question, _entity_cards(str(path)))
        scored = []
        for scene in scenes:
            summary = scene.get("summary") or ""
            if not _SPEECH_CUES.search(summary):
                continue
            named = sum(1 for anchor in anchors if re.search(rf"\b{re.escape(anchor)}\b", summary.casefold()))
            scored.append((named, scene.get("score") or 0.0, scene))
        if scored:
            scene = max(scored, key=lambda item: (item[0], item[1]))[2]
            point, _ = _scene_lookup(state.collection, state.config, scene["scene_id"])
            if point is not None:
                extra_rows = _scene_member_rows(state.collection,
                                                [str(member) for member in (point.payload.get("members") or [])])
                # The passage with the speech is the one to put first, and to show whole: the line follows the setup.
                extra_rows.sort(key=lambda row: 0 if _SPEECH_CUES.search(row.get("text") or "") else 1)
                state.remember(extra_rows)
                state.focus_on(extra_rows)
    state.focus_on(keyword_rows)
    excerpt, excerpt_id = "", ""
    candidates = [*extra_rows, *keyword_rows]
    candidates.sort(key=lambda row: (0 if _QUOTE_VERBS.search(row.get("text") or "") else 1,
                                     0 if _SPEECH_STRONG.search(row.get("text") or "") else 1,
                                     0 if '"' in (row.get("text") or "") or "“" in (row.get("text") or "") else 1))
    for row in candidates:
        found = _speech_excerpt(row.get("text") or "")
        if found:
            excerpt, excerpt_id = found, row["id"][:8]
            break
    if excerpt:
        state.speech_hint = {"id": excerpt_id, "text": excerpt}
    return {"question": state.question, "moment": payload.get("moment"), "scenes": scenes,
            "keywords": keyword_rows, "scene_rows": extra_rows,
            "speech": {"id": excerpt_id, "text": excerpt} if excerpt else None}


def _moment_message(check: dict[str, Any]) -> str:
    lines = [f"Moment search for {check['question']!r}: {check.get('moment')}. These passages are evidence; a scene "
             "summary is not. Read the passages that state the detail before answering."]
    if check.get("speech"):
        lines.append(f"The speech is recorded in [{check['speech']['id']}]: …{check['speech']['text']}… "
                     "Use this line; do not answer that the books do not state it.")
    if check.get("scene_rows"):
        for row in (check.get("scene_rows") or [])[:6]:
            chars = 900 if _SPEECH_CUES.search(row.get("text") or "") else 400
            lines.append(f"[{row['id'][:8]}] {row.get('text', '')[:chars]}")
    else:
        for row in (check.get("keywords") or [])[:3]:
            lines.append(f"[{row['id'][:8]}] {row.get('text', '')[:900]}")
        for scene in (check.get("scenes") or [])[:4]:
            lines.append(f"scene [{scene['scene_id']}] {scene.get('summary', '')[:300]}")
    return "\n\n".join(lines)


def _sequence_precheck(state: AgentState) -> dict[str, Any] | None:
    """For a what-happened question, put the later scenes of the same event in front of the model before it starts.

    The first search finds the arrival and the discovery; the confrontation is several scenes later and often in a
    different chapter. The people from the question's places and their relations give the search its cast.
    """
    if not _WHAT_HAPPENED.search(state.question):
        return None
    hint = _coverage_hint(state, "")
    if not hint.get("later_scenes"):
        return None
    return hint


def _sequence_message(check: dict[str, Any]) -> str:
    lines = ["Sequence search: a what happened answer covers arrival, discovery, confrontation and outcome. The "
             "first search usually finds arrival and discovery; these are later scenes of the same event, all in the "
             "same chapter and section as the arrival at the place the question names. The passages may call the place "
             "by another name (a factory can be a brickworks); that is not a different event. Read the passage that "
             "states what happened there, then answer with the whole sequence, not only the first find."]
    for row in (check.get("scene_passages") or [])[:8]:
        lines.append(f"[{row['id'][:8]}] {row.get('text', '')[:400]}")
    for scene in (check.get("later_scenes") or [])[:6]:
        lines.append(f"scene [{scene['scene_id']}] {scene.get('summary', '')[:260]}")
    return "\n\n".join(lines)


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
        spec("search_scenes", "Search summaries of six-passage windows. Use it to find a conversation or an explanation spread over several passages, or dialogue that never names the people. Pass `people` when the question names two people: their full names are added to the query. Each scene carries its scene_id and passage ids; `full` returns every member passage at length.",
             {"query": query, "people": {"type": "array", "items": {"type": "string"}, "description": "people the question names (optional)"},
              "k": {"type": "integer", "description": "how many scenes (default 2, max 5)"},
              "full": {"type": "boolean", "description": "return every member passage at ~500 characters instead of four 110-character snippets (default false)"}}, []),
        spec("read_scene", "Read every member passage of one scene in reading order (~500 characters each). Use the scene_id that search_scenes or true_account returned when the snippet does not contain the detail.",
             {"scene_id": {"type": "string", "description": "8-character scene id"}}, ["scene_id"]),
        spec("scene_moment", "For a question about a detail at one moment (what someone said, wore, noticed or held), write the situation out and let the model choose the scene that shows it; returns that scene's passages. Use it when a search for the question's words finds the right scene but not the detail.",
             {"question": {"type": "string", "description": "the question or the moment (default: the user's question)"}}, []),
        spec("true_account", "After the books give an official account of a death, a crime or a disappearance, find the true account: searches for the other person doing the event ('Harriet drowned her father') and returns the scene and passages that reveal what really happened. Pass who else was there when you know; otherwise the entity cards suggest them.",
             {"person": {"type": "string", "description": "the person the event happened to (or the event's subject)"},
              "event": {"type": "string", "description": "the event verb or words from the question (died, drowned, shot, nail gun, factory); derived from the question when omitted"},
              "other_person": {"type": "string", "description": "who else was there or who did it (optional)"}},
             ["person"]),
        spec("entity_card", "A person's entity card: how the books spell the name, facts about them, and their links to other names and things (aliases, nicknames, belongings). Facts are ranked by the question, or by `about` when given.",
             {"name": {"type": "string", "description": "person or thing name"},
              "about": {"type": "string", "description": "what to rank the facts for (optional; default the question)"}}, ["name"]),
        spec("find_connections", "What links two people: facts and edges that name both (how they met, what one did for the other, documents or names between them), with passages that state an edge. Use it for 'how did X know Y' or 'what connects X and Y'.",
             {"person_a": {"type": "string", "description": "first person"}, "person_b": {"type": "string", "description": "second person"}},
             ["person_a", "person_b"]),
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
        "read_scene": _tool_read_scene,
        "scene_moment": _tool_scene_moment,
        "true_account": _tool_true_account,
        "entity_card": _tool_entity_card,
        "find_connections": _tool_find_connections,
        "find_names": _tool_find_names,
        "read_passage": _tool_read_passage,
        "read_chapter": _tool_read_chapter,
    }
    if name == "submit_answer":
        return _tool_submit_answer(state, args)
    if name not in tools:
        return {"error": f"unknown tool {name!r}", "tools": sorted([*tools, "submit_answer"])}, False
    return tools[name](state, args), False


def _verify_submission(state: AgentState, answer: str, ids: list[str], extra_ids: list[str] = ()) -> tuple[bool, str]:
    """Ask the model whether the cited passages (or a passage a tool read on purpose) state the proposed answer."""
    blocks = []
    by_section: dict[tuple, list[dict[str, Any]]] = {}
    _, rows = _row_index(state.collection)
    for row in rows:
        by_section.setdefault((row.get("book_file"), row.get("section")), []).append(row)
    checked = list(dict.fromkeys([*ids, *extra_ids]))
    for position, short in enumerate(checked, 1):
        row = state.evidence.get(short)
        if not row:
            continue
        section = sorted(by_section.get((row.get("book_file"), row.get("section")), [row]), key=_passage_position)
        index = next((number for number, item in enumerate(section) if item["id"] == row["id"]), None)
        context = section[max(0, (index or 0) - 1): (index or 0) + 2] if index is not None else [row]
        blocks.append(f"[E{position}] id={short} | {row.get('book')} | {row.get('chapter')}\n" + "\n".join(
            f"paragraph {item.get('paragraph')}: {(item.get('text') or '')[:900]}" for item in context))
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


_SYNTHESIS_SYSTEM = """You answer a question about Stieg Larsson's Millennium trilogy from the evidence passages given.
Use only those passages. Cite each claim with the passage id in square brackets, exactly as given.
If the passages show a document, letter, introduction or conversation that brought two people together, or that brought
something to someone's attention, that is how they came to know it: say so plainly. Only say the passages do not answer
the question if none of them state it."""


_ABSTAIN = re.compile(
    r"\b(insufficient|cannot determine|no factual claims|could not find|not found in|"
    r"(?:do not|does not|don't) (?:contain|describe|state|mention|say|provide)|"
    r"no (?:passage|information|evidence|mention)|there is no passage|"
    r"not possible to answer|cannot be answered|(?:do not|does not|don't) answer|no answer)\b", re.I)


def _looks_like_abstention(answer: str) -> bool:
    return is_explicit_abstention(answer) or bool(_ABSTAIN.search(answer or ""))


def _synthesis_rows(state: AgentState, limit: int = 10) -> list[dict[str, Any]]:
    rows = [state.evidence[short] for short in state.order if short in state.evidence]
    focused = [state.evidence[short] for short in state.focus if short in state.evidence]
    if len(rows) <= limit:
        return rows
    # The passages a tool read on purpose (a full scene, a true-account reveal) must survive the rerank: they were
    # fetched for a reason the question's wording does not capture. Without such a read, the pre-check passages stay.
    kept = (focused or rows[:4])[:limit]
    rest = [row for row in rows if row["id"] not in {item["id"] for item in kept}]
    if len(kept) >= limit or not rest:
        return kept
    scores = _reranker(state.config.reranker_model.name, state.config.reranker_model.revision).predict(
        [(state.question, row.get("text") or "") for row in rest], show_progress_bar=False)
    ranked = [row for row, score in sorted(zip(rest, (float(value) for value in scores)),
                                           key=lambda pair: pair[1], reverse=True)[:limit - len(kept)]]
    return kept + ranked


def _synthesize(state: AgentState) -> tuple[str, list[str]] | None:
    """One clean answer request over the collected evidence, when the loop's answer abstained despite evidence."""
    rows = _synthesis_rows(state)
    if not rows:
        return None
    blocks = [f"[{row['id'][:8]}] {row.get('book')} | {row.get('chapter')} | paragraph {row.get('paragraph')}\n"
              f"{(row.get('text') or '')[:900]}" for row in rows]
    prompt = f"Question: {state.question}\n\nEvidence:\n" + "\n\n".join(blocks)
    try:
        reply = _ollama_chat([{"role": "system", "content": _SYNTHESIS_SYSTEM},
                              {"role": "user", "content": prompt}], None, state.settings)
        content = ((reply.get("message") or {}).get("content") or "").strip()
        state.usage["prompt_tokens"] += int(reply.get("prompt_eval_count") or 0)
        state.usage["completion_tokens"] += int(reply.get("eval_count") or 0)
    except Exception:
        return None
    ids = [short.casefold() for short in re.findall(r"\[([0-9a-fA-F]{8})\]", content)
           if short.casefold() in state.evidence]
    state.trace.append({"tool": "abstention synthesis", "arguments": {"rows": len(rows)},
                        "seconds": 0.0, "error": None, "result_ids": list(dict.fromkeys(ids))})
    if not content or not ids:
        return None
    return content, list(dict.fromkeys(ids))


def _finish(state: AgentState, answer: str, ids: list[str], *, stopped: str,
            raw_answer: str | None = None) -> dict[str, Any]:
    """Answer from the loop, but never abstain while holding evidence that states the answer."""
    if _WHAT_HAPPENED.search(state.question) and state.evidence:
        # The answer may look like it covers the sequence while stopping at the discovery. Add the later scenes'
        # passages, then rewrite when the answer is missing the confrontation or most of the sequence.
        covered = _covered_stages(answer)
        if "confrontation" not in covered or len(covered) < 3:
            _coverage_hint(state, answer)
            synthesized = _synthesize(state)
            if synthesized:
                rewrite, rewrite_ids = synthesized
                rewrite_stages = _covered_stages(rewrite)
                if "confrontation" in rewrite_stages and len(rewrite_stages) > len(covered):
                    answer, ids = rewrite, rewrite_ids
    cited = re.search(r"\[(?:E\d+|[0-9a-fA-F]{8})\]", answer)
    if (not ids or _looks_like_abstention(answer) or not cited) and state.evidence:
        synthesized = _synthesize(state)
        if synthesized:
            answer, ids = synthesized[0], synthesized[1]
            stopped = stopped + "+synthesis"
            raw_answer = None
    if _looks_like_abstention(answer) and state.speech_hint:
        # The moment pass already found the line; do not let the final model lose it behind an abstention.
        answer = f"{state.speech_hint['text']} [{state.speech_hint['id']}]"
        ids = [state.speech_hint["id"]]
        stopped = stopped + "+speech"
        raw_answer = None
    return _final(state, answer, ids, stopped=stopped, raw_answer=raw_answer)


def _evidence_digest(state: AgentState, limit: int = 14) -> str:
    focused = [state.evidence[short] for short in state.focus if short in state.evidence]
    rest = [state.evidence[short] for short in state.order if short in state.evidence
            and short not in set(state.focus)]
    rows = (focused + rest)[:limit]
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
    return _finish(state, content, list(dict.fromkeys(short.casefold() for short in ids)), stopped="budget")


def _final(state: AgentState, answer: str, ids: list[str], *, stopped: str, raw_answer: str | None = None) -> dict[str, Any]:
    labels = {short: f"[E{position}]" for position, short in enumerate(ids, 1)}
    # An id the answer cites but did not collect is not evidence; leave it out instead of confusing the reader (or
    # the fact judge) with a bare hex string, and keep the labels the evidence list actually defines.
    rewritten = re.sub(r"\[([0-9a-fA-F]{8})\]", lambda match: labels.get(match.group(1).casefold(), ""), answer)
    # A citation list on its own line adds nothing (the evidence list shows them) and derails the fact judge, which
    # reads key-like tokens in the answer. Inline citations stay.
    rewritten = re.sub(r"\n+\s*(?:\[E\d+\]\s*)+$", "", rewritten).rstrip()
    cited = [match.group(1) for match in re.finditer(r"\[(E\d+)\]", rewritten)]
    return {"question": state.question, "asked": state.asked, "name_normalization": state.name_notes,
            "answer": rewritten, "raw_answer": raw_answer if raw_answer is not None else answer,
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
    state = AgentState(question=question, asked=question, collection=collection, config=config, settings=settings,
                       started=time.perf_counter())
    normalized, name_notes = _normalize_question(state)
    state.question = normalized
    state.name_notes = name_notes
    precheck = _connection_precheck(state)
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT},
                                      {"role": "user", "content": normalized}]
    if precheck:
        messages.append({"role": "user", "content": _precheck_message(precheck)})
        state.trace.append({"tool": "connection pre-check", "arguments": {"person_a": precheck["person_a"],
                                                                          "person_b": precheck["person_b"]},
                            "seconds": 0.0, "error": None, "result_ids": [row["passage_ids"][0] for row in precheck["facts"] if row["passage_ids"]]})
    true_check = _true_account_precheck(state)
    if true_check:
        messages.append({"role": "user", "content": _true_account_message(true_check)})
        state.trace.append({"tool": "true account pre-check",
                            "arguments": {"person": true_check["person"], "event": true_check["event"],
                                          "other_people": true_check.get("other_people")},
                            "seconds": 0.0, "error": None,
                            "result_ids": [row["id"] for row in (true_check.get("passages") or [])]})
    sequence_check = _sequence_precheck(state)
    if sequence_check:
        messages.append({"role": "user", "content": _sequence_message(sequence_check)})
        state.trace.append({"tool": "sequence pre-check", "arguments": {"question": state.question},
                            "seconds": 0.0, "error": None,
                            "result_ids": [row["id"][:8] for row in (sequence_check.get("scene_passages") or [])]})
    moment_check = _moment_precheck(state)
    if moment_check:
        messages.append({"role": "user", "content": _moment_message(moment_check)})
        state.trace.append({"tool": "moment pre-check", "arguments": {"question": state.question},
                            "seconds": 0.0, "error": None,
                            "result_ids": [row["id"][:8] for row in (moment_check.get("keywords") or [])[:3]
                                           + (moment_check.get("scene_rows") or [])[:6]]})
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
                if state.tool_calls < state.settings.min_tool_calls and state.nudges < 2:
                    state.nudges += 1
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": (
                        f"You have made {state.tool_calls} tool calls; investigate more before answering (at least "
                        f"{state.settings.min_tool_calls}). Check each part of the question and search for the part the "
                        "passages do not yet state.")})
                    emit({"type": "nudge", "turn": turn})
                    continue
                if state.evidence:
                    gap = _coverage_gap(state, content)
                    if gap:
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "tool", "content": _clip(gap)})
                        emit({"type": "coverage", "covered": gap.get("covered_stages"),
                              "people": gap.get("people_involved")})
                        continue
                if ids and state.verifications < 2:
                    state.verifications += 1
                    focus = [short for short in state.focus if short not in ids][:6]
                    supported, reason = _verify_submission(state, content, ids, focus)
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
                result = _finish(state, content, ids, stopped="content")
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
                if name == "find_names" and payload.get("likely") and payload.get("name") not in state.resolved_names:
                    state.resolved_names.add(payload["name"])
                    messages.append({"role": "user", "content": (
                        f"Name check: the books do not use {payload['name']!r}; the person meant is {payload['likely']}. "
                        "Continue the question with that name; do not answer that the character does not exist.")})
                if stop:
                    if state.verifications < 2 and payload["passage_ids"]:
                        state.verifications += 1
                        focus = [short for short in state.focus if short not in payload["passage_ids"]][:6]
                        supported, reason = _verify_submission(state, payload["raw_answer"], payload["passage_ids"], focus)
                        emit({"type": "verify", "supported": supported, "reason": reason})
                        if not supported:
                            messages.append({"role": "tool", "content": _clip({
                                "error": "the answer is not supported by the cited passages",
                                "reason": reason,
                                "note": "search again: find a passage that states the answer, then submit a corrected answer"})})
                            continue
                    result = _finish(state, payload["answer"], payload["passage_ids"], stopped="submit",
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
