"""agent / prechecks responsibilities."""
from __future__ import annotations

from app.agent.state import AgentState
from app.agent.tools.accounts import _event_verb
from app.agent.tools.accounts import _tool_true_account
from app.agent.tools.coverage import _WHAT_HAPPENED
from app.agent.tools.coverage import _coverage_hint
from app.agent.tools.scenes import _tool_scene_moment
from app.agent.tools.search import _semantic_rows
from app.indexing.entities import _cache_path as entity_cache_path
from app.indexing.entities import entity_cards_path
from app.retrieval.entities import connection_pairs
from app.retrieval.entities import fact_sources
from app.retrieval.passages import passage_index
from app.retrieval.passages import scene_member_rows
from app.retrieval.scenes import scene_lookup
from app.retrieval.search import entity_anchors
from app.retrieval.search import entity_cards
from app.retrieval.search import keyword_search
from app.retrieval.search import name_pairs
from typing import Any
import difflib
import re


_CONNECTION_CUE = re.compile(r"\b(know|knew|known|learn|learned|learnt|meet|met|meeting|introduc\w*|relationship|related|"
                              r"connect\w*|affair|marry|married|hire|hired|gave|given|tell|told)\b", re.I)


def _normalize_question(state: AgentState) -> tuple[str, list[dict[str, str]]]:
    """Replace a name the books do not use with the closest book name (Mikhail -> Mikael Blomkvist)."""
    pairs, words = name_pairs(state.collection)
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
    data = entity_cards(str(path))
    anchors = entity_anchors(state.question, data)
    if len(anchors) < 2:
        return None
    mentions = {card["key"]: card.get("mentions", 0) for card in data["cards"]}
    first, second = sorted(anchors, key=lambda key: mentions.get(key, 0), reverse=True)[:2]
    facts, edges = connection_pairs(data, first, second)
    if not facts:
        return None
    sources = fact_sources(str(entity_cache_path()))
    by_id, _ = passage_index(state.collection)
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
    data = entity_cards(str(path))
    anchors = entity_anchors(state.question, data)
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
    for row in keyword_search(state.question, state.collection, 5):
        keyword_rows.append(row | {"score": row.get("keyword_score")})
    state.remember(keyword_rows)
    extra_rows: list[dict[str, Any]] = []
    scenes = payload.get("scenes") or []
    if _SPEECH_CUES.search(state.question):
        anchors = set()
        path = entity_cards_path(state.collection, state.config)
        if path.exists():
            anchors = entity_anchors(state.question, entity_cards(str(path)))
        scored = []
        for scene in scenes:
            summary = scene.get("summary") or ""
            if not _SPEECH_CUES.search(summary):
                continue
            named = sum(1 for anchor in anchors if re.search(rf"\b{re.escape(anchor)}\b", summary.casefold()))
            scored.append((named, scene.get("score") or 0.0, scene))
        if scored:
            scene = max(scored, key=lambda item: (item[0], item[1]))[2]
            point, _ = scene_lookup(state.collection, state.config, scene["scene_id"])
            if point is not None:
                extra_rows = scene_member_rows(state.collection,
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


def _premise_probe(state: AgentState) -> str | None:
    """Put a direct counter-hypothesis beside a question that presumes a death."""
    match = re.search(r"\bwho\s+(?:killed|murdered)\s+([^?.,]+)", state.question, re.I)
    if not match:
        return None
    person = match.group(1).strip()
    rows = _semantic_rows(state, f"{person} is alive", 8)
    direct = [row for row in rows if re.search(r"\b(?:alive|surviv(?:ed|es)|still living)\b", row.get("text") or "", re.I)]
    if not direct:
        return None
    state.remember(direct, query=f"{person} is alive")
    state.focus_on(direct[:3])
    state.premise_evidence = [row["id"][:8] for row in direct[:3]]
    return ("Premise check: the question assumes a death. These passages may contradict that assumption. "
            "Resolve whether the person actually died before naming a killer; read the surrounding passage if needed.\n\n"
            + "\n\n".join(f"[{row['id'][:8]}] {(row.get('text') or '')[:900]}" for row in direct[:3]))
