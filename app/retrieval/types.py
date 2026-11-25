"""Passage payloads shared by search and evidence consumers."""
from typing import NotRequired, TypedDict


class Passage(TypedDict):
    id: str
    text: str
    book: NotRequired[str]
    chapter: NotRequired[str | None]
    section: NotRequired[str]
    paragraph: NotRequired[int]
    part: NotRequired[int]
    keyword_score: NotRequired[float]
    score: NotRequired[float]
