"""context / conversation responsibilities."""
from __future__ import annotations

from typing import Any
import json
import re


def _compact(messages: list[dict[str, Any]], keep: int = 6, budget: int = 22000) -> None:
    """Drop the body of older tool results when the conversation grows; their ids stay for read_passage."""
    tool_indexes = [index for index, message in enumerate(messages) if message.get("role") == "tool"]
    total = sum(len(message.get("content") or "") for message in messages)
    if total <= budget:
        return
    for index in tool_indexes[:-keep]:
        content = messages[index].get("content") or ""
        ids = list(dict.fromkeys(re.findall(r'"id": "([0-9a-f]{8})"', content)))
        messages[index] = {"role": "tool", "tool_call_id": messages[index].get("tool_call_id"), "content": json.dumps(
            {"compacted": True, "ids": ids[:8], "note": "earlier result compacted to save context; read_passage can reopen an id"})}
