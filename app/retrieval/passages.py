"""retrieval / passages responsibilities."""
from __future__ import annotations

from app.retrieval.search import _keyword_index
from app.retrieval.search import _passage_position
from typing import Any


def _row_index(collection: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    rows = _keyword_index(collection)[0]
    return {row["id"]: row for row in rows}, rows



def _resolve_id(collection: str, wanted: str) -> tuple[dict[str, Any] | None, str]:
    """Resolve a full or 8-character id; return (row, error)."""
    wanted = (wanted or "").strip().strip("[]")
    by_id, _ = _row_index(collection)
    if wanted in by_id:
        return by_id[wanted], ""
    matches = [row for key, row in by_id.items() if key.startswith(wanted)] if len(wanted) >= 6 else []
    if len(matches) == 1:
        return matches[0], ""
    if len(matches) > 1:
        return None, f"id {wanted!r} is ambiguous ({len(matches)} passages)"
    return None, f"no passage with id {wanted!r}"



def _scene_member_rows(collection: str, members: list[str]) -> list[dict[str, Any]]:
    """The scene's passages in reading order (a window is stored in order, but never trust storage order)."""
    by_id, _ = _row_index(collection)
    rows = [by_id[member] | {"id": member} for member in members if member in by_id]
    return sorted(rows, key=_passage_position)

