"""Resolve a named pipeline and explicit overrides without reading runtime defaults."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.corpus_config import corpus_config, corpus_id
from app.corpus_profiles import profile_identity, prompt_identity
from app.agent import AgentSettings, instruction_fingerprint, tool_names
from app.identity import canonical_json
from app.pipelines.catalog import PipelineCatalog, load_catalog
from app.pipelines.config import ResolvedPipelineConfig

IDENTITY_KEYS = {"corpus_checksum", "prompt_hashes", "engine", "pipeline", "agent", "index", "prompts", "models"}


@dataclass(frozen=True)
class ResolvedRun:
    version: str
    status: str
    engine: str
    config: ResolvedPipelineConfig
    agent_settings: AgentSettings
    prompts: dict[str, int]
    index: dict[str, str]
    pipeline_id: str
    derived: bool
    overrides: dict[str, Any]
    fingerprint: str
    corpus_id: str = "millennium"
    corpus_checksum: str = ""
    profile_id: str = "millennium"
    profile_identity: str = ""
    prompt_identity: str = ""

    @property
    def version_fields(self) -> dict[str, Any]:
        return {"pipeline_id": self.pipeline_id, "pipeline_version": self.version,
                "pipeline_derived": self.derived, "pipeline_status": self.status,
                "corpus_id": self.corpus_id, "corpus_checksum": self.corpus_checksum,
                "profile_id": self.profile_id, "profile_identity": self.profile_identity,
                "prompt_identity": self.prompt_identity}


def corpus_checksum() -> str:
    root = Path(os.getenv("CORPUS_DIR", corpus_config().books))
    paths = sorted(root.glob("*.epub"))
    if not paths:
        raise ValueError(f"no EPUBs found for corpus in {root}")
    files = [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths]
    return hashlib.sha256(canonical_json(files).encode()).hexdigest()


def resolve(pipeline: str | None = None, overrides: Mapping[str, Any] | None = None, *,
            catalog: PipelineCatalog | None = None, engine: str | None = None,
            collection: str | None = None) -> ResolvedRun:
    catalog = catalog or load_catalog()
    if pipeline is not None and (not isinstance(pipeline, str) or not pipeline):
        raise ValueError("pipeline must be a non-empty version id")
    if engine is not None and engine != "agent":
        raise ValueError("only the agent engine is supported")
    block = catalog.get(pipeline)
    version = block["id"]
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, Mapping):
        raise ValueError("settings must be an object")
    overrides = dict(overrides)
    identity = set(overrides) & IDENTITY_KEYS
    if identity:
        raise ValueError(f"identity keys cannot be settings: {', '.join(sorted(identity))}")
    agent_effort = overrides.get("agent_reasoning_effort")
    agent_provider = overrides.get("agent_provider")
    agent_model = overrides.get("agent_model")
    agent_think = overrides.get("agent_think")
    agent_context_length = overrides.get("agent_context_length")
    scene_candidate_count = overrides.get("scene_candidate_count")
    premise_early_stop = overrides.get("premise_early_stop")
    allowed = set(block["settings"])
    allowed.update({"agent_provider", "agent_model", "agent_think", "agent_context_length",
                    "automatic_scene_search", "scene_candidate_count", "premise_early_stop"})
    if block["agent"].get("provider") == "openai" or agent_provider == "openai":
        allowed.add("agent_reasoning_effort")
    unknown = set(overrides) - allowed
    if unknown:
        raise ValueError(f"settings not used by {version}: {', '.join(sorted(unknown))}")
    source_checksum = corpus_checksum()
    selected_id = corpus_id()
    values = dict(block["settings"])
    values.update(block["models"])
    if "generation" in overrides and isinstance(overrides["generation"], Mapping):
        overrides["generation"] = {**values["generation"], **overrides["generation"]}
    agent_override_keys = {"agent_provider", "agent_model", "agent_think", "agent_context_length",
                           "automatic_scene_search", "agent_reasoning_effort", "scene_candidate_count",
                           "premise_early_stop"}
    config_overrides = {key: value for key, value in overrides.items() if key not in agent_override_keys}
    values.update(config_overrides)
    config = ResolvedPipelineConfig.from_mapping(values, use_environment=False)
    agent_values = {key: value for key, value in block["agent"].items()
                    if key not in {"tools", "instruction_fingerprint", "conversation_handoff_fingerprint"}}
    agent_settings = AgentSettings(**agent_values)
    expected_handoff = block["agent"].get("conversation_handoff_fingerprint")
    actual_handoff = hashlib.sha256((Path(__file__).resolve().parents[1] / "agent_final_handoff.py").read_bytes()).hexdigest()
    if expected_handoff != actual_handoff:
        raise ValueError(f"{version}: conversation handoff differs from its pinned fingerprint")
    if agent_provider is not None:
        if agent_provider not in ("ollama", "openai"):
            raise ValueError("agent_provider must be ollama or openai")
        model = "gpt-6-luna" if agent_provider == "openai" else block["agent"]["model"]
        agent_settings = AgentSettings(**{**agent_settings.__dict__,
                                          "provider": agent_provider, "model": model})
    if agent_model is not None:
        if not isinstance(agent_model, str) or not agent_model.strip():
            raise ValueError("agent_model must be a non-empty string")
        if agent_settings.provider != "ollama":
            raise ValueError("agent_model can only be set for the ollama provider")
        agent_settings = AgentSettings(**{**agent_settings.__dict__, "model": agent_model.strip()})
    if agent_think is not None:
        if not isinstance(agent_think, bool):
            raise ValueError("agent_think must be a boolean")
        if agent_settings.provider != "ollama":
            raise ValueError("agent_think can only be set for the ollama provider")
        agent_settings = AgentSettings(**{**agent_settings.__dict__, "think": agent_think})
    if agent_context_length is not None:
        if type(agent_context_length) is not int or agent_context_length < 1:
            raise ValueError("agent_context_length must be a positive integer")
        if agent_settings.provider != "ollama":
            raise ValueError("agent_context_length can only be set for the ollama provider")
        agent_settings = AgentSettings(**{**agent_settings.__dict__,
                                          "context_length": agent_context_length})
    if "automatic_scene_search" in overrides:
        if not isinstance(overrides["automatic_scene_search"], bool):
            raise ValueError("automatic_scene_search must be a boolean")
        agent_settings = AgentSettings(**{**agent_settings.__dict__,
                                          "initial_scene_probe": overrides["automatic_scene_search"]})
    if scene_candidate_count is not None:
        if type(scene_candidate_count) is not int or not 1 <= scene_candidate_count <= 100:
            raise ValueError("scene_candidate_count must be an integer from 1 to 100")
        agent_settings = AgentSettings(**{**agent_settings.__dict__,
                                          "scene_candidate_count": scene_candidate_count})
    if premise_early_stop is not None:
        if not isinstance(premise_early_stop, bool):
            raise ValueError("premise_early_stop must be a boolean")
        agent_settings = AgentSettings(**{**agent_settings.__dict__,
                                          "premise_early_stop": premise_early_stop})
    if agent_effort is not None:
        if agent_effort not in {"none", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("agent_reasoning_effort must be none, low, medium, high, xhigh, or max")
        agent_settings = AgentSettings(**{**agent_settings.__dict__, "reasoning_effort": agent_effort})
    if block["agent"]["tools"] != tool_names():
        raise ValueError(f"{version}: agent tool catalog differs from released version")
    expected_instructions = block["agent"]["instruction_fingerprint"]
    actual_instructions = instruction_fingerprint()
    if selected_id == "millennium" and expected_instructions != actual_instructions:
        raise ValueError(f"{version}: agent instructions differ from released version; publish a new version")
    try:
        from app.indexing.passages import index_identity
    except ImportError:
        from indexer import index_identity
    expected_collection = index_identity(config)[0]
    if collection is not None and collection != expected_collection:
        raise ValueError(f"{version}: collection must be {expected_collection!r}, got {collection!r}")
    released_fingerprint = catalog.releases[version]
    digest = hashlib.sha256(canonical_json({"id": version, "fingerprint": released_fingerprint,
                                            "overrides": overrides}).encode()).hexdigest()[:8]
    prefix = "derived" if overrides else "pipeline"
    selected_corpus = corpus_config()
    return ResolvedRun(version, block["status"], block["engine"], config, agent_settings,
                       dict(block["prompts"]), {**block["index"], "collection": expected_collection},
                       f"{prefix}-{version}-{digest}", bool(overrides), overrides, released_fingerprint,
                       corpus_id(), source_checksum, selected_corpus.profile_id,
                       profile_identity(), prompt_identity())
