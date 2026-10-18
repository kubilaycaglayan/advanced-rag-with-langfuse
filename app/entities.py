"""Entity cards: the people, other names, places and things of each scene window, merged across the books.

A question about a set of names ("What is Salander's fake identity?") is answered by passages that never use its words
and say "she ... under the name of Irene Nesser"; dense search, keywords and the cross-encoder cannot tie them to the
question. Each non-overlapping window of ``ENTITY_WINDOW`` consecutive passages of one EPUB section is read once by the
index-time model (``scene_summary_model``), which lists its entities with the person each belongs to and how
("false identity used by Lisbeth Salander"). The mentions are merged into entities (name variants and one-word names
joined to the person's full name) and edges ("Irene Nesser — false identity used by Lisbeth Salander"), each pointing
back to the passages that state it. The pipeline reads the cards with ``entity_names`` (see ``_entity_name_hits``).
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import requests
from qdrant_client import QdrantClient

try:
    from .identity import canonical_json
    from .prompt_templates import PROMPT_TEMPLATES
    from .resolved_config import ResolvedPipelineConfig
    from .scenes import passages_in_order, scene_windows, summary_model
except ImportError:
    from identity import canonical_json
    from prompt_templates import PROMPT_TEMPLATES
    from resolved_config import ResolvedPipelineConfig
    from scenes import passages_in_order, scene_windows, summary_model

ENTITY_WINDOW = 6


def _cache_path() -> Path:
    return Path(os.getenv("ENTITY_CACHE", "/data/entities.jsonl"))


def _prompt_hash() -> str:
    return hashlib.sha256(PROMPT_TEMPLATES["entity_extraction_system"].encode("utf-8")).hexdigest()


def _window_key(members: list[str], config: ResolvedPipelineConfig) -> str:
    return hashlib.sha256(canonical_json({"members": members, "prompt": _prompt_hash(), "model": summary_model(config)}).encode()).hexdigest()


def entity_cards_path(collection: str, config: ResolvedPipelineConfig) -> Path:
    identity = {"passages": collection, "window": ENTITY_WINDOW, "prompt": _prompt_hash(), "model": summary_model(config),
                "merge": hashlib.sha256(inspect.getsource(merge_entities).encode("utf-8")).hexdigest()}
    directory = Path(os.getenv("ENTITY_CARDS_DIR", "/data/entity-cards"))
    return directory / f"{collection}_entities_{hashlib.sha256(canonical_json(identity).encode()).hexdigest()[:12]}.json"


def _extract(points: list[Any], config: ResolvedPipelineConfig) -> tuple[list[dict[str, Any]] | None, str]:
    body = "\n".join(point.payload["text"] for point in points)
    response = requests.post(os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat", json={
        "model": summary_model(config), "think": False, "stream": False, "format": "json",
        "messages": [{"role": "system", "content": PROMPT_TEMPLATES["entity_extraction_system"]},
                     {"role": "user", "content": f"Book: {points[0].payload['book']}\n\nEXCERPT:\n{body}"}],
        "options": {"temperature": 0, "num_ctx": 6144, "num_predict": 1500}}, timeout=(10, 900))
    response.raise_for_status()
    text = response.json().get("message", {}).get("content", "")
    try:
        entities = json.loads(text).get("entities", [])
    except (ValueError, AttributeError):
        return None, text
    return entities if isinstance(entities, list) else None, text


def _read_cache() -> dict[str, dict[str, Any]]:
    path = _cache_path()
    rows: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            rows[row["key"]] = row
    return rows


def build_entity_cards(collection: str, config: ResolvedPipelineConfig, qdrant: QdrantClient) -> dict[str, Any]:
    """Extract every window's entities (reusing cached ones) and write the merged cards. Slow on first build: one
    index-time model call per window, about 2.8 hours with gemma4:26b for the three books on this machine."""
    path = entity_cards_path(collection, config)
    if path.exists():
        return {"path": str(path), "already_indexed": True}
    windows = scene_windows(passages_in_order(qdrant, collection), ENTITY_WINDOW, ENTITY_WINDOW)
    cache = _read_cache()
    called = False
    extracted = []
    _cache_path().parent.mkdir(parents=True, exist_ok=True)
    with _cache_path().open("a", encoding="utf-8") as out:
        for points in windows:
            members = [str(point.id) for point in points]
            key = _window_key(members, config)
            if key not in cache:
                entities, raw = _extract(points, config)
                called = True
                cache[key] = {"key": key, "members": members, "book": points[0].payload["book"], "entities": entities,
                              "raw": None if entities is not None else raw}
                out.write(json.dumps(cache[key]) + "\n")
                out.flush()
            extracted.append(cache[key])
    if called and summary_model(config) != config.generation_model.name:
        requests.post(os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/generate",
                      json={"model": summary_model(config), "keep_alive": 0}, timeout=(10, 60))
    cards = merge_entities(extracted)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(cards), encoding="utf-8")
    temporary.replace(path)
    return {"path": str(path), "windows": len(windows), "entities": len(cards["cards"]), "edges": len(cards["edges"]),
            "already_indexed": False}


EVENT_CARRY_CHARS = 4000


def _events_cache_path() -> Path:
    return Path(os.getenv("ENTITY_EVENTS_CACHE", "/data/entity-events.jsonl"))


def _events_prompt_hash() -> str:
    return hashlib.sha256(PROMPT_TEMPLATES["entity_events_system"].encode("utf-8")).hexdigest()


def entity_events_path(collection: str, config: ResolvedPipelineConfig) -> Path:
    identity = {"passages": collection, "window": ENTITY_WINDOW, "carry": EVENT_CARRY_CHARS, "prompt": _events_prompt_hash(),
                "model": summary_model(config)}
    directory = Path(os.getenv("ENTITY_CARDS_DIR", "/data/entity-cards"))
    return directory / f"{collection}_events_{hashlib.sha256(canonical_json(identity).encode()).hexdigest()[:12]}.json"


def _extract_events(points: list[Any], before: str, config: ResolvedPipelineConfig) -> tuple[list[dict[str, Any]] | None, str]:
    body = "\n".join(point.payload["text"] for point in points)
    response = requests.post(os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat", json={
        "model": summary_model(config), "think": False, "stream": False, "format": "json",
        "messages": [{"role": "system", "content": PROMPT_TEMPLATES["entity_events_system"]},
                     {"role": "user", "content": f"Book: {points[0].payload['book']}\n\nTEXT BEFORE (only for who is who):\n{before}\n\nEXCERPT:\n{body}"}],
        "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 1500}}, timeout=(10, 900))
    response.raise_for_status()
    text = response.json().get("message", {}).get("content", "")
    try:
        events = json.loads(text).get("events", [])
    except (ValueError, AttributeError):
        return None, text
    return events if isinstance(events, list) else None, text


def build_entity_events(collection: str, config: ResolvedPipelineConfig, qdrant: QdrantClient) -> dict[str, Any]:
    """Extract the events between people of every entity window, given the ``EVENT_CARRY_CHARS`` of its section before
    it so the people it only calls "he" or "my father" are named, and write them with the passages that state them.
    One index-time model call per window, like the cards."""
    path = entity_events_path(collection, config)
    if path.exists():
        return {"path": str(path), "already_indexed": True}
    ordered = passages_in_order(qdrant, collection)
    position = {str(point.id): i for i, point in enumerate(ordered)}
    cache: dict[str, dict[str, Any]] = {}
    if _events_cache_path().exists():
        for line in _events_cache_path().read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            cache[row["key"]] = row
    called, events = False, []
    _events_cache_path().parent.mkdir(parents=True, exist_ok=True)
    with _events_cache_path().open("a", encoding="utf-8") as out:
        for points in scene_windows(ordered, ENTITY_WINDOW, ENTITY_WINDOW):
            members = [str(point.id) for point in points]
            key = hashlib.sha256(canonical_json({"members": members, "carry": EVENT_CARRY_CHARS, "prompt": _events_prompt_hash(),
                                                 "model": summary_model(config)}).encode()).hexdigest()
            if key not in cache:
                first, section = position[members[0]], (points[0].payload["book_file"], points[0].payload["section"])
                earlier = [point.payload["text"] for point in ordered[max(0, first - 20):first]
                           if (point.payload["book_file"], point.payload["section"]) == section]
                found, raw = _extract_events(points, "\n".join(earlier)[-EVENT_CARRY_CHARS:], config)
                called = True
                cache[key] = {"key": key, "members": members, "events": found, "raw": None if found is not None else raw}
                out.write(json.dumps(cache[key]) + "\n")
                out.flush()
            for event in cache[key]["events"] or []:
                if isinstance(event, dict) and isinstance(event.get("fact"), str) and event["fact"].strip():
                    events.append({"fact": event["fact"].strip(), "members": members,
                                   "people": [name for name in (event.get("who"), event.get("whom")) if isinstance(name, str) and name.strip()]})
    if called and summary_model(config) != config.generation_model.name:
        requests.post(os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/generate",
                      json={"model": summary_model(config), "keep_alive": 0}, timeout=(10, 60))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(events), encoding="utf-8")
    temporary.replace(path)
    return {"path": str(path), "events": len(events), "already_indexed": False}


def _norm(name: str) -> str:
    name = re.sub(r"[’']s\b", "", name.strip())
    name = re.sub(r"^(the|a|an)\s+", "", name, flags=re.I)
    return re.sub(r"\s+", " ", name).strip(" .,").casefold()


def _generic(name: str) -> bool:
    """An unnamed person or thing: "the woman", "a man"."""
    rest = name.split(" ", 1)[1] if " " in name else ""
    return bool(re.match(r"^(the|a|an|her|his)\s", name.strip(), re.I)) and not re.search(r"\b[A-ZÅÄÖ][a-zåäö]", rest)


def _kind(mention: dict[str, Any]) -> str:
    return str(mention.get("type") or "").lower()


def merge_entities(windows: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge the windows' mentions into cards (one per entity) and edges (entity — relation person), and the one-word
    names joined to a full name."""
    mentions = [entity | {"members": window["members"], "book": window["book"]}
                for window in windows for entity in window.get("entities") or []
                if isinstance(entity, dict) and isinstance(entity.get("name"), str) and entity["name"].strip()]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mention in mentions:
        if _kind(mention) == "person" and _generic(mention["name"]):
            continue
        groups[_norm(mention["name"])].append(mention)

    def proper(group: list[dict[str, Any]]) -> bool:
        """A name, not a description: every word of its most common spelling is capitalised."""
        name = Counter(mention["name"] for mention in group).most_common(1)[0][0]
        return all(word[:1].isupper() for word in re.sub(r"[’']s\b", "", name).split() if word.isalpha() or "." in word)

    def mostly_person(group: list[dict[str, Any]]) -> bool:
        return Counter(_kind(mention) for mention in group).most_common(1)[0][0] == "person"

    # A one-word person name joins the full person name containing it that most of its pairings use (Nesser -> Irene
    # Nesser); "Wasp" stays apart from "Wasp Enterprises", which is not a person.
    full: dict[str, Counter] = defaultdict(Counter)
    for key, group in groups.items():
        if len(key.split()) > 1 and proper(group) and mostly_person(group):
            for word in key.split():
                full[word][key] += len(group)
    alias = {}
    for key, group in groups.items():
        if len(key.split()) == 1 and full.get(key) and mostly_person(group):
            best, count = full[key].most_common(1)[0]
            if count >= 0.7 * sum(full[key].values()):
                alias[key] = best

    def canon(name: str) -> str:
        key = _norm(name)
        return alias.get(key, key)

    entities: dict[str, dict[str, Any]] = defaultdict(lambda: {"names": Counter(), "types": Counter(), "relations": Counter(), "facts": [],
                                                               "members": set(), "relation_types": defaultdict(Counter),
                                                               "relation_members": defaultdict(set)})
    for key, group in groups.items():
        entity_key = alias.get(key, key)
        entity = entities[entity_key]
        for mention in group:
            entity["names"][mention["name"]] += 1
            entity["types"][_kind(mention)] += 1
            owner = mention.get("of") if isinstance(mention.get("of"), str) else None
            if owner and not _generic(owner) and _norm(owner) not in ("unknown", "none", "null", "") and canon(owner) != entity_key:
                relation = (str(mention.get("relation") or "related to").strip(), canon(owner))
                entity["relations"][relation] += 1
                entity["relation_types"][relation][_kind(mention)] += 1
                entity["relation_members"][relation].update(mention["members"])
            if isinstance(mention.get("fact"), str) and mention["fact"]:
                entity["facts"].append((mention["fact"], mention["members"]))
            entity["members"].update(mention["members"])
    display = {key: entity["names"].most_common(1)[0][0] for key, entity in entities.items()}

    def shown(key: str) -> str:
        return display.get(key, key.title())

    cards, edges = [], []
    for key, entity in entities.items():
        types = ", ".join(kind for kind, _ in entity["types"].most_common(2) if kind)
        relations = "; ".join(f"{relation} {shown(owner)}" for (relation, owner), _ in entity["relations"].most_common(3))
        facts = list(dict.fromkeys(fact for fact, _ in entity["facts"]))
        cards.append({"key": key, "text": f"{shown(key)} ({types}){'. ' + relations if relations else ''}. " + " ".join(facts[:4]),
                      "members": sorted(entity["members"]), "mentions": sum(entity["names"].values()),
                      "types": [kind for kind, _ in entity["types"].most_common(3) if kind], "facts": facts})
        for (relation, owner), count in entity["relations"].items():
            surname = shown(owner).split()[-1].lower()
            fact = next((fact for fact, _ in entity["facts"] if surname in fact.lower()), entity["facts"][0][0] if entity["facts"] else "")
            edges.append({"from": key, "to": owner, "relation": relation, "count": count,
                          "types": [kind for kind, _ in entity["relation_types"][(relation, owner)].most_common(3)],
                          "text": f"{shown(key)} — {relation} {shown(owner)}: {fact}",
                          "members": sorted(entity["relation_members"][(relation, owner)]), "names": list(entity["names"])})
    return {"cards": cards, "edges": edges, "alias": alias}
