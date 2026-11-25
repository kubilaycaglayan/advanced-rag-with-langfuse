"""context / citations responsibilities."""
from __future__ import annotations

from typing import Any


def _book_short(book: str | None) -> str:
    if not book:
        return "?"
    if "Dragon" in book:
        return "Dragon Tattoo"
    if "Fire" in book:
        return "Played with Fire"
    if "Hornet" in book:
        return "Hornet's Nest"
    return book


def _passage(row: dict[str, Any], chars: int) -> dict[str, Any]:
    text = (row.get("text") or "").replace("\n", " ")
    return {"id": str(row["id"])[:8], "book": _book_short(row.get("book")), "chapter": row.get("chapter"),
            "paragraph": row.get("paragraph"),
            "score": round(float(row["score"]), 3) if row.get("score") is not None else None,
            "text": text[:chars] + ("…" if len(text) > chars else "")}


def _scene_member(row: dict[str, Any], chars: int) -> dict[str, Any]:
    """One passage of a scene: reading order and ids, without the ranking fields search results carry."""
    text = (row.get("text") or "").replace("\n", " ")
    return {"id": str(row["id"])[:8], "book": _book_short(row.get("book")), "chapter": row.get("chapter"),
            "paragraph": row.get("paragraph"), "text": text[:chars] + ("…" if len(text) > chars else "")}
