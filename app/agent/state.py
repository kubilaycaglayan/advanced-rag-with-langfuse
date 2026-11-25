"""agent / state responsibilities."""
from __future__ import annotations

from app.context.evidence import EvidenceState
from app.agent.prompts import SYSTEM_PROMPT
from app.pipelines.config import ResolvedPipelineConfig
from dataclasses import dataclass
from dataclasses import field
from typing import Any


@dataclass(frozen=True)
class AgentSettings:
    model: str = "qwen3.6:35b"
    provider: str = "ollama"
    max_turns: int = 10
    max_tool_calls: int = 16
    min_tool_calls: int = 4
    timeout_seconds: float = 900.0
    context_length: int = 16384
    num_predict: int = 1600
    think: bool = False
    snippet_chars: int = 300
    scene_candidate_count: int = 30
    initial_scene_probe: bool = True
    reasoning_effort: str = "none"
    premise_early_stop: bool = False

    def with_model(self, model: str) -> "AgentSettings":
        return AgentSettings(**{**self.__dict__, "model": model})


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
