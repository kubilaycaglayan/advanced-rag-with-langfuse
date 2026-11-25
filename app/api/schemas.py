"""api / schemas responsibilities."""
from __future__ import annotations

from pydantic import BaseModel
from pydantic import Field
from pydantic import IPvAnyAddress
from typing import Any



class AskRequest(BaseModel):
    model_config = {"extra": "forbid"}
    question: str = Field(min_length=1)
    pipeline: str | None = None
    settings: Any = None
    mode: str | None = Field(default=None, pattern="^(baseline|hyde|query_expansion|hyde_query_expansion|full)$")
    engine: str | None = Field(default=None, pattern="^agent$")
    passage_chars: int | None = Field(default=None, ge=1)
    collection: str | None = None
    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    user_id: str | None = Field(default=None, min_length=1, max_length=200)
    source: str = Field(default="api", pattern="^(api|frontend)$")
    client_ip: IPvAnyAddress | None = None
    production: bool = False
    cache_mode: str = Field(default="use", pattern="^(use|bypass|refresh)$")
    cache_layers: list[str] | None = None



class IndexRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)
    pipeline: str | None = None
    settings: Any = None
    explicit_rebuild: bool = False



class CacheFeedbackRequest(BaseModel):
    trace_id: str = Field(pattern="^[0-9a-f]{32}$")
    owner_id: str = Field(min_length=1, max_length=200)
    helpful: bool

