"""agent / state responsibilities."""
from __future__ import annotations

from app.context.evidence import EvidenceState
from app.settings_definitions import AgentSettings
from app.agent.prompts import SYSTEM_PROMPT
from app.pipelines.config import ResolvedPipelineConfig
from dataclasses import dataclass
from dataclasses import field
from typing import Any


@dataclass
class AgentState(EvidenceState):
    question: str
    collection: str
    config: ResolvedPipelineConfig
    settings: AgentSettings
    started: float
    system_prompt: str = SYSTEM_PROMPT
    asked: str = ""
    name_notes: list[dict[str, str]] = field(default_factory=list)
    tool_calls: int = 0
    turns: int = 0
    nudges: int = 0
    resolved_names: set[str] = field(default_factory=set)
    coverage_checks: int = 0
    speech_hint: dict[str, str] | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    rejected_answers: set[str] = field(default_factory=set)
    premise_evidence: list[str] = field(default_factory=list)
    search_history: list[tuple[str, set[str]]] = field(default_factory=list)
