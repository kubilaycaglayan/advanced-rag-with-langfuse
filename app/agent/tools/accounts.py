"""agent / tools / accounts responsibilities."""
from __future__ import annotations

from app.agent.state import AgentState
from app.agent.tools.search import _scene_points
from app.agent.tools.search import _semantic_rows
from app.context.citations import _passage
from app.context.citations import _scene_member
from app.indexing.entities import entity_cards_path
from app.retrieval.entities import display_name
from app.retrieval.entities import resolve_entity
from app.retrieval.passages import scene_member_rows
from app.retrieval.search import entity_anchors
from app.retrieval.search import entity_cards
from typing import Any
import re


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
    for anchor in entity_anchors(state.question, data):
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



def _tool_true_account(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    person_name = str(args.get("person") or "").strip()
    if not person_name:
        return {"error": "person is required"}
    event = _event_verb(state, args)
    other_name = str(args.get("other_person") or "").strip()
    data: dict[str, Any] = {}
    path = entity_cards_path(state.collection, state.config)
    if path.exists():
        data = entity_cards(str(path))
    person_key = resolve_entity(data, person_name) if data else None
    person = display_name(person_key) if person_key else person_name
    other_key = ""
    if other_name:
        other_key = (resolve_entity(data, other_name) or "") if data else ""
        other_key = other_key or other_name
    elif person_key:
        candidates = _candidate_others(state, person_key, data)
        if candidates:
            other_key = candidates[0]
    other = display_name(other_key) if other_key else ""
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
    chosen_rows = (scene_member_rows(state.collection, [str(member) for member in (chosen.payload.get("members") or [])])
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

