"""agent / tools / entities responsibilities."""
from __future__ import annotations

from app.agent.state import AgentState
from app.indexing.entities import _cache_path as entity_cache_path
from app.indexing.entities import entity_cards_path
from app.retrieval.entities import _connection_pairs
from app.retrieval.entities import _fact_sources
from app.retrieval.entities import _rank_facts
from app.retrieval.entities import _resolve_entity
from app.retrieval.passages import _row_index
from app.retrieval.search import _entity_cards
from app.retrieval.search import _keywords
from app.retrieval.search import _name_pairs
from typing import Any
import difflib


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

