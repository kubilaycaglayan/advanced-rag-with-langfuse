"""Resolve a named pipeline and explicit overrides without reading runtime defaults."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    from .agent import AgentSettings, instruction_fingerprint, tool_names
    from .identity import canonical_json
    from .pipeline_catalog import PipelineCatalog, fingerprint, load_catalog
    from .resolved_config import ResolvedPipelineConfig
except ImportError:
    from agent import AgentSettings, instruction_fingerprint, tool_names
    from identity import canonical_json
    from pipeline_catalog import PipelineCatalog, fingerprint, load_catalog
    from resolved_config import ResolvedPipelineConfig

MODEL_KEYS = {"embedding_model", "reranker_model", "generation_model", "scene_summary_model"}
IDENTITY_KEYS = {"corpus_checksum", "prompt_hashes", "engine", "pipeline", "agent", "index", "prompts", "models"}


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

    @property
    def version_fields(self) -> dict[str, Any]:
        return {"pipeline_id": self.pipeline_id, "pipeline_version": self.version,
                "pipeline_derived": self.derived, "pipeline_status": self.status}


def corpus_checksum() -> str:
    root = Path(os.getenv("CORPUS_DIR", Path(__file__).resolve().parents[1] / "corpus"))
    paths = sorted(root.glob("*.epub"))
    if len(paths) != 3:
        raise ValueError(f"expected three EPUBs for pinned corpus in {root}, found {len(paths)}")
    files = [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths]
    return hashlib.sha256(canonical_json(files).encode()).hexdigest()


def resolve(pipeline: str | None = None, overrides: Mapping[str, Any] | None = None, *,
            catalog: PipelineCatalog | None = None, engine: str | None = None,
            prompt_label: str | None = None, collection: str | None = None) -> ResolvedRun:
    catalog = catalog or load_catalog()
    if pipeline is None and engine is not None:
        if engine not in {"fixed", "agent"}:
            raise ValueError("engine must be fixed or agent")
        pipeline = {"fixed": "v1", "agent": "v2"}[engine]
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
    allowed = set(block["settings"]) | (MODEL_KEYS if block["engine"] == "fixed" else set())
    unknown = set(overrides) - allowed
    if unknown:
        raise ValueError(f"settings not used by {version}: {', '.join(sorted(unknown))}")
    if corpus_checksum() != block["index"]["corpus_checksum"]:
        raise ValueError(f"{version}: local corpus differs from pinned corpus checksum")
    values = dict(block["settings"])
    values.update(block["models"])
    if "generation" in overrides and isinstance(overrides["generation"], Mapping):
        overrides["generation"] = {**values["generation"], **overrides["generation"]}
    values.update(overrides)
    config = ResolvedPipelineConfig.from_mapping(values, use_environment=False)
    agent_settings = None
    if block["engine"] == "agent":
        agent_values = {key: value for key, value in block["agent"].items()
                        if key not in {"tools", "instruction_fingerprint"}}
        agent_settings = AgentSettings(**agent_values)
        if block["agent"]["tools"] != tool_names():
            raise ValueError(f"{version}: agent tool catalog differs from released version")
        if block["agent"]["instruction_fingerprint"] != instruction_fingerprint():
            raise ValueError(f"{version}: agent instructions differ from released version; publish a new version")
    try:
        from .indexer import index_identity
    except ImportError:
        from indexer import index_identity
    actual_collection = index_identity(config)[0]
    changes_index = bool(set(overrides) & {"passage_chars", "min_passage_chars", "passage_overlap", "embedding_model"})
    expected_collection = actual_collection if changes_index else block["index"]["collection"]
    if not changes_index and actual_collection != expected_collection:
        raise ValueError(f"{version}: pinned index {expected_collection!r} differs from current index identity {actual_collection!r}")
    if collection is not None and collection != expected_collection:
        raise ValueError(f"{version}: collection must be {expected_collection!r}, got {collection!r}")
    released_fingerprint = catalog.releases.get(version) or fingerprint(block)
    digest = hashlib.sha256(canonical_json({"id": version, "fingerprint": released_fingerprint,
                                            "overrides": overrides}).encode()).hexdigest()[:8]
    prefix = "draft" if block["status"] == "draft" else "derived" if overrides else "pipeline"
    return ResolvedRun(version, block["status"], block["engine"], config, agent_settings,
                       dict(block["prompts"]), {**block["index"], "collection": expected_collection},
                       f"{prefix}-{version}-{digest}", bool(overrides), overrides, released_fingerprint)
