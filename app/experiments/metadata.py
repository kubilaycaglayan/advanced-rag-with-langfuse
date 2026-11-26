"""experiments / metadata responsibilities."""
from __future__ import annotations

from app.settings_definitions import runtime_settings_manifest
from app.corpus_profiles import profile_identity
from app.corpus_profiles import prompt_identity
from app.evaluation.specs import JUDGE_MODELS
from app.evaluation.specs import evaluator_manifest
from app.identity import canonical_json
from app.identity import evaluator_identity
from app.identity import source_manifest
from app.indexing.passages import corpus_paths
from app.pipelines.config import ResolvedPipelineConfig
from app.pipelines.config import resolve_ollama_model
from app.pipelines.resolver import ResolvedRun
from pathlib import Path
from typing import Any
import hashlib
import json
import os


_EXPERIMENT_PROPAGATED_METADATA = frozenset({
    "execution_id", "pipeline_id", "pipeline_version", "pipeline_derived", "evaluator_id",
    "dataset_version", "variant_label", "snapshot_sha256", "correctness_evaluator",
    "answer_cache_mode", "agent_provider", "agent_model", "agent_reasoning_effort",
    "agent_think", "agent_context_length",
})


def pack_experiment_metadata(metadata: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Propagate join keys and preserve the complete metadata as one observation attribute."""
    propagated = {key: value for key, value in metadata.items() if key in _EXPERIMENT_PROPAGATED_METADATA}
    return propagated, json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "__dict__"):
        return {k: _jsonable(v) for k, v in vars(value).items() if not k.startswith("_")}
    return value


def _fingerprints(config: ResolvedPipelineConfig, managed_evaluators: dict[str, Any],
                  correctness_name: str, resolved: ResolvedRun) -> tuple[dict[str, Any], dict[str, Any], str]:
    repo_root = Path(__file__).resolve().parents[2]
    sources = source_manifest(str(repo_root))
    corpus_files = corpus_paths()
    corpus_manifest = [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in corpus_files]
    corpus_checksum = hashlib.sha256(canonical_json(corpus_manifest).encode()).hexdigest()
    enriched = config.manifest()
    enriched["prompt_hashes"] = {}
    enriched["generation_model"] = config.generation_model.__dict__
    enriched["embedding_model"] = {"name": config.embedding_model.name, "revision": config.embedding_model.revision}
    enriched["reranker_model"] = {"name": config.reranker_model.name, "revision": config.reranker_model.revision}
    enriched["corpus_checksum"] = corpus_checksum
    enriched["corpus_id"] = resolved.corpus_id
    enriched["profile_identity"] = profile_identity()
    enriched["prompt_identity"] = prompt_identity()
    pipeline = {**resolved.version_fields, "fingerprint": resolved.fingerprint,
                 "git_revision": sources["git_revision"], "dirty": sources["dirty"],
                 "source_fingerprint": sources["source_fingerprint"], "resolved_config": enriched,
                 "corpus_checksum": corpus_checksum}
    pipeline["source_manifest"] = sources
    pipeline["corpus_manifest"] = corpus_manifest
    pipeline["agent_settings"] = resolved.agent_settings.__dict__
    pipeline["runtime_settings"] = runtime_settings_manifest()
    evaluator_model_name = os.getenv("EVALUATOR_MODEL", "qwen3:8b")
    evaluator_endpoint = os.getenv("EVALUATOR_OLLAMA_URL") or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    try:
        evaluator_model = resolve_ollama_model(evaluator_model_name, evaluator_endpoint).__dict__
    except Exception:
        evaluator_model = {"name": evaluator_model_name, "digest": None}
    if correctness_name in JUDGE_MODELS:
        executor, judge_model, _ = JUDGE_MODELS[correctness_name]
        evaluator_model = {"name": judge_model, "digest": None, "executor": executor}
    evaluator_prompt = canonical_json({"specs": evaluator_manifest(), "managed": managed_evaluators,
                                       "prompts": {}})
    evaluator_code = hashlib.sha256((Path(__file__).resolve().parents[1] / "evaluation" / "judges.py").read_bytes()).hexdigest()
    evaluator = evaluator_identity(model=evaluator_model, settings={"temperature": 0, "stream": False, "format": "json"},
                                   rubric=evaluator_prompt, prompt=evaluator_prompt, code_version=f"evaluation.py:{evaluator_code}")
    return pipeline, {"evaluator_id": evaluator, "managed_evaluators": managed_evaluators,
                      "model": evaluator_model, "specs": evaluator_manifest(),
                      "settings": {"temperature": 0, "stream": False, "format": "json"},
                      "code_fingerprint": evaluator_code}, corpus_checksum
