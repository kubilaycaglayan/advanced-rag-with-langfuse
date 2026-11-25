"""retrieval / entities responsibilities."""
from __future__ import annotations

from app.retrieval.search import keywords
from app.retrieval.search import name_pairs
from functools import lru_cache
from typing import Any
import difflib
import json
import os
import re


def name_hints(collection: str, text: str) -> dict[str, list[str]]:
    """Book spellings for capitalised words in a query that the books do not use, or use under another full name."""
    _, words = name_pairs(collection)
    hints: dict[str, list[str]] = {}
    for token in dict.fromkeys(re.findall(r"\b[A-ZÅÄÖ][\wåäöé-]{2,}\b", text or "")):
        if words.get(token, 0) >= 20:
            continue
        close = difflib.get_close_matches(token, list(words), n=2, cutoff=0.6)
        if close:
            hints[token] = [f"{name} ({words[name]} mentions)" for name in close]
    return hints



def display_name(key: str) -> str:
    """A card key as a name the answer can use ('gottfried vanger' -> 'Gottfried Vanger')."""
    return " ".join(word[:1].upper() + word[1:] for word in (key or "").split())



def resolve_entity(data: dict[str, Any], name: str) -> str | None:
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



def name_score(text: str, key: str) -> int:
    """2 when the full name is in the text, 1 when one of its longer words is, 0 otherwise."""
    low = (text or "").casefold()
    if re.search(rf"\b{re.escape(key)}\b", low):
        return 2
    return 1 if any(re.search(rf"\b{re.escape(word)}\b", low) for word in key.split() if len(word) >= 4) else 0



_LINK_WORDS = frozenset("""wrote write written gave give given sent send met meet told tell showed show paid pay helped help
saved save hired hire employed employed introduced recommends recommended report letter file document married""".split())



@lru_cache(maxsize=2)
def fact_sources(path: str) -> dict[str, list[str]]:
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



def connection_pairs(data: dict[str, Any], first: str, second: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Facts that name both entities and edges that link them, strongest first."""
    facts: dict[str, dict[str, Any]] = {}
    for card in data["cards"]:
        if card["key"] not in (first, second):
            continue
        for fact in card.get("facts", []):
            score = name_score(fact, first) + name_score(fact, second)
            if score >= 2:
                links = len(_LINK_WORDS & set(keywords(fact)))
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
        score = len(_LINK_WORDS & set(keywords(other or "")))
        if not direct and score == 0:
            continue
        edges[text or str(edge.get("members"))] = {
            "other_name": other, "relation": edge.get("relation"), "fact": text[:240], "score": score,
            "passage_ids": [str(member)[:8] for member in edge.get("members", [])[:6]],
            "members": [str(member) for member in edge.get("members", [])[:6]],
            "direct": direct}
    return (sorted(facts.values(), key=lambda row: row["score"], reverse=True),
            sorted(edges.values(), key=lambda row: (-row["score"], not row["direct"], row["relation"] or "")))



def rank_facts(facts: list[str], about: str, limit: int = 8) -> list[str]:
    """Facts most related to ``about``; original order on ties, so an empty about keeps the card order."""
    words = {word for word in keywords(about or "") if len(word) >= 3}
    scored = [(sum(1 for word in words if word in keywords(fact)), -index, fact)
              for index, fact in enumerate(facts)]
    return [fact for score, _, fact in sorted(scored, reverse=True)[:limit]]



def person_full_name(collection: str, name: str) -> str:
    """The books' two-word name when the question uses one word ("Mikael" -> "Mikael Blomkvist")."""
    pairs, words = name_pairs(collection)
    form = name.strip()
    if form in pairs:
        return pairs[form][0]
    matches = [word for word in words if word.casefold() == form.casefold()]
    for word in matches:
        if word in pairs:
            return pairs[word][0]
    return form

