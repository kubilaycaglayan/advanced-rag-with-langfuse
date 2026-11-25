"""Typed, serializable resolved pipeline configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from dataclasses import replace
from functools import lru_cache
import json
import os
import math
from typing import Any, Mapping
from urllib.error import URLError
from urllib.request import urlopen


@dataclass(frozen=True)
class ModelIdentity:
    name: str
    digest: str | None = None
    revision: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("model name must be a non-empty string")
        if self.digest is not None and not isinstance(self.digest, str):
            raise ValueError("model digest must be a string when provided")
        if self.revision is not None and not isinstance(self.revision, str):
            raise ValueError("model revision must be a string when provided")


@dataclass(frozen=True)
class GenerationSettings:
    temperature: float = 0.0
    context_length: int = 8192
    output_budgets: tuple[int, ...] = (4096, 8192)

    def __post_init__(self) -> None:
        if isinstance(self.temperature, bool) or not isinstance(self.temperature, (int, float)) or not math.isfinite(self.temperature) or self.temperature < 0:
            raise ValueError("generation temperature must be a finite non-negative number")
        if isinstance(self.context_length, bool) or not isinstance(self.context_length, int) or self.context_length < 1:
            raise ValueError("generation context_length must be a positive integer")
        if not self.output_budgets or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in self.output_budgets):
            raise ValueError("generation output_budgets must contain positive integers")


@dataclass(frozen=True)
class EvaluatorSettings:
    model: ModelIdentity = ModelIdentity("qwen3:8b")
    temperature: float = 0.0
    stream: bool = False
    response_format: str = "json"


@dataclass(frozen=True)
class ResolvedPipelineConfig:
    retrieval_mode: str = "full"
    passage_chars: int = 1200
    embedding_model: ModelIdentity = ModelIdentity("sentence-transformers/multi-qa-MiniLM-L6-cos-v1")
    reranker_model: ModelIdentity = ModelIdentity("cross-encoder/ms-marco-MiniLM-L-6-v2")
    generation_model: ModelIdentity = ModelIdentity("qwen3:8b")
    generation: GenerationSettings = GenerationSettings()
    min_passage_chars: int = 400
    passage_overlap: int = 0
    expansion_count: int = 3
    hyde: bool = True
    parallel_transformations: bool = False
    name_completion: bool = True
    scene_window: int = 6
    scene_stride: int = 3
    scene_search_hits: int = 10
    scene_summary_model: ModelIdentity | None = ModelIdentity("gemma4:26b")
    scene_thinking: bool = False
    corpus_checksum: str = ""
    prompt_hashes: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        for name in ("embedding_model", "reranker_model", "generation_model"):
            if not isinstance(getattr(self, name), ModelIdentity):
                raise ValueError(f"{name} must be a model identity")
        if self.scene_summary_model is not None and not isinstance(self.scene_summary_model, ModelIdentity):
            raise ValueError("scene_summary_model must be a model identity or null")
        if not isinstance(self.generation, GenerationSettings):
            raise ValueError("generation must be GenerationSettings")
        bounds = {
            "passage_chars": (1, None), "min_passage_chars": (0, None),
            "passage_overlap": (0, 5), "expansion_count": (1, 10),
            "scene_window": (1, 20), "scene_stride": (1, self.scene_window),
            "scene_search_hits": (1, 100),
        }
        for name, (low, high) in bounds.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            if value < low or (high is not None and value > high):
                raise ValueError(f"{name} is out of range")
        if self.passage_overlap and not self.min_passage_chars:
            raise ValueError("passage_overlap requires min_passage_chars (paragraph merging)")
        for name in ("hyde", "parallel_transformations", "name_completion", "scene_thinking"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")
        if self.retrieval_mode not in {"baseline", "hyde", "query_expansion", "hyde_query_expansion", "full"}:
            raise ValueError(f"unsupported retrieval mode: {self.retrieval_mode}")
        if not isinstance(self.corpus_checksum, str):
            raise ValueError("corpus_checksum must be a string")
        if self.prompt_hashes is not None and (not isinstance(self.prompt_hashes, Mapping)
                or not all(isinstance(k, str) and isinstance(v, str) for k, v in self.prompt_hashes.items())):
            raise ValueError("prompt_hashes must map strings to strings")

    def manifest(self) -> dict[str, Any]:
        value = asdict(self)
        value["generation"]["output_budgets"] = list(self.generation.output_budgets)
        value["prompt_hashes"] = dict(self.prompt_hashes or {})
        return value

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None = None, *, use_environment: bool = True) -> "ResolvedPipelineConfig":
        """Validate a JSON config without accepting unknown or identity fields."""
        value = dict(value or {})
        defaults: dict[str, Any] = {
            "retrieval_mode": "full",
        }
        if use_environment:
            defaults.update({
                "passage_chars": int(os.getenv("PASSAGE_CHARS", "1200")),
                "min_passage_chars": int(os.getenv("MIN_PASSAGE_CHARS", "400")),
                "embedding_model": os.getenv("EMBEDDING_MODEL", "sentence-transformers/multi-qa-MiniLM-L6-cos-v1"),
                "reranker_model": os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"),
                "generation_model": os.getenv("GENERATION_MODEL", "qwen3:8b"),
            })
        defaults.update(value)
        value = defaults
        allowed = {field.name for field in fields(cls)}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown config fields: {', '.join(sorted(unknown))}")
        for key in ("embedding_model", "reranker_model", "generation_model", "scene_summary_model"):
            if key == "scene_summary_model" and value.get(key) is None:
                continue
            if key in value and isinstance(value[key], str):
                value[key] = ModelIdentity(value[key])
            elif key in value and isinstance(value[key], Mapping):
                try:
                    value[key] = ModelIdentity(**value[key])
                except TypeError as exc:
                    raise ValueError(f"{key} has invalid model identity fields") from exc
            elif key in value:
                raise ValueError(f"{key} must be a model name or model identity object")
        if "generation" in value:
            generation = value["generation"]
            if not isinstance(generation, Mapping):
                raise ValueError("generation must be an object")
            unknown_generation = set(generation) - {"temperature", "context_length", "output_budgets"}
            if unknown_generation:
                raise ValueError(f"unknown generation fields: {', '.join(sorted(unknown_generation))}")
            generation = dict(generation)
            if "output_budgets" in generation:
                if not isinstance(generation["output_budgets"], (list, tuple)):
                    raise ValueError("generation output_budgets must be an array")
                generation["output_budgets"] = tuple(generation["output_budgets"])
            try:
                value["generation"] = GenerationSettings(**generation)
            except TypeError as exc:
                raise ValueError("generation has invalid fields") from exc
        return cls(**value)


def resolve_ollama_model(model_name: str, base_url: str = "http://127.0.0.1:11434") -> ModelIdentity:
    """Resolve a local Ollama tag to its content digest for reproducible manifests."""
    try:
        with urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=5) as response:
            payload = json.load(response)
    except (OSError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"cannot resolve Ollama model identity from {base_url}") from exc
    for model in payload.get("models", []):
        if model.get("name") == model_name:
            digest = model.get("digest")
            if not digest:
                raise RuntimeError(f"Ollama model {model_name!r} has no reported digest")
            return ModelIdentity(name=model_name, digest=digest)
    raise RuntimeError(f"Ollama model {model_name!r} is not installed")


@lru_cache(maxsize=16)
def _resolve_huggingface_revision(model_name: str) -> str | None:
    """Resolve the current Hub commit, falling back to a locally cached snapshot."""
    try:
        from huggingface_hub import HfApi
        revision = HfApi().model_info(model_name, timeout=5).sha
        if revision:
            return revision
    except Exception:
        pass
    try:
        from huggingface_hub import try_to_load_from_cache
        cached_config = try_to_load_from_cache(model_name, "config.json")
        if isinstance(cached_config, str):
            return __import__("pathlib").Path(cached_config).parent.name
    except Exception:
        pass
    return None


def resolve_pipeline_model_identities(config: ResolvedPipelineConfig) -> ResolvedPipelineConfig:
    """Pin Hub models to commit SHAs when the Hub or local cache can identify them."""
    def resolve(identity: ModelIdentity) -> ModelIdentity:
        if identity.revision:
            return identity
        revision = _resolve_huggingface_revision(identity.name)
        return replace(identity, revision=revision) if revision else identity
    return replace(config, embedding_model=resolve(config.embedding_model), reranker_model=resolve(config.reranker_model))
