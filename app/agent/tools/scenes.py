"""agent / tools / scenes responsibilities."""
from __future__ import annotations

from app.agent.protocol import _int
from app.agent.state import AgentState
from app.agent.tools.search import _scene_points
from app.context.citations import _passage
from app.context.citations import _scene_member
from app.indexing.entities import entity_cards_path
from app.retrieval.entities import display_name
from app.retrieval.entities import person_full_name
from app.retrieval.passages import scene_member_rows
from app.retrieval.scenes import scene_lookup
from app.retrieval.search import entity_anchors
from app.retrieval.search import entity_cards
from app.retrieval.moments import moment_scene_hits
from app.retrieval.search import qdrant_client
from typing import Any
import re


def _scene_payload(state: "AgentState", point: Any, score: float, *, full: bool,
                   query: str | None = None) -> dict[str, Any]:
    """A scene as the agent sees it: compact by default, every member at full length when asked.

    The compact form keeps the first four 110-character snippets (the old payload) and adds the scene id and all
    member ids, so the agent can open the scene instead of guessing. The full form caps at six members of 500
    characters, the size of one scene window and the per-call token budget.
    """
    members = [str(member) for member in (point.payload.get("members") or [])]
    rows = scene_member_rows(state.collection, members)
    state.remember(rows, query=query)
    if full:
        state.focus_on(rows)
    shown = rows[:6] if full else rows[:4]
    return {"scene_id": str(point.id)[:8], "score": round(score, 3), "summary": point.payload.get("summary"),
            "passage_ids": [member[:8] for member in members[:6]],
            "passages": [_scene_member(row, 500 if full else 110) for row in shown],
            "more_passages": max(0, len(rows) - len(shown)) if full else 0}


def _tool_scene_search(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    people = args.get("people") or []
    if isinstance(people, str):
        people = [people]
    names = [person_full_name(state.collection, str(person).strip()) for person in people if str(person).strip()]
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
    scenes = [_scene_payload(state, point, score, full=full, query=query) for point, score in ranked]
    return {"query": query, "people": names, "scenes": scenes,
            "note": "pass a scene_id to read_scene for every member passage in reading order"}


def _initial_scene_probe(state: AgentState) -> tuple[dict[str, Any] | None, str]:
    """Offer the best scene's source passages before the agent chooses any tools."""
    ranked, error = _scene_points(state, state.question, 1)
    if error or not ranked:
        return None, error or "no scene candidate returned"
    point, score = ranked[0]
    return _scene_payload(state, point, score, full=True, query=state.question), ""


def _initial_scene_message(scene: dict[str, Any]) -> str:
    lines = ["Automatic scene search found a possible lead. Check its source passages against the question; "
             "cite only passages that state the answer, and search further if needed."]
    lines.extend(f"[{row['id']}] {row['text']}" for row in scene["passages"])
    return "\n\n".join(lines)


def _tool_read_scene(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    wanted = str(args.get("scene_id") or args.get("id") or "")
    point, error = scene_lookup(state.collection, state.config, wanted)
    if point is None:
        return {"error": error}
    rows = scene_member_rows(state.collection, [str(member) for member in (point.payload.get("members") or [])])
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
    data = entity_cards(str(path))
    cards = {card["key"]: card for card in data.get("cards", [])}
    alias = data.get("alias", {})
    variants = []
    for key in sorted(entity_anchors(moment, data), key=lambda name: data.get("mentions", {}).get(name, 0)):
        display = display_name(key)
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
            alias_name = display_name(other)
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
    rows, moment = moment_scene_hits(question, state.config, state.collection, qdrant_client(), evidence, present, None)
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
