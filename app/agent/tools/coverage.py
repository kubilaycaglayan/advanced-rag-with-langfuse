"""agent / tools / coverage responsibilities."""
from __future__ import annotations

from app.agent.state import AgentState
from app.agent.tools.accounts import _RELATION_WORDS
from app.agent.tools.search import _scene_points
from app.context.citations import _scene_member
from app.indexing.entities import entity_cards_path
from app.retrieval.passages import passage_index
from app.retrieval.passages import scene_member_rows
from app.retrieval.search import entity_anchors
from app.retrieval.search import entity_cards
from app.retrieval.search import name_pairs
from typing import Any
import re


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
    words = name_pairs(collection)[1]
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
    data = entity_cards(str(path))
    rows = [state.evidence[short] for short in state.order[:10] if short in state.evidence]
    match_text = " ".join([state.question, answer])
    text = " ".join([match_text] + [(row.get("text") or "")[:500] for row in rows])
    names = set(entity_anchors(text, data))
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
        found = entity_anchors(" ".join(card.get("facts", [])), data)
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
    by_id, _ = passage_index(state.collection)
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
                scene_rows += scene_member_rows(state.collection, members)
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

