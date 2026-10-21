"""Resolve a named pipeline and explicit overrides without reading runtime defaults."""
from __future__ import annotations

import hashlib
import ast
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    from .corpus_config import corpus_config, corpus_id
    from .corpus_profiles import profile_identity, prompt_identity
    from .agent import AgentSettings, instruction_fingerprint, tool_names
    from .identity import canonical_json
    from .pipeline_catalog import PipelineCatalog, fingerprint, load_catalog
    from .resolved_config import ResolvedPipelineConfig
except ImportError:
    from corpus_config import corpus_config, corpus_id
    from corpus_profiles import profile_identity, prompt_identity
    from agent import AgentSettings, instruction_fingerprint, tool_names
    from identity import canonical_json
    from pipeline_catalog import PipelineCatalog, fingerprint, load_catalog
    from resolved_config import ResolvedPipelineConfig

MODEL_KEYS = {"embedding_model", "reranker_model", "generation_model", "scene_summary_model"}
IDENTITY_KEYS = {"corpus_checksum", "prompt_hashes", "engine", "pipeline", "agent", "index", "prompts", "models"}
_V2_INSTRUCTION_FINGERPRINT = "e114bc0e9958ce609c6bdc9706eb46cbd00f54f4025a7b7acc77353dba42831d"
_V2_STABLE_LITERAL_FINGERPRINT = "91071f9aeafd4ad613de6c66cb4b9c80332811d3c992e6af8435e64c7d146b8a"
_V22_ORIGINAL_INSTRUCTION_FINGERPRINT = "b457df458c964b4d225d82d784b73bae7232c68c1c124ac120299a209085ae86"
_V22_PROVIDER_ADAPTER_COMPAT_FINGERPRINT = "edfc2ec1fbd340498afc2b139dc14f151a74de825c2d95428fe108a6b77ac720"
_V23_HIGH_REASONING_ADAPTER_FINGERPRINT = "d117d53070e4cf4ccaeab0db35444bb8a5db4a7ff3750dea91fc15e1786a528f"
_V25_SCENE_PROBE_FINGERPRINT = "4f3c86b9ec0ebe2f76328df25168cc4900e9ad6ecb8626c67780df12163042a8"
_V26_PROBE_TRACE_FINGERPRINT = "59696263473e1c7bec631f012986747b8efb222739e51fed2077cbc9f6ace6bb"


