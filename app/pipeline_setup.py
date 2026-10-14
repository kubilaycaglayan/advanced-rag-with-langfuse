"""Pipeline setup identity for interactive questions.

Keep this calculation aligned with the pipeline half of experiments._fingerprints.
It lives separately so an interactive request does not load evaluator assets.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

try:
    from .identity import canonical_json, pipeline_identity, source_manifest
    from .indexer import corpus_paths
    from .resolved_config import ResolvedPipelineConfig, resolve_ollama_model
except ImportError:
    from identity import canonical_json, pipeline_identity, source_manifest
    from indexer import corpus_paths
    from resolved_config import ResolvedPipelineConfig, resolve_ollama_model


def current_pipeline_setup(config: ResolvedPipelineConfig, prompt_versions: dict[str, Any]) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    sources = source_manifest(str(root))
    corpus_manifest = [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                       for path in corpus_paths()]
    corpus_checksum = hashlib.sha256(canonical_json(corpus_manifest).encode()).hexdigest()
    enriched = config.manifest()
    enriched["prompt_hashes"] = {name: hashlib.sha256(canonical_json(asset).encode()).hexdigest()
                                  for name, asset in prompt_versions.items()}
    try:
        generation_model = resolve_ollama_model(config.generation_model.name,
                                                os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")).__dict__
    except Exception:
        generation_model = {"name": config.generation_model.name, "digest": None}
    enriched["generation_model"] = generation_model
    enriched["embedding_model"] = {"name": config.embedding_model.name, "revision": config.embedding_model.revision}
    enriched["reranker_model"] = {"name": config.reranker_model.name, "revision": config.reranker_model.revision}
    enriched["corpus_checksum"] = corpus_checksum
    return pipeline_identity(git_revision=sources["git_revision"], dirty=sources["dirty"],
                             source_fingerprint=sources["source_fingerprint"], resolved_config=enriched,
                             corpus_checksum=corpus_checksum)
