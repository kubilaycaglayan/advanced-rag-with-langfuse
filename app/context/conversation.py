"""context / conversation responsibilities."""
from __future__ import annotations

from app.settings_definitions import runtime_limits
from typing import Any
import json
import re


def _compact(messages: list[dict[str, Any]], keep: int | None = None, budget: int | None = None) -> None:
    """Drop the body of older tool results when the conversation grows; their ids stay for read_passage."""
    keep = runtime_limits().compaction_recent_tools if keep is None else keep
    budget = runtime_limits().compaction_chars if budget is None else budget
    tool_indexes = [index for index, message in enumerate(messages) if message.get("role") == "tool"]
    total = sum(len(message.get("content") or "") for message in messages)
    if total <= budget:
        return
    for index in tool_indexes[:-keep]:
        content = messages[index].get("content") or ""
        ids = list(dict.fromkeys(re.findall(r'"id": "([0-9a-f]{8})"', content)))
        messages[index] = {"role": "tool", "tool_call_id": messages[index].get("tool_call_id"), "content": json.dumps(
            {"compacted": True, "ids": ids[:runtime_limits().compaction_ids], "note": "earlier result compacted to save context; read_passage can reopen an id"})}
