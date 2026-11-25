"""agent / tools / reading responsibilities."""
from __future__ import annotations

from app.agent.protocol import _int
from app.agent.state import AgentState
from app.context.citations import _passage
from app.retrieval.passages import resolve_passage_id
from app.retrieval.passages import passage_index
from app.retrieval.search import passage_position
from typing import Any
import re


def _tool_read_passage(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    wanted = str(args.get("id") or "")
    row, error = resolve_passage_id(state.collection, wanted)
    if row is None:
        return {"error": error}
    before = _int(args, "before", 1, 0, 3)
    after = _int(args, "after", 1, 0, 3)
    _, rows = passage_index(state.collection)
    section = [item for item in rows if item.get("book_file") == row.get("book_file") and item.get("section") == row.get("section")]
    section.sort(key=passage_position)
    position = next((index for index, item in enumerate(section) if item["id"] == row["id"]), None)
    window = section[max(0, (position or 0) - before): (position or 0) + after + 1] if position is not None else [row]
    state.remember(window)
    state.focus_on(window)
    return {"passage": _passage(row, 1600),
            "neighbours": [_passage(item, 500) for item in window if item["id"] != row["id"]]}


def _tool_read_chapter(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    book = str(args.get("book") or "").strip()
    chapter = str(args.get("chapter") or "").strip()
    if not book or not chapter:
        return {"error": "book and chapter are required"}
    offset = _int(args, "offset", 0, 0, 200)
    limit = _int(args, "limit", 8, 1, 12)
    _, rows = passage_index(state.collection)
    books = sorted({row.get("book") or "" for row in rows})
    matched_books = [title for title in books if book.casefold() in title.casefold()]
    if len(matched_books) != 1:
        return {"error": f"book {book!r} matched {len(matched_books)} books", "books": books}
    title = matched_books[0]
    in_book = [row for row in rows if row.get("book") == title]
    chapters = sorted({row.get("chapter") or "" for row in in_book})
    if re.fullmatch(r"\d+", chapter):
        matched = [name for name in chapters if re.match(rf"CHAPTER\s+{chapter}\b", name, re.I)]
    else:
        matched = [name for name in chapters if chapter.casefold() in name.casefold()]
    if len(matched) != 1:
        return {"error": f"chapter {chapter!r} matched {len(matched)} chapters", "chapters": chapters}
    chapter_name = matched[0]
    paragraphs = sorted((row for row in in_book if row.get("chapter") == chapter_name), key=passage_position)
    window = paragraphs[offset: offset + limit]
    state.remember(window)
    return {"book": title, "chapter": chapter_name, "total_paragraphs": len(paragraphs), "offset": offset,
            "passages": [_passage(row, 500) for row in window],
            "note": "call again with a larger offset to continue"}

