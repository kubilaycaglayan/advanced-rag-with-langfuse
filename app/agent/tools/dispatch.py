"""agent / tools / dispatch responsibilities."""
from __future__ import annotations

from app.agent.state import AgentState
from app.agent.tools.accounts import _tool_true_account
from app.agent.tools.entities import _tool_entity_card
from app.agent.tools.entities import _tool_find_connections
from app.agent.tools.entities import _tool_find_names
from app.agent.tools.reading import _tool_read_chapter
from app.agent.tools.reading import _tool_read_passage
from app.agent.tools.scenes import _tool_read_scene
from app.agent.tools.scenes import _tool_scene_moment
from app.agent.tools.scenes import _tool_scene_search
from app.agent.tools.search import _tool_expand_query
from app.agent.tools.search import _tool_keyword_search
from app.agent.tools.search import _tool_semantic_search
from app.agent.tools.submission import _tool_submit_answer
from app.cache.intermediate import cache_value as _cache_value
from app.retrieval.passages import _row_index
from typing import Any


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
    if name in {"read_scene", "read_passage", "read_chapter", "entity_card",
                "find_connections", "find_names"}:
        def read() -> dict[str, Any]:
            capture = {"remembered": [], "focused": []}
            previous_capture = state.read_capture
            state.read_capture = capture
            try:
                payload = tools[name](state, args)
            finally:
                state.read_capture = previous_capture
            return {"payload": payload,
                    "remembered_ids": list(dict.fromkeys(capture["remembered"])),
                    "focused_ids": list(dict.fromkeys(capture["focused"]))}

        cached = _cache_value("tool_read", name,
            {"collection": state.collection, "question": state.question, "arguments": args},
            input={"tool": name, "arguments": args}, compute=read,
            trace_output=lambda value: value.get("payload"))
        by_id, _ = _row_index(state.collection)
        rows = [by_id[identifier] for identifier in cached["remembered_ids"] if identifier in by_id]
        state.remember(rows)
        focused = set(cached["focused_ids"])
        state.focus_on([row for row in rows if str(row["id"]) in focused])
        return cached["payload"], False
    return tools[name](state, args), False

