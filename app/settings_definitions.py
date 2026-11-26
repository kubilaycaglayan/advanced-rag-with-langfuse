"""Typed agent settings and embedded runtime limits, with documentation metadata.

Defaults describe new settings objects. Released catalog values take precedence in
resolution. Runtime limits have no user override surface; changes to their effective
values participate in answer-cache identity and experiment provenance.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import math
from typing import Any


@dataclass(frozen=True)
class Definition:
    unit: str
    explanation: str
    source: str
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    approximate_tokens: bool = False

    def validate(self, name: str, value: Any, expected: type) -> None:
        if expected is float:
            valid = type(value) in (int, float) and math.isfinite(value)
        else:
            valid = type(value) is expected
        if not valid:
            raise ValueError(f'{name} must be {expected.__name__}')
        if expected is str and not value.strip():
            raise ValueError(f'{name} must be a non-empty string')
        if self.minimum is not None and value < self.minimum:
            raise ValueError(f'{name} must be at least {self.minimum:g}')
        if self.maximum is not None and value > self.maximum:
            raise ValueError(f'{name} must be at most {self.maximum:g}')
        if self.choices and value not in self.choices:
            raise ValueError(f'{name} must be one of {", ".join(self.choices)}')


def setting(default: Any, unit: str, explanation: str, source: str, **constraints: Any):
    return field(default=default, metadata={'definition': Definition(unit, explanation, source, **constraints)})


def validate_settings(instance: Any) -> None:
    for item in fields(instance):
        definition = item.metadata['definition']
        # All defaults are primitive values and specify the accepted runtime type.
        definition.validate(item.name, getattr(instance, item.name), type(item.default))


@dataclass(frozen=True)
class TargetAgentSettings:
    model: str = setting('qwen3.6:35b', 'model name', 'Answering-agent model; separate from retrieval transformation models.', 'app/models/agent.py')
    provider: str = setting('ollama', 'provider', 'Existing answering-agent adapter.', 'app/models/agent.py', choices=('ollama', 'openai'))
    max_turns: int = setting(10, 'turns', 'Maximum model-selection turns; verification and synthesis are separate calls.', 'app/agent/runner.py', minimum=0)
    max_tool_calls: int = setting(16, 'calls', 'Ordinary tool exit threshold; incremented before dispatch; rejection branches can skip checking.', 'app/agent/runner.py', minimum=0)
    min_tool_calls: int = setting(4, 'calls', 'Investigation minimum; speech-hint submission can use one call.', 'app/agent/tools/submission.py', minimum=0)
    timeout_seconds: float = setting(900.0, 'seconds', 'Elapsed allowance checked before model turns; includes preparation and can be exceeded by in-flight work.', 'app/agent/runner.py', minimum=0)
    context_length: int = setting(16384, 'tokens', 'Ollama num_ctx; not sent as an OpenAI context override.', 'app/models/agent.py', minimum=1)
    num_predict: int = setting(1600, 'tokens', 'Requested output limit; mapped to the selected provider output-limit parameter.', 'app/models/agent.py', minimum=1)
    think: bool = setting(False, 'boolean', 'Ollama thinking flag; OpenAI uses reasoning_effort.', 'app/models/agent.py')
    snippet_chars: int = setting(300, 'characters', 'Displayed retrieval snippet length.', 'app/agent/tools/search.py', minimum=0)
    scene_candidate_count: int = setting(30, 'scenes', 'Scene candidate pool before scene selection.', 'app/agent/tools/search.py', minimum=1, maximum=100)
    initial_scene_probe: bool = setting(True, 'boolean', 'Gather an initial scene before model tool selection; override name is automatic_scene_search.', 'app/agent/runner.py')
    reasoning_effort: str = setting('none', 'effort', 'OpenAI none uses Chat Completions; other efforts use Responses.', 'app/models/agent.py', choices=('none', 'low', 'medium', 'high', 'xhigh', 'max'))

    def __post_init__(self) -> None:
        validate_settings(self)

    def with_model(self, model: str) -> TargetAgentSettings:
        return type(self)(**{**self.__dict__, 'model': model})


@dataclass(frozen=True)
class AgentSettings(TargetAgentSettings):
    # Retain the released v2.16 schema; the target configuration has no early stop.
    premise_early_stop: bool = setting(False, 'boolean', 'v2.16 compatibility only; absent from the target configuration.', 'app/agent/runner.py')


@dataclass(frozen=True)
class RuntimeLimits:
    nudge_limit: int = setting(2, 'nudges', 'Shared allowance for minimum-investigation and no-tool nudges.', 'app/agent/runner.py', minimum=0)
    compaction_recent_tools: int = setting(6, 'messages', 'Latest tool messages kept intact; compaction does not impose a final input bound.', 'app/context/conversation.py', minimum=1)
    compaction_chars: int = setting(22000, 'characters', 'Content-size trigger; excludes tool schemas and structured tool arguments.', 'app/context/conversation.py', minimum=0, approximate_tokens=True)
    compaction_ids: int = setting(8, 'IDs', 'Maximum matching passage IDs retained per older compacted tool result.', 'app/context/conversation.py', minimum=0)
    tool_result_chars: int = setting(9000, 'characters', 'Displayed JSON payload prefix before the existing ellipsis; not a tokenizer limit.', 'app/agent/protocol.py', minimum=0, approximate_tokens=True)
    http_connect_seconds: int = setting(10, 'seconds', 'Connection timeout for answering-agent HTTP calls.', 'app/models/agent.py', minimum=1)
    ollama_read_seconds: int = setting(900, 'seconds', 'Ollama answering-agent HTTP read timeout.', 'app/models/agent.py', minimum=1)
    openai_chat_read_seconds: int = setting(180, 'seconds', 'OpenAI Chat Completions HTTP read timeout.', 'app/models/agent.py', minimum=1)
    openai_responses_read_seconds: int = setting(300, 'seconds', 'OpenAI Responses HTTP read timeout.', 'app/models/agent.py', minimum=1)

    def __post_init__(self) -> None:
        validate_settings(self)


RUNTIME_LIMITS = RuntimeLimits()


def runtime_limits() -> RuntimeLimits:
    return RUNTIME_LIMITS


def runtime_settings_manifest() -> dict[str, Any]:
    return asdict(runtime_limits())


def validate_agent_value(name: str, value: Any) -> None:
    item = next(item for item in fields(AgentSettings) if item.name == name)
    item.metadata['definition'].validate(name, value, type(item.default))
