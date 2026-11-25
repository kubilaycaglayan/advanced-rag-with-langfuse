"""agent / protocol responsibilities."""
from __future__ import annotations

from typing import Any
import json
import re


def _clip(payload: Any, limit: int = 9000) -> str:
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _int(args: dict[str, Any], key: str, default: int, low: int = 1, high: int = 12) -> int:
    try:
        value = int(args.get(key, default))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _parse_text_tool(content: str) -> tuple[str, dict[str, Any]] | None:
    """A tool call printed as JSON when the model does not use native tool calls."""
    if not content:
        return None
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    for candidate in (text, *re.findall(r"\{.*\}", text, re.S)):
        try:
            value = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and isinstance(value.get("tool"), str):
            arguments = value.get("arguments", value.get("args", {}))
            return value["tool"], arguments if isinstance(arguments, dict) else {}
        if isinstance(value, dict) and isinstance(value.get("name"), str) and ("arguments" in value or "args" in value):
            arguments = value.get("arguments", value.get("args", {}))
            return value["name"], arguments if isinstance(arguments, dict) else {}
    return None

