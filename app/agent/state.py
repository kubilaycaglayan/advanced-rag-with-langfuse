"""agent / state responsibilities."""
from __future__ import annotations

from app.context.evidence import EvidenceState
from app.settings_definitions import AgentSettings, TargetAgentSettings
from app.agent.prompts import SYSTEM_PROMPT
from app.pipelines.config import ResolvedPipelineConfig
from dataclasses import dataclass
from dataclasses import field
from typing import Any, Callable, Literal


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


Route = Literal["prepare", "decide", "select", "tools", "review", "budget", "final", "done"]


@dataclass
class ExecutionState(AgentState):
    """Explicit in-memory orchestration state for the explicitly selected v2.17 path.

    This is not a durable checkpoint schema. Existing ordered evidence remains in
    the inherited state; the process-local start clock retains its current policy.
    """
    settings: TargetAgentSettings
    messages: list[dict[str, Any]] = field(default_factory=list)
    pending_reply: dict[str, Any] | None = None
    pending_content: str = ""
    pending_calls: list[dict[str, Any]] = field(default_factory=list)
    next_tool_index: int = 0
    candidate_answer: str = ""
    candidate_passage_ids: list[str] = field(default_factory=list)
    candidate_raw_answer: str | None = None
    candidate_stopped: str = ""
    submitted_payload: dict[str, Any] | None = None
    verification_supported: bool | None = None
    verification_reason: str = ""
    route: Route = "prepare"
    budget_reason: str | None = None
    budget_drafted: bool = False
    final_prepared: bool = False
    final_result: dict[str, Any] | None = None


@dataclass
class AgentRuntime:
    """Non-state execution resources; never included in evidence or checkpoints."""
    tool_specs: list[dict[str, Any]] = field(default_factory=list)
    on_event: Callable[[dict[str, Any]], None] | None = None
    root_observation: Any = None

    def emit(self, event: dict[str, Any]) -> None:
        if self.on_event:
            self.on_event(event)