def _legacy_v2_instructions_unchanged() -> bool:
    """Recognize v2's original instruction literals after code-only reranking additions."""
    source = Path(__file__).resolve().parent
    literals: dict[str, list[str]] = {}
    for filename in ("agent.py", "prompt_templates.py"):
        tree = ast.parse((source / filename).read_text(encoding="utf-8"))
        literals[filename] = sorted(node.value for node in ast.walk(tree)
                                    if isinstance(node, ast.Constant) and isinstance(node.value, str))
    # These are retrieval data keys and a numeric sentinel introduced by reranking, not instructions.
    for value, count in (("id", 4), ("", 2), ("text", 2), ("-inf", 1)):
        for _ in range(count):
            try:
                literals["agent.py"].remove(value)
            except ValueError:
                return False
    digest = hashlib.sha256(json.dumps(literals, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode()).hexdigest()
    return digest == _V2_STABLE_LITERAL_FINGERPRINT


@dataclass(frozen=True)
class ResolvedRun:
    version: str
    status: str
    engine: str
    config: ResolvedPipelineConfig
    agent_settings: AgentSettings | None
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
            prompt_label: str | None = None, collection: str | None = None) -> ResolvedRun:
    catalog = catalog or load_catalog()
    if pipeline is not None and (not isinstance(pipeline, str) or not pipeline):
        raise ValueError("pipeline must be a non-empty version id")
    if pipeline is None and engine is not None:
        if engine not in {"fixed", "agent"}:
            raise ValueError("engine must be fixed or agent")
        pipeline = {"fixed": "v1", "agent": catalog.default}[engine]
    block = catalog.get(pipeline)
    version = block["id"]
    if engine is not None and engine != block["engine"]:
        raise ValueError(f"engine {engine!r} disagrees with pipeline {version}")
    if prompt_label is not None and block["status"] != "draft":
        raise ValueError("prompt_label is allowed only for draft pipelines")
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
    scene_candidate_count = overrides.get("scene_candidate_count")
    if version in {"v2.6", "v2.7", "v2.8", "v2.9"} and overrides.get("automatic_scene_search") is True and scene_candidate_count is None:
        # The validated automatic probe trials used 30 candidates; the v2.2-compatible default remains 20.
        overrides["scene_candidate_count"] = 30
        scene_candidate_count = 30
    allowed = set(block["settings"]) | (MODEL_KEYS if block["engine"] == "fixed" else set())
    if version in {"v2.6", "v2.7", "v2.8", "v2.9"}:
        allowed.update({"agent_provider", "automatic_scene_search", "scene_candidate_count"})
    if (block["engine"] == "agent" and
            (block.get("agent", {}).get("provider") == "openai" or agent_provider == "openai")):
        allowed.add("agent_reasoning_effort")
    unknown = set(overrides) - allowed
    if unknown:
        raise ValueError(f"settings not used by {version}: {', '.join(sorted(unknown))}")
    source_checksum = corpus_checksum()
    selected_id = corpus_id()
    if (selected_id == "millennium" and block["index"].get("corpus_checksum")
            and source_checksum != block["index"]["corpus_checksum"]):
        raise ValueError(f"{version}: local corpus differs from pinned corpus checksum")
    values = dict(block["settings"])
    values.update(block["models"])
    if "generation" in overrides and isinstance(overrides["generation"], Mapping):
        overrides["generation"] = {**values["generation"], **overrides["generation"]}
    agent_override_keys = {"agent_provider", "automatic_scene_search", "agent_reasoning_effort",
                           "scene_candidate_count"}
    config_overrides = {key: value for key, value in overrides.items() if key not in agent_override_keys}
    values.update(config_overrides)
    config = ResolvedPipelineConfig.from_mapping(values, use_environment=False)
    agent_settings = None
    if block["engine"] == "agent":
        agent_values = {key: value for key, value in block["agent"].items()
                        if key not in {"tools", "instruction_fingerprint"}}
        agent_settings = AgentSettings(**agent_values)
        if agent_provider is not None:
            if agent_provider not in ("ollama", "openai"):
                raise ValueError("agent_provider must be ollama or openai")
            model = "gpt-6-luna" if agent_provider == "openai" else block["agent"]["model"]
            agent_settings = AgentSettings(**{**agent_settings.__dict__,
                                              "provider": agent_provider, "model": model})
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
        if agent_effort is not None:
            if agent_effort not in {"none", "low", "medium", "high", "xhigh", "max"}:
                raise ValueError("agent_reasoning_effort must be none, low, medium, high, xhigh, or max")
            agent_settings = AgentSettings(**{**agent_settings.__dict__, "reasoning_effort": agent_effort})
        if block["agent"]["tools"] != tool_names():
            raise ValueError(f"{version}: agent tool catalog differs from released version")
        expected_instructions = block["agent"]["instruction_fingerprint"]
        actual_instructions = instruction_fingerprint()
        legacy_v2 = (version == "v2" and expected_instructions == _V2_INSTRUCTION_FINGERPRINT
                     and (_legacy_v2_instructions_unchanged() or actual_instructions in {
                         _V25_SCENE_PROBE_FINGERPRINT, _V26_PROBE_TRACE_FINGERPRINT}))
        legacy_v22 = (version == "v2.2" and expected_instructions == _V22_ORIGINAL_INSTRUCTION_FINGERPRINT
                      and actual_instructions in {_V22_PROVIDER_ADAPTER_COMPAT_FINGERPRINT,
                                                  _V23_HIGH_REASONING_ADAPTER_FINGERPRINT,
                                                  _V25_SCENE_PROBE_FINGERPRINT,
                                                  _V26_PROBE_TRACE_FINGERPRINT})
        compatible_v23_adapter = (version == "v2.3" and expected_instructions == _V22_PROVIDER_ADAPTER_COMPAT_FINGERPRINT
                                  and actual_instructions in {_V23_HIGH_REASONING_ADAPTER_FINGERPRINT,
                                                              _V25_SCENE_PROBE_FINGERPRINT,
                                                              _V26_PROBE_TRACE_FINGERPRINT})
        compatible_probe_trace = (version in {"v2.4", "v2.5", "v2.6", "v2.7"}
                                  and expected_instructions == _V25_SCENE_PROBE_FINGERPRINT
                                  and actual_instructions == _V26_PROBE_TRACE_FINGERPRINT)
        if expected_instructions != actual_instructions and not (legacy_v2 or legacy_v22 or compatible_v23_adapter
                                                                  or compatible_probe_trace):
            raise ValueError(f"{version}: agent instructions differ from released version; publish a new version")
    try:
        from .indexer import index_identity
    except ImportError:
        from indexer import index_identity
    actual_collection = index_identity(config)[0]
    changes_index = bool(set(overrides) & {"passage_chars", "min_passage_chars", "passage_overlap", "embedding_model"})
    expected_collection = (actual_collection if changes_index or selected_id != "millennium"
                           or block["index"].get("collection") is None else block["index"]["collection"])
    if not changes_index and actual_collection != expected_collection:
        raise ValueError(f"{version}: pinned index {expected_collection!r} differs from current index identity {actual_collection!r}")
    if collection is not None and collection != expected_collection:
        raise ValueError(f"{version}: collection must be {expected_collection!r}, got {collection!r}")
    released_fingerprint = catalog.releases.get(version) or fingerprint(block)
    digest = hashlib.sha256(canonical_json({"id": version, "fingerprint": released_fingerprint,
                                            "overrides": overrides}).encode()).hexdigest()[:8]
    prefix = "draft" if block["status"] == "draft" else "derived" if overrides else "pipeline"
    selected_corpus = corpus_config()
    return ResolvedRun(version, block["status"], block["engine"], config, agent_settings,
                       dict(block["prompts"]), {**block["index"], "collection": expected_collection},
                       f"{prefix}-{version}-{digest}", bool(overrides), overrides, released_fingerprint,
                       corpus_id(), source_checksum, selected_corpus.profile_id,
                       profile_identity(), prompt_identity())
